"""待处理记录的状态推进与租约领取。

归属见[写入路径](../../../../docs/技术设计/technical-details/写入路径.md)第 4、5、6 节。
本模块是**状态机的唯一实现**：其它地方（Worker、业务模块）只调用这里，不自己写
`UPDATE ... SET state=...`——否则状态判据会散落成多份，也就没有「唯一所有者」了。

## 为什么领取必须走 UPDATE ... RETURNING 而不是「先查后改」

第 4 节明确「不使用先查后改的无锁流程」。两个 Worker 同时查同一条记录、
都看到 `pending`、都去改，会**双双认为领到了**，于是同一条记忆被抽取两次。
因此这里的领取是**单条 SQL 的条件更新**：

    UPDATE ... SET state='processing', lease_owner=... WHERE id=... AND <可领取条件>
    RETURNING ...

数据库的行锁保证只有一个事务能把它从「可领取」改成「processing」；另一个更新的
`WHERE` 不再匹配，`RETURNING` 为空 → 调用方明确知道「没领到」，而不是猜。

## 租约过期的重新领取

`lease_expires_at` 过期即视为可领取（第 6 节：Worker 崩溃不该让记录永久卡住）。
**过期不等于失败**：`attempts` 只在真正失败时 +1（见 `mark_retryable_failure`），
崩溃重启不该消耗重试预算——否则反复崩溃会把一条本来健康的记录耗成 `dead`。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.core.pending_write.models import (
    KINDS,
    ORIGINS,
    STATE_DEAD,
    STATE_DONE,
    STATE_FAILED,
    STATE_PENDING,
    STATE_PROCESSING,
    PendingWrite,
)

#: 重试上限（第 10 节参数表：**5 次**）。达到即转 `dead` 并告警，不静默丢弃。
MAX_ATTEMPTS = 5

#: 租约时长（第 10 节：**5 分钟**）。取值理由：**短于兜底扫描周期**（也是 5 分钟），
#: 好让 Worker 崩溃能在一次扫描内被发现。
LEASE_SECONDS = 300

#: 退避曲线（第 10 节：1 → 2 → 4 → 8 → 16 分钟）。按 `attempts` 取第 n 项，
#: 超出长度时取最后一项（上限行为显式，不外推成无限增长）。
_BACKOFF_SECONDS = (60, 120, 240, 480, 960)

#: `last_error` 的长度上界，与列宽一致。**截断而不是报错**：错误摘要是诊断信息，
#: 因它写入失败会让「失败记录」本身丢失，反而更难排查。
MAX_LAST_ERROR_LENGTH = 512


class PendingWriteError(Exception):
    """待处理记录的统一异常基类。

    **不继承 `core/db` 的异常**：本模块是状态机的所有者，调用方（Worker、业务模块）
    需要能一句 ``except PendingWriteError`` 收口，而不必知道底层是 SQLAlchemy。
    """


class PendingWriteNotFoundError(PendingWriteError):
    """记录不存在，或当前不处于调用方期望的状态。

    两种情况合并为一个类型是**有意的**：调用方对它们的处置相同（不能推进）。
    若需要区分，按 id 再查一次即可——本模块不为此增加一条「先查后改」的路径。
    """

    def __init__(self, pending_id: uuid.UUID | str, reason: str) -> None:
        """记录待处理记录标识与不能推进的原因。"""
        self.pending_id = pending_id
        self.reason = reason
        super().__init__(f"待处理记录 {pending_id!r} 无法推进：{reason}")


class InsufficientPayloadError(PendingWriteError):
    """入参不满足记录形状的约束（第 3 节）。

    单独成型是为了让调用方区分「调用方给错了」（不该重试）与「基础设施故障」
    （可重试）——与 `modules/memory` 的 `MemoryDataError` 同一种分层思路。
    """

    def __init__(self, detail: str) -> None:
        """记录不合格的原因。"""
        self.detail = detail
        super().__init__(f"待处理记录的形状不合法：{detail}")


def _utc_now() -> datetime:
    """当前 UTC 时间。集中一处，便于测试替换时只有一个改动点。"""
    return datetime.now(timezone.utc)


def _backoff_for(attempts: int) -> timedelta:
    """按已尝试次数取退避时长（第 10 节的曲线）。

    ``attempts`` 从 0 开始：第 0 次失败后等 1 分钟，第 1 次后 2 分钟，依此类推。
    超出曲线长度时取最后一项——**显式封顶**而不是无限外推。
    """
    index = min(max(attempts, 0), len(_BACKOFF_SECONDS) - 1)
    return timedelta(seconds=_BACKOFF_SECONDS[index])


async def enqueue(
    session: AsyncSession,
    *,
    kind: str,
    account_id: str,
    origin: str,
    payload: dict,
    source: dict,
    support_object_id: str | None = None,
    pending_id: uuid.UUID | None = None,
) -> PendingWrite:
    """写入一条待处理记录（**与业务数据同一事务**，第 3 节）。

    Args:
        session: 关系库会话（**调用方负责提交事务**——记录必须与业务数据同事务，
            事务回滚则记录不存在）。
        kind: 记录种类，取值见 `KINDS`。
        account_id: 发起者；记忆的分区键即此值。
        origin: 生成方式，取值见 `ORIGINS`。
        payload: 自足的最小载荷（Worker 只凭它就能完成写入）。
        source: 来源信息（会话 id、消息 seq、工具名、时间）。
        support_object_id: **仅 `profile_item` 需要**；`memory_episode` 必须传 `None`。
        pending_id: 可选的确定性标识（重放/测试用）。不给则生成新的 uuid4。

    Returns:
        已加入会话的记录（**尚未提交**）。

    Raises:
        InsufficientPayloadError: 词表外的取值，或归属字段与 `kind` 不匹配。
            这些判据在存储层也有 CHECK 约束；这里**提前**拒绝是为了给出可读的错误，
            而不是让调用方读到数据库的约束名。
    """
    if kind not in KINDS:
        raise InsufficientPayloadError(f"kind 不在词表内：{kind!r}（合法取值={sorted(KINDS)}）")
    if origin not in ORIGINS:
        raise InsufficientPayloadError(f"origin 不在词表内：{origin!r}（合法取值={sorted(ORIGINS)}）")
    if not account_id:
        raise InsufficientPayloadError("account_id 为空")
    if not isinstance(payload, dict):
        raise InsufficientPayloadError(f"payload 必须是对象，收到 {type(payload).__name__}")
    if not isinstance(source, dict):
        raise InsufficientPayloadError(f"source 必须是对象，收到 {type(source).__name__}")

    # 归属字段按 kind 的判据（第 3 节）。与存储层 CHECK 同一条规则，此处提前报错。
    requires_object = kind == "profile_item"
    if requires_object and not support_object_id:
        raise InsufficientPayloadError(f"{kind} 必须有 support_object_id")
    if not requires_object and support_object_id is not None:
        raise InsufficientPayloadError(f"{kind} 不得带 support_object_id（记忆属账号，不随对象分区）")

    record = PendingWrite(
        id=pending_id if pending_id is not None else uuid.uuid4(),
        kind=kind,
        account_id=account_id,
        support_object_id=support_object_id,
        payload=payload,
        origin=origin,
        source=source,
        state=STATE_PENDING,
        attempts=0,
    )
    session.add(record)
    return record


async def take_for_processing(
    session: AsyncSession,
    *,
    pending_id: uuid.UUID | str,
    lease_owner: str,
    now: datetime | None = None,
) -> PendingWrite | None:
    """以租约方式领取一条记录（第 4 节）。

    **可领取**的条件（三选一，都是「未终结」）：
      - `pending`：从未领过，或上次失败后退避已到期；
      - `processing` 且**租约已过期**：Worker 崩溃，可被重新领取；
      - `failed`：可重试失败，退避到期后重新领取。

    Args:
        session: 关系库会话。
        pending_id: 待领取记录标识。
        lease_owner: 领取者标识（Worker 实例名），写入 `lease_owner` 供排查。
        now: 参照时间，默认当前 UTC——**显式可传**以便测试租约过期的确定性。

    Returns:
        领取到的记录；**未领到返回 `None`**（不是异常）——「没领到」是并发的正常结果，
        不是错误。调用方据此跳过即可。

    Note:
        用「条件更新 + RETURNING」在**一条 SQL** 内完成判定与占用（见模块说明）：
        改成先查后改会让两个 Worker 同时认为自己领到了同一条记录。
    """
    reference = now if now is not None else _utc_now()
    # 可领取的三种情形，与 `docstring` 一一对应：
    #   1. `pending`（从未领过，或失败后退避已到期）；
    #   2. `processing` 但租约已过期（Worker 崩溃）；
    #   3. `failed`（第 3 节的状态词表里有它；本模块的 `mark_retryable_failure` 按第 6 节
    #      把可重试失败写回 `pending`，因此正常流程不会留下 `failed`——但历史数据或
    #      将来「不可重试也非 dead」的处置可能留下它，故仍视为可领取）。
    claimable = or_(
        PendingWrite.state == STATE_PENDING,
        PendingWrite.state == STATE_FAILED,
        (PendingWrite.state == STATE_PROCESSING) & (PendingWrite.lease_expires_at < reference),
    )
    statement = (
        update(PendingWrite)
        .where(
            PendingWrite.id == pending_id,
            claimable,
            or_(PendingWrite.next_attempt_at.is_(None), PendingWrite.next_attempt_at <= reference),
        )
        .values(
            state=STATE_PROCESSING,
            lease_owner=lease_owner,
            lease_expires_at=reference + timedelta(seconds=LEASE_SECONDS),
            updated_at=reference,
        )
        .returning(PendingWrite)
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def mark_done(
    session: AsyncSession,
    *,
    pending_id: uuid.UUID | str,
    now: datetime | None = None,
) -> PendingWrite:
    """标记写入成功（第 4 节）：置 `done`、记 `finished_at`，**并清理租约**。

    同一事务内清理租约是第 4 节的要求：留着租约会让排查时看不出「这条已经不归谁管了」。

    Raises:
        PendingWriteNotFoundError: 记录不存在，或**已处于终结状态**。
            重复标记不是错误数据，但**必须让调用方知道本次没有推进任何东西**——
            静默返回成功会让「刚才那个 done 是谁标的」无从查起。
    """
    reference = now if now is not None else _utc_now()
    statement = (
        update(PendingWrite)
        .where(
            PendingWrite.id == pending_id,
            PendingWrite.state.notin_((STATE_DONE, STATE_DEAD)),
        )
        .values(
            state=STATE_DONE,
            finished_at=reference,
            lease_owner=None,
            lease_expires_at=None,
            last_error=None,
            updated_at=reference,
        )
        .returning(PendingWrite)
    )
    record = (await session.execute(statement)).scalar_one_or_none()
    if record is None:
        raise PendingWriteNotFoundError(pending_id, "不存在，或已是 done/dead（不可重复终结）")
    return record


async def mark_retryable_failure(
    session: AsyncSession,
    *,
    pending_id: uuid.UUID | str,
    error: str,
    now: datetime | None = None,
) -> PendingWrite:
    """可重试失败（第 6 节）：`attempts + 1`、按退避后移 `next_attempt_at`、回 `pending`。

    **超过 `MAX_ATTEMPTS` 时转 `dead`**（第 6 节：不得静默丢弃）。

    Args:
        session: 关系库会话。
        pending_id: 待处理记录标识。
        error: 失败摘要。**只记摘要，不复述连接串或凭据**（AGENTS.md 安全条款）；
            超长时截断（见 `MAX_LAST_ERROR_LENGTH`）。
        now: 参照时间。

    Returns:
        更新后的记录（`state` 为 `pending` 或 `dead`）。

    Raises:
        PendingWriteNotFoundError: 记录不存在或已终结。
    """
    reference = now if now is not None else _utc_now()
    # 先原子地自增并取回新值：并发两次失败各 +1，不会互相覆盖（用 SQL 表达式而不是
    # 读-改-写）。
    bumped = (
        await session.execute(
            update(PendingWrite)
            .where(
                PendingWrite.id == pending_id,
                PendingWrite.state.notin_((STATE_DONE, STATE_DEAD)),
            )
            .values(attempts=PendingWrite.attempts + 1, updated_at=reference)
            .returning(PendingWrite.attempts)
        )
    ).scalar_one_or_none()

    if bumped is None:
        raise PendingWriteNotFoundError(pending_id, "不存在，或已终结（不可再记失败）")

    summary = error[:MAX_LAST_ERROR_LENGTH]
    if bumped >= MAX_ATTEMPTS:
        return await mark_dead(session, pending_id=pending_id, error=summary, now=reference)

    statement = (
        update(PendingWrite)
        .where(PendingWrite.id == pending_id)
        .values(
            state=STATE_PENDING,
            next_attempt_at=reference + _backoff_for(bumped - 1),
            lease_owner=None,
            lease_expires_at=None,
            last_error=summary,
            updated_at=reference,
        )
        .returning(PendingWrite)
    )
    record = (await session.execute(statement)).scalar_one_or_none()
    if record is None:
        raise PendingWriteNotFoundError(pending_id, "记录在更新过程中消失")
    return record


async def mark_dead(
    session: AsyncSession,
    *,
    pending_id: uuid.UUID | str,
    error: str,
    now: datetime | None = None,
) -> PendingWrite:
    """转 `dead`（第 6 节：**超过重试上限并告警**，不得静默丢弃）。

    本函数只负责状态；**告警由调用方发出**——本模块不引入日志/告警依赖，
    避免 `core/pending_write` 依赖可观测设施（它是状态机，不是运维组件）。

    Raises:
        PendingWriteNotFoundError: 记录不存在，或已处于终结状态。
    """
    reference = now if now is not None else _utc_now()
    statement = (
        update(PendingWrite)
        .where(PendingWrite.id == pending_id, PendingWrite.state.notin_((STATE_DONE, STATE_DEAD)))
        .values(
            state=STATE_DEAD,
            finished_at=reference,
            lease_owner=None,
            lease_expires_at=None,
            last_error=error[:MAX_LAST_ERROR_LENGTH],
            updated_at=reference,
        )
        .returning(PendingWrite)
    )
    record = (await session.execute(statement)).scalar_one_or_none()
    if record is None:
        raise PendingWriteNotFoundError(pending_id, "不存在，或已是 done/dead（不可重复终结）")
    return record


async def reclaim_expired_leases(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> list[uuid.UUID]:
    """把租约过期的记录放回 `pending`，返回被回收的 id 列表（第 6 节）。

    **不增加 `attempts`**：Worker 崩溃不是「尝试失败」，消耗重试预算会让反复崩溃的
    环境把健康记录耗成 `dead`。

    Args:
        session: 关系库会话。
        now: 参照时间。
        limit: 单次回收条数上界。**有界**（CORE-11）：扫描周期固定，无界回收会让
            一次扫描在积压时耗时不可控。

    Returns:
        被回收的记录 id（按 id 升序，稳定）。空列表表示没有需要回收的记录。
    """
    reference = now if now is not None else _utc_now()
    # 先选出一批 id（有界），再按 id 更新——避免 `UPDATE ... LIMIT` 的方言差异。
    candidates = (
        await session.execute(
            select(PendingWrite.id)
            .where(
                PendingWrite.state == STATE_PROCESSING,
                PendingWrite.lease_expires_at.is_not(None),
                PendingWrite.lease_expires_at < reference,
            )
            .order_by(PendingWrite.id)
            .limit(max(1, limit))
        )
    ).scalars()
    ids = list(candidates)
    if not ids:
        return []

    await session.execute(
        update(PendingWrite)
        .where(PendingWrite.id.in_(ids))
        .values(
            state=STATE_PENDING,
            lease_owner=None,
            lease_expires_at=None,
            # 立刻可领（不设退避）：崩溃恢复应当尽快重试。
            next_attempt_at=None,
            updated_at=reference,
        )
    )
    return ids


__all__ = [
    "LEASE_SECONDS",
    "MAX_ATTEMPTS",
    "MAX_LAST_ERROR_LENGTH",
    "InsufficientPayloadError",
    "PendingWriteError",
    "PendingWriteNotFoundError",
    "enqueue",
    "mark_dead",
    "mark_done",
    "mark_retryable_failure",
    "reclaim_expired_leases",
    "take_for_processing",
]
