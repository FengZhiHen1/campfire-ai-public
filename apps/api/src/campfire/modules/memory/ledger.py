"""读取侧的删除过滤：把账本里的 `episode_key` 取出来供图库侧排除，以及删除的写入。

归属（见 docs/技术设计/technical-details/通用记忆.md 第 7 节）：**账本过滤是语义
删除的唯一生效点**，图库物理删除不是。两条读路径都必须先经这里。

**为什么是「取 key 再传给图库」而不是「读回来再过滤」**：先在图库查询里排除
（`WHERE NOT e.uuid IN $deleted`）可以让过滤与分页/上限在同一层生效。若读回来再
过滤，`limit` 会先把已删除的算进去——「取最近 20 条」可能实际只剩 3 条可见，
这不是等价变换。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.modules.memory.errors import MemoryDataError
from campfire.modules.memory.identity import to_episode_key
from campfire.modules.memory.models import (
    DELETION_REASON_USER_REQUEST,
    DELETION_REASONS,
    MemoryDeletionLedger,
)

#: 单次查询取回的已删 key 上界（CORE-11：读路径在应急首字时延上，不能无界拉取）。
#: 10k 远超一期单账号记忆量（参数表 `emergency_memory_limit` 为 20 条量级）。
#:
#: **触顶时的行为是「显式失败」而不是「返回前 N 条」**（2026-09-29 修正）：
#: 截断意味着「部分已删记忆仍会被返回」——即删除静默失效，直接违反 `RQ-MEM-03`。
#: 宁可明确报错并提示需要物理清理（`docs/技术设计/technical-details/通用记忆.md`
#: 第 7 节已写明该规模下物理清理必须启用），也不返回用户已删除的内容。
DELETED_KEYS_LIMIT: Final[int] = 10_000


class DeletionOutcome(StrEnum):
    """记录删除的结果。**区分「本次真的记了」与「之前已记过」**。

    删除是幂等的（同一条重复删不产生第二行），但调用方需要知道是「刚刚删除成功」
    还是「此前已删除」——两者的用户可见文案与审计含义不同。静默返回同一种结果会
    让「删除根本没生效」与「删除早已生效」看起来一样。
    """

    #: 本次新记入账本：删除从此刻开始对两条读路径生效。
    RECORDED = "recorded"
    #: 账本中已有同一 `episode_key` 的记录：幂等命中，未重复写入。
    ALREADY_RECORDED = "already_recorded"


@dataclass(frozen=True, slots=True)
class DeletionRecord:
    """一次删除记录请求的结果。

    ``outcome`` 说明本次是新记还是幂等命中；``owner_account_id`` 在幂等命中时
    给出**原记录的归属账号**，供调用方判断是否为异常（见 `record_deletion`）。
    """

    episode_key: str
    outcome: DeletionOutcome
    #: 该记录在账本中的**实际**原因。
    #:
    #: **幂等命中时是原记录的原因，不是本次请求传的原因**（2026-09-29 明确）：
    #: 一条记忆先按 `correction` 删除、之后又收到一次 `user_request` 删除请求时，
    #: 账本里仍是 `correction`。如实回报原原因，避免审计读到「本次请求的原因」
    #: 这种与账本不符的信息。
    reason: str
    #: 已存在那条记录所属的账号（仅 `ALREADY_RECORDED` 时有意义）。
    owner_account_id: str | None = None


async def deleted_episode_keys(session: AsyncSession, account_id: object) -> list[str]:
    """取该账号已删除的 episode key 列表（按删除时间升序，稳定）。

    Args:
        session: 关系库会话。
        account_id: 账号标识（与 `group_id` 同源）。

    Returns:
        已删 `episode_key`；无删除记录时为空列表（**正常状态，不是错误**）。

    Raises:
        MemoryDataError: 该账号的删除记录**超过** ``DELETED_KEYS_LIMIT``。此时无法
            完整排除已删内容，返回部分结果等于让删除静默失效（见常量说明）；
            需先按账号做物理清理。
    """
    # 多取一条用于检测「还有更多」——只看 == LIMIT 无法区分「恰好这么多」与「被截断」。
    result = await session.execute(
        select(MemoryDeletionLedger.episode_key)
        .where(MemoryDeletionLedger.account_id == account_id)
        .order_by(MemoryDeletionLedger.deleted_at)
        .limit(DELETED_KEYS_LIMIT + 1)
    )
    keys = list(result.scalars())
    if len(keys) > DELETED_KEYS_LIMIT:
        raise MemoryDataError(
            f"删除账本记录超过 {DELETED_KEYS_LIMIT} 条，无法完整排除已删内容",
            operation="deleted_episode_keys",
            detail=f"account_id={account_id!r} 触顶：需先按账号做图库物理清理",
        )
    return keys


async def record_deletion(
    session: AsyncSession,
    *,
    account_id: str,
    episode_key: str,
    reason: str = DELETION_REASON_USER_REQUEST,
    deleted_by: str | None = None,
    derived_uuids: list[str] | None = None,
) -> DeletionRecord:
    """把一条记忆记入删除账本（幂等）。

    **幂等落在存储约束上**，不是「先查后写」：`episode_key` 有唯一约束，这里用
    `INSERT ... ON CONFLICT DO NOTHING`——并发重复删除也只有一行。先查后写在并发下
    会双写（两个请求同时查不到、同时插入），那不是幂等。

    Args:
        session: 关系库会话（**调用方负责提交事务**）。
        account_id: 归属账号（分区键同源）。
        episode_key: 确定性 episode uuid（`identity.derive_episode_uuid` 的产物）。
        reason: 删除原因，取值见 `DELETION_REASONS`。
        deleted_by: 发起删除的账号；一期与 `account_id` 同值。
        derived_uuids: 删除时已知的派生物清单（尽力记录，**不作过滤依据**）。

    Returns:
        `DeletionRecord`：本次新记还是幂等命中。

    Raises:
        MemoryDataError: `reason` 不在词表内；或 `episode_key` 为空、非字符串、
            超长、非合法 UUID（形状校验见 `identity.to_episode_key`）。
        MemoryDataError: `episode_key` 已被**其它账号**记录删除。这说明该 uuid 被
            两个账号共用（`episode_key` 由 uuid4 派生，正常不可能发生）；此时
            静默幂等会让本账号的删除看起来成功、实际不生效，故显式失败。
    """
    if reason not in DELETION_REASONS:
        raise MemoryDataError(
            f"删除原因不在词表内：{reason!r}",
            operation="record_deletion",
            detail=f"合法取值={sorted(DELETION_REASONS)}",
        )

    # 归一为规范 UUID 文本（大小写/花括号形式不一致会让同一条记忆在写入与读取两侧
    # 看起来是两个 key）。校验在此处做而不是信任调用方——账本里的脏 key 不会报错，
    # 只会让某条记忆永远删不掉、或误删不到（静默失效）。
    # 空值与超长也在这里被拒（`to_episode_key` 的边界校验）。
    episode_key = to_episode_key(episode_key)

    statement = (
        pg_insert(MemoryDeletionLedger)
        .values(
            account_id=account_id,
            episode_key=episode_key,
            deleted_by=deleted_by if deleted_by is not None else account_id,
            reason=reason,
            derived_uuids=derived_uuids or [],
        )
        # 幂等的落点：唯一约束冲突则什么都不做（不更新、不报错）。
        .on_conflict_do_nothing(index_elements=[MemoryDeletionLedger.episode_key])
        .returning(MemoryDeletionLedger.episode_key)
    )
    inserted = (await session.execute(statement)).scalar_one_or_none()

    if inserted is not None:
        return DeletionRecord(episode_key=episode_key, outcome=DeletionOutcome.RECORDED, reason=reason)

    # 未插入 = 已存在。查它的归属账号**与原因**：
    #   - 归属账号用于区分「同账号幂等」与「跨账号异常」；
    #   - 原因是**账本里的原原因**，不是本次请求传的原因（见 DeletionRecord 说明），
    #     调用方的审计与文案必须按账本事实回报。
    existing = (
        await session.execute(
            select(MemoryDeletionLedger.account_id, MemoryDeletionLedger.reason).where(
                MemoryDeletionLedger.episode_key == episode_key
            )
        )
    ).one_or_none()

    if existing is None:
        # 理论上不可达（未插入意味着冲突行存在）。显式失败而不是编造一个原因。
        raise MemoryDataError(
            "删除记录既未插入也查不到，账本状态不一致",
            operation="record_deletion",
            detail=f"episode_key={episode_key!r}",
        )

    existing_owner, existing_reason = existing

    if existing_owner != account_id:
        raise MemoryDataError(
            "该 episode_key 已被其它账号记录删除，本账号的删除不会生效",
            operation="record_deletion",
            detail=f"owner={existing_owner!r} requester={account_id!r}（uuid 被跨账号共用）",
        )

    return DeletionRecord(
        episode_key=episode_key,
        outcome=DeletionOutcome.ALREADY_RECORDED,
        reason=existing_reason,
        owner_account_id=existing_owner,
    )


__all__ = [
    "DELETED_KEYS_LIMIT",
    "DeletionOutcome",
    "DeletionRecord",
    "deleted_episode_keys",
    "record_deletion",
]
