"""人工处理队列：把「超限且不可分」的块落成可查询的复核件。

职责：把不可嵌入的块写进 `campfire_manual_review`，并按条目整批替换其复核件。
边界：不判定哪些块需要人工处理（判定在 `chunking.py`）；不提供查询端点，运维直接查表。
参考：docs/技术设计/technical-details/RAG策略.md 第 1.2 节；细节见 `record_manual_reviews`、`build_excerpt` 的 docstring。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.modules.library.chunking import TARGET_MAX_CHARS, Chunk
from campfire.modules.library.models import ManualReviewItem

#: 复核件正文摘录的字符上界。
#:
#: 依据：复用同模块的目标块长 `TARGET_MAX_CHARS`（800）。复核人看到的正文量与一个
#: 正常嵌入的块相当，足以判断该在哪里切、该怎么改；没有测量支持另一个数字，就不自造
#: 阈值。上界存在的意义（CORE-11）是让本表的单行大小与源文件长度解耦——不可分块
#: 正是什么长度都可能，语料里已实测到 8,487 字符的表格。
MANUAL_REVIEW_EXCERPT_CHARS = TARGET_MAX_CHARS


class ManualReviewError(Exception):
    """复核件无法构造：块标记为需人工处理却没有给出原因。

    没有原因的复核件交不出去（复核人不知道要改什么），因此这是不变量被破坏，
    不补默认值（CORE-07 无静默兜底）。
    """


def build_excerpt(text: str, *, limit: int = MANUAL_REVIEW_EXCERPT_CHARS) -> str:
    """取正文摘录：超过上界时截断，并在末尾写明原文总长。

    为什么截断必须留痕：本表正是「不静默截断」的落点（RAG 策略第 1.2 节）。若摘录
    自己悄悄截断，复核人会把 800 字符当成该块的全部内容，而判断「要不要切、切在哪」
    最需要的信息恰是它到底有多长。

    Args:
        text: 块正文（`Chunk.text`，已含章节路径前缀）。
        limit: 保留的字符上界，缺省 `MANUAL_REVIEW_EXCERPT_CHARS`。

    Returns:
        不超过上界时原样返回；否则返回前 `limit` 个字符加一行原文总长说明。
    """
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n\n（以上为摘录：原文共 {len(text)} 字符，此处保留前 {limit} 字符）"


def build_row(
    *,
    library: str,
    item_id: UUID,
    source_path: str,
    chunk: Chunk,
) -> ManualReviewItem:
    """把一个不可嵌入的块构造成复核件行。

    独立成纯函数而不是并进 `record_manual_reviews`：前置校验（块必须带原因）因此
    可以不起库地被测到——它是本表「可移交」的全部依据，值一条不起库的用例。

    Args:
        library: 库别（`LIBRARIES` 的取值）。
        item_id: 所属条目 id。
        source_path: 摄取来源路径（资料侧是文件、案例侧是包目录）。
        chunk: 需人工处理的块（`needs_manual_review` 为真）。

    Returns:
        待写入的 `ManualReviewItem`（调用方负责 `session.add`）。

    Raises:
        ManualReviewError: 块没有给出 `review_reason`。
    """
    reason = chunk.review_reason
    if not reason:
        raise ManualReviewError(f"块标记为需人工处理却没有原因（locator={chunk.locator!r}）：无法移交复核人")
    return ManualReviewItem(
        library=library,
        item_id=item_id,
        source_path=source_path,
        locator=chunk.locator,
        excerpt=build_excerpt(chunk.text),
        review_reason=reason,
    )


# quality-floor: ignore docstring-promise 异常由 build_row 抛出并原样传播，本函数只做逐块转发
async def record_manual_reviews(
    session: AsyncSession,
    *,
    library: str,
    item_id: UUID,
    source_path: str,
    chunks: list[Chunk],
) -> int:
    """把本次摄取的不可分块写成复核件，返回写入行数。

    重摄取时的幂等由「先删后插」承担，而不是靠唯一约束或 upsert：调用方在删该条目
    检索节点的同一处调用 `delete_manual_reviews`，因此本表里该条目名下永远只有
    本次分块结果对应的行。理由是复核件的身份是「该条目当前无法嵌入的块」这一集合，
    不是历史账本——内容改好之后旧行若留着，运维会去修一份已经不存在的问题。

    `chunks` 为空时本函数不写任何行（该条目本次没有不可分块）：调用方已删旧行，
    因此「上一次有、这一次没有」会自然表现为队列里没有该条目的行，而不是留下过期条目。

    Args:
        session: 调用方的事务会话（与条目表、节点表同事务，失败一起回滚）。
        library: 库别。
        item_id: 所属条目 id。
        source_path: 摄取来源路径。
        chunks: 需人工处理的块；空列表是合法输入。

    Returns:
        写入的行数（等于 `len(chunks)`）。

    Raises:
        ManualReviewError: 某个块没有给出 `review_reason`（透传 `build_row`）。
    """
    for chunk in chunks:
        session.add(build_row(library=library, item_id=item_id, source_path=source_path, chunk=chunk))
    await session.flush()
    return len(chunks)


async def delete_manual_reviews(session: AsyncSession, *, library: str, item_id: UUID) -> int:
    """删掉某条目的全部复核件，返回删除行数。

    与「删该条目的检索节点」成对调用：撤下与重摄取都要求该条目名下不留上一轮的投影，
    复核件与节点是同一批投影（一个是能嵌入的块，一个是不能嵌入的块）。

    删除条件用写入时的同一组键（库别 + 条目 id），不做「只按 item_id 删」的简化：
    两库的条目 id 各自生成，只按 id 删会在跨库同 id 时误删另一库的行。

    Args:
        session: 调用方的事务会话。
        library: 库别。
        item_id: 条目 id。

    Returns:
        删除的行数。
    """
    result = await session.execute(
        delete(ManualReviewItem).where(
            ManualReviewItem.library == library,
            ManualReviewItem.item_id == item_id,
        )
    )
    # `AsyncSession.execute` 的静态返回类型只声明 `Result`，而 DML 在运行期返回
    # `CursorResult`——`rowcount` 只在那上面（实测 sqlalchemy 2.0.54：DML 的
    # `type(result)` 为 `CursorResult`，`rowcount` 可读）。这里按实际类型收窄，
    # 而不是 `getattr(result, "rowcount", 0)` 兜底：兜底会把「上游换了返回类型」
    # 静默折成 0，于是删除行数虚报成「一行没删」，而撤下正是靠这个数判断清理是否完整。
    assert isinstance(result, CursorResult)  # 上游存根缺口，见上
    return result.rowcount or 0


__all__ = [
    "MANUAL_REVIEW_EXCERPT_CHARS",
    "ManualReviewError",
    "build_excerpt",
    "build_row",
    "delete_manual_reviews",
    "record_manual_reviews",
]
