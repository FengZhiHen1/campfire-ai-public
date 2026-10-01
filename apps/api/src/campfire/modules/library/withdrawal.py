"""撤下用例：打 `withdrawn` 标记并在同一事务内删除该条目的检索节点与人工处理队列行。

职责：实现 `RQ-KB-04` 的撤下——条目状态变更、节点删除与复核件清理在一个事务里完成。
边界：不提供服务端点（撤下经 CLI：`python -m campfire.cli withdraw <库别> <条目id>`，`RQ-KB-03`）；不做异步清理——那会让撤下与「即刻不可检索」之间出现窗口。
参考：docs/技术设计/technical-details/资料与案例检索.md 第 4 节；docs/技术设计/technical-details/RAG 策略.md 第 2 节；细节见 `withdraw_item` 的 docstring。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.modules.library.manual_review import delete_manual_reviews
from campfire.modules.library.models import (
    ITEM_MODELS,
    LIBRARIES,
    RetrievedNode,
)
from campfire.modules.library.retrieval import as_uuid

#: 撤下原因的合法取值域之外的自由文本，故不做枚举；只限制长度避免写入超长内容。
MAX_WITHDRAWN_REASON_CHARS = 500


class WithdrawalError(Exception):
    """撤下失败：条目不存在或库别非法。"""


@dataclass(frozen=True, slots=True)
class WithdrawalResult:
    """一次撤下的结果。

    `already_withdrawn` 的存在是为了让重复撤下成为可辨的幂等操作而不是错误：
    撤下是运维动作，重跑（或重放脚本）不该报错，但调用方需要知道「这次真的改了什么」。
    """

    item_id: str
    library: str
    already_withdrawn: bool
    #: 本次删除的检索节点数——撤下在向量路上生效的机制就是它消失。
    nodes_deleted: int
    #: 本次清理的人工处理队列行数。与 `nodes_deleted` 分开计数：后者的含义是检索节点，
    #: 混在一起会让「撤下生效」的证据含混。
    manual_reviews_deleted: int = 0


async def withdraw_item(
    session: AsyncSession,
    *,
    library: str,
    item_id: str,
    reason: str | None = None,
    now: datetime | None = None,
) -> WithdrawalResult:
    """撤下一个条目：打标记 + 删该条目全部检索节点与人工处理队列行（同一事务）。

    为什么两者必须同事务（RAG 策略第 2 节）：检索在查询时过滤 `withdrawn`
    （资料与案例检索第 4 节），因此「撤下即刻不可检索」与向量索引重建的滞后解耦。
    反过来说，若条目状态与节点删除分处两个事务，中间窗口里就会出现「节点还在、
    但查询已过滤掉条目」——聚合时该条目被丢弃，看起来是安全的；但字面路是按条目表
    命中的，节点删除才是让向量路彻底不再召回它的那一步。同事务把这两种机制
    的生效时点压到同一个提交点，不留窗口。

    撤下同时清掉该条目的人工处理队列行（`campfire_manual_review`）：那些行装的是
    超限且不可分块的正文摘录，属于该条目的投影；条目已撤下，「去修这份文件」这件事
    不再有落点，留着只会把撤下内容的摘录继续存在库里。清理与撤下同事务，
    否则会留下「条目已撤下、队列里还有它的行」的窗口。

    幂等：重复撤下返回 `already_withdrawn=True` 且不报错——撤下是可重跑的运维
    动作。重复执行仍会重新清理节点与复核件（`nodes_deleted` 与
    `manual_reviews_deleted` 反映本次实际删除数），因为「残留」本身就是需要被清掉的
    状态，跳过清理会让重跑失去意义。

    为什么用 `withdrawn IS TRUE` 之外的字段也不重置：重复撤下不覆盖首次的
    `withdrawn_at` 与原因——首次撤下的时间与理由是审计事实，重跑把它改成当前时间
    会让「这条什么时候被撤下的」失真。

    Args:
        library: 库别；非法取值抛 `WithdrawalError`（不静默当资料库处理）。
        item_id: 条目 UUID 字符串。
        reason: 撤下原因（`RQ-KB-04` 要求记录时间与原因）。
        now: 注入的当前时间，便于测试；缺省取 UTC 现在。

    Returns:
        `WithdrawalResult`。

    Raises:
        WithdrawalError: 库别非法或条目不存在。
        RetrievalError: `item_id` 不是合法 UUID。
    """
    if library not in LIBRARIES:
        raise WithdrawalError(f"非法库别：{library!r}，合法取值：{sorted(LIBRARIES)}")

    item_uuid = as_uuid(item_id)
    model = ITEM_MODELS[library]
    item = (await session.execute(select(model).where(model.id == item_uuid))).scalar_one_or_none()
    if item is None:
        raise WithdrawalError(f"条目不存在：{library}/{item_id}")

    already = bool(item.withdrawn)
    if not already:
        item.withdrawn = True
        item.withdrawn_at = now or datetime.now(timezone.utc)
        if reason:
            item.withdrawn_reason = reason[:MAX_WITHDRAWN_REASON_CHARS]

    # 节点删除按条目归属进行，两库共用同一节点表（node_id 前缀是条目 UUID）。
    # 用 node_id 前缀而不是 metadata_->>'item_id'：前者是写入时的既有约定
    # （`<item_id>:<chunk_index>`），且能走 `ix_data_campfire_node_node_id`。
    result = await session.execute(delete(RetrievedNode).where(RetrievedNode.node_id.like(f"{item_uuid}:%")))

    # 复核件是同一批投影的另一半（不能嵌入的块），随条目撤下一起清掉：条目已撤下，
    # 待处理的正文没有意义，留着反而把撤下内容的摘录继续留在库里。
    # 与条目状态变更同事务——分处两个提交点会留下「条目已撤下、队列里还有它的行」的窗口。
    manual_reviews_deleted = await delete_manual_reviews(session, library=library, item_id=item_uuid)

    return WithdrawalResult(
        item_id=item_id,
        library=library,
        already_withdrawn=already,
        nodes_deleted=result.rowcount or 0,
        manual_reviews_deleted=manual_reviews_deleted,
    )


__all__ = [
    "MAX_WITHDRAWN_REASON_CHARS",
    "WithdrawalError",
    "WithdrawalResult",
    "withdraw_item",
]
