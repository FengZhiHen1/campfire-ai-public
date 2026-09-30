"""记忆写入的 Worker 侧消费：把待处理记录变成图库里的 episode。

归属（见[写入路径](../../../../docs/技术设计/technical-details/写入路径.md)第 4、5、6 节与
[通用记忆](../../../../docs/技术设计/technical-details/通用记忆.md)第 3 节）：本模块是
`kind = memory_episode` 的消费者。投递与状态机在 `core/pending_write`；本模块只把
**自足载荷**变成图库写入，不回查业务用例、不依赖请求上下文（第 7 节的 Worker 边界）。

## 幂等：标记就是 `state`，它承载的是「避免重复抽取」

第 5 节要求「在我们自己的表里记'该 pending 已写入图库'的标记；重试前先查该标记」。
**该标记就是 `pending_write.state`**：只有 `done` 才算写入成功（第 2 节的不变量），
因此本模块的流程是

    领取（processing + 租约）→ 写图库 → 置 done

重试（含租约过期后的重新领取）会再走一遍。**为什么这样仍然安全**（2026-09-29 实测，
假 LLM 返回固定抽取结果）：同 uuid 重复 `add_episode` **不产生**重复 episode 节点、
重复实体或重复边，`edge.episodes` 也不会被追加两次——边的消解按事实内容命中既有边。

**残余风险与它为什么仍需要标记**：真实模型抽取**不确定**。重跑时若把同一件事抽成
措辞不同的事实，它会成为一条**新边**，而这一层无法拦住。因此标记的价值不是防重复
节点（`MERGE` 已保证），而是**避免重复调用抽取**——省一次模型成本与时间，并消除上述
不确定性。这也是为什么本模块**不**在领取前额外查一次状态：那会与 `take_for_processing`
的条件更新重复（第 4 节要求原子领取），而重复抽取的代价已由下面的流程上限收敛。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.core.auth.tombstone_repository import is_account_deleted
from campfire.core.pending_write import (
    KIND_MEMORY_EPISODE,
    PendingWrite,
    mark_done,
    take_for_processing,
)
from campfire.modules.memory.errors import MemoryDataError
from campfire.modules.memory.graph import MemoryGraph
from campfire.modules.memory.identity import PendingId, derive_episode_uuid, to_account_id
from campfire.modules.memory.store import write_episode

logger = logging.getLogger(__name__)

#: 载荷里必须存在的键（第 3 节：载荷**自足**，Worker 不回查业务用例）。
PAYLOAD_CONTENT = "content"
PAYLOAD_OCCURRED_AT = "occurred_at"

#: 来源里必须存在的键。来源会话标识是硬约束（`write_memory` 契约第 4 节：
#: 「没有时间的记忆无法回看」；来源同理——没有来源的记忆无法核对）。
SOURCE_SESSION_ID = "session_id"


@dataclass(frozen=True, slots=True)
class ConsumeResult:
    """一次消费的结果。

    ``written`` 为 False 表示**本次没有领取到记录**（已被他人领取、租约未到期、
    或已是终结态）——这不是错误，是并发下的正常结果，调用方跳过即可。

    ``discarded`` 为 True 表示**领取到了、但因账号已注销而不写入**（见
    :func:`consume_memory_episode` 的说明）。它与「没领到」是**两件不同的事**，
    必须能区分——否则运维看不出「有多少写入因为注销被丢弃」。
    """

    pending_id: str
    written: bool
    episode_uuid: str | None = None
    discarded: bool = False


# quality-floor: ignore docstring-promise 异常由 _write_record_to_graph 抛出并原样传播，函数体只做编排
async def consume_memory_episode(
    session: AsyncSession,
    graph: MemoryGraph,
    *,
    pending_id: str,
    lease_owner: str,
) -> ConsumeResult:
    """领取并消费一条 `memory_episode`（Worker 侧用例）。

    流程严格按第 4 节：**原子领取**（`take_for_processing`）→ **复查账号是否已注销**
    → 写图库 → 置 `done`。
    领取失败（返回 `None`）时**直接返回未写入**，不抛异常——「没领到」是并发的正常
    结果，把它当错误会让兜底扫描把每次竞争都记成失败。

    ## 为什么领取后必须复查「账号是否已注销」（2026-09-30 补，决策记录的不变量 2）

    账号注销时可能已有记录在排队、甚至已被本 Worker 领取（注销删的是**未领取**的记录，
    见[认证与账号](../../../../docs/技术设计/technical-details/认证与账号.md)第 8 节第 2 步）。
    若不在写入前复查，数据会被写回一个**已注销账号**的图——即
    **「删后复活」**，而墓碑正是为了阻止它而存在的
    （见[决策记录](../../../../docs/技术设计/decisions/账号注销与墓碑.md)）。

    **判据是墓碑**：这也是墓碑唯一的运行时用途——没有它，Worker 查不到账号时
    **无法区分「已注销」与「账号从不存」**。

    **发现已注销时怎么处置**：**删除该记录，不写图、不置 done**。
    理由：这条记录属于一个已不存在的账号，与第 8 节第 2 步「删除该账号的待处理记录」
    是同一个动作（它只是恰好已被领取）。用 `done` 会是谎话（**什么都没写**）；
    用 `dead` 会污染「重试耗尽」的告警流（这不是失败，是预期内的丢弃）。

    Args:
        session: 关系库会话（**调用方负责提交事务**）。
        graph: 记忆图库句柄。
        pending_id: 待处理记录标识（Taskiq 任务携带的载荷）。
        lease_owner: Worker 标识。

    Returns:
        `ConsumeResult`。``written=False`` 表示本次未领取到或已按注销丢弃
        （用 ``discarded`` 区分）。

    Raises:
        MemoryDataError: 载荷缺必填键，或记录的形状不合法。
            由调用方按第 6 节转成「可重试失败」或「转 dead」——**本函数不自作决定**，
            因为它无法知道调用方的重试预算。
        PendingWriteNotFoundError: 记录在领取后消失（极端并发），交由调用方处置。
    """
    record = await take_for_processing(session, pending_id=pending_id, lease_owner=lease_owner)
    if record is None:
        return ConsumeResult(pending_id=str(pending_id), written=False)

    # --- 复查账号是否已注销（写入之前，不可省）---
    if await is_account_deleted(session, account_id=record.account_id):
        logger.info(
            "账号已注销，丢弃待处理记录（不写图库）：pending_id=%s 账号=%s",
            pending_id,
            record.account_id,
        )
        await session.execute(delete(PendingWrite).where(PendingWrite.id == record.id))
        return ConsumeResult(pending_id=str(pending_id), written=False, discarded=True)

    episode_uuid = await _write_record_to_graph(graph, record)

    # 置 done 与「清理租约」同一次更新（`core/pending_write` 已实现）。
    # **带租约栅栏**（CORE-03）：抽取可能超过租约时长，期间记录会被另一个 Worker
    # 重领；若这里不带 `lease_owner`，先领取者的迟到 `mark_done` 会抢先成功，
    # 把真正写入者的终结挤成失败（实测复现，2026-09-29 评审 C-3）。
    # 栅栏不匹配说明本次写入已不再被承认——显式失败，不假装成功。
    await mark_done(session, pending_id=pending_id, lease_owner=lease_owner)
    return ConsumeResult(pending_id=str(pending_id), written=True, episode_uuid=episode_uuid)


async def _write_record_to_graph(graph: MemoryGraph, record: PendingWrite) -> str:
    """把一条待处理记录写进图库，返回派生的 episode uuid。

    载荷缺失时抛 `MemoryDataError`——**不猜、不用默认值**。用默认值（例如把缺
    `occurred_at` 的当成"现在发生"）会污染时间线，而时间线正是记忆回看的唯一载体。

    Raises:
        MemoryDataError: `kind` 不是 `memory_episode`，或载荷/来源缺必填键。
    """
    if record.kind != KIND_MEMORY_EPISODE:
        raise MemoryDataError(
            f"本消费者只处理 {KIND_MEMORY_EPISODE}，收到 {record.kind!r}",
            operation="consume_memory_episode",
            detail=f"kind={record.kind!r}",
        )

    payload = record.payload or {}
    content = payload.get(PAYLOAD_CONTENT)
    if not content or not isinstance(content, str):
        raise MemoryDataError(
            "载荷缺 content（记忆的正文是回看的唯一载体）",
            operation="consume_memory_episode",
            detail=f"pending_id={record.id!r} payload_keys={sorted(payload)}",
        )

    raw_occurred_at = payload.get(PAYLOAD_OCCURRED_AT)
    if not raw_occurred_at or not isinstance(raw_occurred_at, str):
        raise MemoryDataError(
            "载荷缺 occurred_at（没有时间的记忆无法回看）",
            operation="consume_memory_episode",
            detail=f"pending_id={record.id!r} payload_keys={sorted(payload)}",
        )
    occurred_at = _parse_occurred_at(raw_occurred_at, record)

    source = record.source or {}
    session_id = source.get(SOURCE_SESSION_ID)
    if not session_id or not isinstance(session_id, str):
        raise MemoryDataError(
            "来源缺 session_id（没有来源的记忆无法核对）",
            operation="consume_memory_episode",
            detail=f"pending_id={record.id!r} source_keys={sorted(source)}",
        )

    # 分区键取自记录（由登录态在请求事务内写入），不由载荷决定。
    account_id = to_account_id(record.account_id)
    # 确定性 episode 标识由 pending_id 派生（第 5 节）：这是幂等的依据，
    # 而不是 `name`（图库的身份是 uuid）。
    episode_uuid = derive_episode_uuid(PendingId(str(record.id)))

    await write_episode(
        graph,
        account_id,
        episode_uuid,
        content=content,
        occurred_at=occurred_at,
        source_description=_source_description(record, source, session_id),
    )
    return episode_uuid


def _source_description(record: PendingWrite, source: dict, session_id: str) -> str:
    """把来源拼成 `source_description`。

    为什么走这个字段：`episode_metadata` **不落库**（通用记忆第 3 节实测），因此
    「来源会话标识」只能由 `source_description` 承载。

    拼法保留可核对性（会话 + 消息定位），但不引入固定 schema：`source` 的形状随
    `kind` 不同（第 3 节只要求它是「来源信息」）。
    """
    parts = [f"session={session_id}"]
    message_seq = source.get("message_seq")
    if message_seq is not None:
        parts.append(f"message={message_seq}")
    tool = source.get("tool")
    if tool:
        parts.append(f"tool={tool}")
    parts.append(f"pending={record.id}")
    return " ".join(parts)


def _parse_occurred_at(raw: str, record: PendingWrite) -> datetime:
    """解析载荷里的发生时间。

    只接受 ISO 8601（含时区）。**不接受朴素时间**：记忆的时间线要跨账号与跨机器看，
    没有时区的时间会被解释成不同瞬间，而时间顺序正是回看的组织方式。

    Raises:
        MemoryDataError: 无法解析，或缺少时区。
    """
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise MemoryDataError(
            "occurred_at 不是合法的 ISO 8601 时间",
            operation="consume_memory_episode",
            detail=f"pending_id={record.id!r} occurred_at={raw!r}",
        ) from exc
    if parsed.tzinfo is None:
        raise MemoryDataError(
            "occurred_at 缺少时区（朴素时间会被解释成不同瞬间，污染时间线顺序）",
            operation="consume_memory_episode",
            detail=f"pending_id={record.id!r} occurred_at={raw!r}",
        )
    return parsed


__all__ = [
    "PAYLOAD_CONTENT",
    "PAYLOAD_OCCURRED_AT",
    "SOURCE_SESSION_ID",
    "ConsumeResult",
    "consume_memory_episode",
]
