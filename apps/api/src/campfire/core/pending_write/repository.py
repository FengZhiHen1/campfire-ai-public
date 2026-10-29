"""待处理记录的状态推进与租约领取。

职责：推进一条待处理记录的状态（领取、成功、可重试失败、终结、回收）。
边界：状态判据只此一处；投递与业务消费不在本模块。
参考：归属见 docs/技术设计/technical-details/写入路径.md 第 4、5、6 节。
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.core.pending_write.models import (
    KINDS,
    MAX_ACCOUNT_ID_LENGTH,
    ORIGINS,
    STATE_DEAD,
    STATE_DONE,
    STATE_FAILED,
    STATE_PENDING,
    STATE_PROCESSING,
    PendingWrite,
)

#: 重试上限（第 10 节参数表：5 次）。达到即转 `dead` 并告警，不静默丢弃。
MAX_ATTEMPTS = 5

#: 租约时长（第 10 节：5 分钟）。取值理由：与兜底扫描周期相等（都是 300 秒），
#: 好在回收承重时一次扫描内就能发现崩溃——`sweep_once` 每轮先回收过期租约、再重投
#: （见 `worker.sweep_once` 的顺序说明）：上一轮扫描之后才崩溃的 Worker，其租约最迟
#: 在下一轮扫描执行到回收那一步时已过期（租约起点早于该轮扫描至少一个周期的情形
#: 恒成立；同周期内刚领的租约属「在途」，本就不该被回收）。
#: 当前接线下崩溃是另一个机制接住的：事务回滚把行留成 `pending`，由
#: `find_undelivered` 在下一轮扫描重投——同样一次扫描内被发现，且不依赖本常量
#: （实测与理由见 `reclaim_expired_leases`）。
#: 不能假定它更短：数值上等于扫描周期（`SWEEP_INTERVAL_SECONDS` 同为 300）。
#: 写成「相等 + 先回收后重投」才与代码的实际时序一致。
LEASE_SECONDS = 300

#: 退避曲线（第 10 节：1 → 2 → 4 → 8 → 16 分钟）。
#:
#: 末档 960 秒（16 分钟）不可达。
#: 调用点是 `_backoff_for(bumped - 1)`，而第 5 次失败在应用退避之前即转 `dead`
#: （见 `mark_retryable_failure`），故实际用到的是第 0..3 项
#: = `[60, 120, 240, 480]`，曲线是 1→2→4→8、合计 15 分钟。
#: 第 10 节的取值理由写着「约半小时内自然恢复」，实际是 15 分钟。
#: 保留 5 项并加说明（而不是截成 4 项）：`mark_retryable_failure` 的下标取自
#: `attempts - 1`，截短会让「超长时取最后一项」这条兜底语义在多一点重试时越界；
#: 且第 10 节的参数表以 5 档成文，改档位属设计变更（已登记 TODO `TECH-22`）。
_BACKOFF_SECONDS = (60, 120, 240, 480, 960)

#: 单次租约回收的条数上界（CORE-11）。与 `store.TIMELINE_MAX_LIMIT` 同一纪律：
#: 调用方给多大都收敛到该上界，避免一次兜底扫描在积压时耗时不可控。
RECLAIM_MAX_LIMIT = 1000

#: 单次兜底扫描返回的条数上界（第 4.1 节）。与 `RECLAIM_MAX_LIMIT` 同一纪律：
#: 扫描是周期任务，一次处理不完的记录留给下一周期，不得让单次扫描无界。
SWEEP_MAX_LIMIT = 1000

#: `last_error` 的长度上界，与列宽一致。截断而不是报错：错误摘要是诊断信息，
#: 因它写入失败会让「失败记录」本身丢失，反而更难排查。
MAX_LAST_ERROR_LENGTH = 512


class PendingWriteError(Exception):
    """待处理记录的统一异常基类。

    不继承 `core/db` 的异常：本模块是状态机的所有者，调用方（Worker、业务模块）
    需要能一句 `except PendingWriteError` 收口，而不必知道底层是 SQLAlchemy。

    本模块是状态机的唯一实现：其它地方（Worker、业务模块）只调用这里，不自己写
    `UPDATE ... SET state=...`——否则状态判据会散落成多份，也就没有「唯一所有者」了。
    """


class PendingWriteNotFoundError(PendingWriteError):
    """记录不存在，或当前不处于调用方期望的状态。

    两种情况合并为一个类型是有意的：调用方对它们的处置相同（不能推进）。
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

    `attempts` 从 0 开始：第 0 次失败后等 1 分钟，第 1 次后 2 分钟，依此类推。
    超出曲线长度时取最后一项——显式封顶而不是无限外推。
    """
    index = min(max(attempts, 0), len(_BACKOFF_SECONDS) - 1)
    return timedelta(seconds=_BACKOFF_SECONDS[index])


def _lease_fence(lease_owner: str, reference: datetime):  # noqa: ANN202 —— 返回 SQLAlchemy 布尔表达式
    """失败/终结的迟到守卫：只在「没有别人持有未过期租约」时允许推进。

    判据是 `lease_owner IS NULL`、或属主是自己、或租约已过期——**不是**「必须
    `processing` 且属主相符」。后者会把正常失败登记全部挡掉：失败登记发生在消费
    事务回滚之后的独立事务里，回滚后库里是 `pending` 且 `lease_owner IS NULL`
    （领取从未提交）。看不见的未提交领取由行锁串行化，不需要本栅栏判断；
    本栅栏只负责一件能看见的事：别人**已提交**的活跃租约不得被迟到失败踩掉。

    `lease_expires_at IS NULL` 时比较为 NULL ⇒ 不满足 ⇒ 拒绝（fail-closed）。
    租约字段为空的非 `processing` 行为本仓不变量，正常路径不会走到这一支。
    """
    return or_(
        PendingWrite.lease_owner.is_(None),
        PendingWrite.lease_owner == lease_owner,
        PendingWrite.lease_expires_at <= reference,
    )


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
    """写入一条待处理记录（与业务数据同一事务，第 3 节）。

    Args:
        session: 关系库会话（调用方负责提交事务——记录必须与业务数据同事务，
            事务回滚则记录不存在）。
        kind: 记录种类，取值见 `KINDS`。
        account_id: 发起者；记忆的分区键即此值。
        origin: 生成方式，取值见 `ORIGINS`。
        payload: 自足的最小载荷（Worker 只凭它就能完成写入）。
        source: 来源信息（会话 id、消息 seq、工具名、时间）。
        support_object_id: 仅 `profile_item` 需要；`memory_episode` 必须传 `None`。
        pending_id: 可选的确定性标识（重放/测试用）。不给则生成新的 uuid4。

    Returns:
        已加入会话的记录（尚未提交）。

    Raises:
        InsufficientPayloadError: 词表外的取值、归属字段与 `kind` 不匹配，
            或 `account_id` 超宽。这些判据在存储层也有 CHECK/宽度约束；这里提前
            拒绝是为了给出可读的错误，而不是让调用方读到数据库的约束名。
    """
    if kind not in KINDS:
        raise InsufficientPayloadError(f"kind 不在词表内：{kind!r}（合法取值={sorted(KINDS)}）")
    if origin not in ORIGINS:
        raise InsufficientPayloadError(f"origin 不在词表内：{origin!r}（合法取值={sorted(ORIGINS)}）")
    if not account_id:
        raise InsufficientPayloadError("account_id 为空")
    if len(account_id) > MAX_ACCOUNT_ID_LENGTH:
        # 长度上界必须显式：只判空时，超宽值会一路走到 INSERT 才由 PostgreSQL
        # 抛出裸 `DBAPIError`——调用方拿到的是驱动异常而不是领域异常，
        # 且看不出是哪个字段的问题。
        # 形状（字符集）不在此校验：本包不得依赖业务模块，见 `PendingWrite.account_id`。
        raise InsufficientPayloadError(f"account_id 超过 {MAX_ACCOUNT_ID_LENGTH} 字符上界（实际 {len(account_id)}）")
    if not isinstance(payload, dict):
        raise InsufficientPayloadError(f"payload 必须是对象，收到 {type(payload).__name__}")
    if not isinstance(source, dict):
        raise InsufficientPayloadError(f"source 必须是对象，收到 {type(source).__name__}")

    # 归属字段按 kind 的判据（第 3 节）。
    # 与存储层 CHECK 同一条规则，此处提前报错。
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

    可领取的条件（三选一，都是「未终结」）：
      - `pending`：从未领过，或上次失败后退避已到期；
      - `processing` 且租约已过期：Worker 崩溃，可被重新领取；
      - `failed`：可重试失败，退避到期后重新领取。

    Args:
        session: 关系库会话。
        pending_id: 待领取记录标识。
        lease_owner: 领取者标识（Worker 实例名），写入 `lease_owner` 供排查。
        now: 参照时间，默认当前 UTC——显式可传以便测试租约过期的确定性。

    Returns:
        领取到的记录；未领到返回 `None`（不是异常）——「没领到」是并发的正常结果，
        不是错误。调用方据此跳过即可。

    Note:
        用「条件更新 + RETURNING」在一条 SQL 内完成判定与占用（见模块说明）：
        改成先查后改会让两个 Worker 同时认为自己领到了同一条记录。

        为什么领取必须走 UPDATE ... RETURNING 而不是「先查后改」：

        第 4 节明确「不使用先查后改的无锁流程」。两个 Worker 同时查同一条记录、
        都看到 `pending`、都去改，会双双认为领到了，于是同一条记忆被抽取两次。
        因此这里的领取是单条 SQL 的条件更新：

            UPDATE ... SET state='processing', lease_owner=... WHERE id=... AND <可领取条件>
            RETURNING ...

        数据库的行锁保证只有一个事务能把它从「可领取」改成「processing」；另一个更新的
        `WHERE` 不再匹配，`RETURNING` 为空 → 调用方明确知道「没领到」，而不是猜。

        租约过期的重新领取：

        `lease_expires_at` 过期即视为可领取（第 6 节：Worker 崩溃不该让记录永久卡住）。
        过期不等于失败：`attempts` 只在真正失败时 +1（见 `mark_retryable_failure`），
        崩溃重启不该消耗重试预算——否则反复崩溃会把一条本来健康的记录耗成 `dead`。
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
    lease_owner: str | None = None,
    now: datetime | None = None,
) -> PendingWrite:
    """标记写入成功（第 4 节）：置 `done`、记 `finished_at`，并清理租约。

    同一事务内清理租约是第 4 节的要求：留着租约会让排查时看不出「这条已经不归谁管了」。

    Args:
        session: 关系库会话。
        pending_id: 待处理记录标识。
        lease_owner: 租约栅栏（CORE-03 迟到响应守卫）。给了就要求与库中记录一致，
            不一致则显式失败。为什么需要（2026-09-29 评审 C-3 实测）：慢抽取（超过
            5 分钟租约）会让租约过期、记录被另一个 Worker 重领；此时先领取者的
            迟到 `mark_done` 会抢先成功，而真正写入者的终结反而抛
            `PendingWriteNotFoundError`——制造一个假失败（Taskiq 记为失败、丢摘要）。
            实测复现该序列。
        now: 参照时间。

    Raises:
        PendingWriteNotFoundError: 记录不存在、已处于终结状态，或租约已被他人持有
            （`lease_owner` 不匹配）。三者都必须让调用方知道本次没有推进任何东西——
            静默返回成功会让「刚才那个 done 是谁标的」无从查起。
    """
    reference = now if now is not None else _utc_now()
    conditions = [
        PendingWrite.id == pending_id,
        PendingWrite.state.notin_((STATE_DONE, STATE_DEAD)),
    ]
    if lease_owner is not None:
        conditions.append(PendingWrite.lease_owner == lease_owner)
    statement = (
        update(PendingWrite)
        .where(*conditions)
        .values(
            state=STATE_DONE,
            finished_at=reference,
            lease_owner=None,
            lease_expires_at=None,
            last_error=None,
            # 清掉退避时刻：`done` 是终态，留着过期的 `next_attempt_at` 会让排查
            # 误判「这条还会重试」。
            next_attempt_at=None,
            updated_at=reference,
        )
        .returning(PendingWrite)
    )
    record = (await session.execute(statement)).scalar_one_or_none()
    if record is None:
        detail = "不存在，或已是 done/dead（不可重复终结）"
        if lease_owner is not None:
            detail = f"{detail}，或租约已不属于 {lease_owner!r}（迟到响应不得改变状态）"
        raise PendingWriteNotFoundError(pending_id, detail)
    return record


async def mark_retryable_failure(
    session: AsyncSession,
    *,
    pending_id: uuid.UUID | str,
    error: str,
    lease_owner: str | None = None,
    now: datetime | None = None,
) -> PendingWrite:
    """可重试失败（第 6 节）：`attempts + 1`、按退避后移 `next_attempt_at`、回 `pending`。

    超过 `MAX_ATTEMPTS` 时转 `dead`（第 6 节：不得静默丢弃）。

    Args:
        session: 关系库会话。
        pending_id: 待处理记录标识。
        error: 失败摘要。只记摘要，不复述连接串或凭据（AGENTS.md 安全条款）；
            超长时截断（见 `MAX_LAST_ERROR_LENGTH`）。
        lease_owner: 租约栅栏（可选）。给了就要求「不存在别人持有的未过期租约」，
            否则显式失败——迟到的失败登记不得把别人正在处理的记录改回 `pending`、
            清掉它的租约或消耗它的重试预算。**不给则不校验**（兼容既有调用方）；
            消费任务应显式传入自己的 `lease_owner`。
            为什么不要求「必须是 `processing` 且属主相符」：失败登记跑在消费事务
            **回滚之后**的独立事务里，而领取与写入同在一个事务内、回滚后不可见
            ——那时库里是回滚前的 `pending`、`lease_owner IS NULL`。要求属主相符
            会把正常失败登记全部挡掉（记录永远停在 `pending`、不增 `attempts`、
            永不进 `dead`）。未提交的领取由行锁串行化，不靠本栅栏判断。
        now: 参照时间。

    Returns:
        更新后的记录（`state` 为 `pending` 或 `dead`）。

    Raises:
        PendingWriteNotFoundError: 记录不存在、已终结，或存在别人持有的未过期租约。
    """
    reference = now if now is not None else _utc_now()
    conditions = [
        PendingWrite.id == pending_id,
        PendingWrite.state.notin_((STATE_DONE, STATE_DEAD)),
    ]
    if lease_owner is not None:
        conditions.append(_lease_fence(lease_owner, reference))
    # 先原子地自增并取回新值：并发两次失败各 +1，不会互相覆盖（用 SQL 表达式而不是
    # 读-改-写）。
    bumped = (
        await session.execute(
            update(PendingWrite)
            .where(*conditions)
            .values(attempts=PendingWrite.attempts + 1, updated_at=reference)
            .returning(PendingWrite.attempts)
        )
    ).scalar_one_or_none()

    if bumped is None:
        detail = "不存在，或已终结（不可再记失败）"
        if lease_owner is not None:
            detail = f"{detail}，或租约已属于别的 Worker（迟到失败不得改变状态）"
        raise PendingWriteNotFoundError(pending_id, detail)

    summary = error[:MAX_LAST_ERROR_LENGTH]
    if bumped >= MAX_ATTEMPTS:
        # 同一栅栏必须延续到 dead：耗尽重试的终结同样不得踩别人的活跃租约。
        return await mark_dead(session, pending_id=pending_id, error=summary, now=reference, lease_owner=lease_owner)

    statement = (
        update(PendingWrite)
        .where(*conditions)
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
    lease_owner: str | None = None,
    now: datetime | None = None,
) -> PendingWrite:
    """转 `dead`（第 6 节：超过重试上限并告警，不得静默丢弃）。

    本函数只负责状态；告警由调用方发出——本模块不引入日志/告警依赖，
    避免 `core/pending_write` 依赖可观测设施（它是状态机，不是运维组件）。

    `lease_owner` 是租约栅栏（可选，语义与 :func:`mark_retryable_failure` 相同）：
    给了就拒绝「存在别人持有的未过期租约」时的终结，否则一次迟到的不可重试判定
    会把别人正在处理的记录直接置成 `dead`（它的那次写入就再没有记录可对账）。

    调用方契约：每个调用方都必须保证这条记录进 `dead` 时有专属告警，
    不能只打可重试失败的 warning。实测的调用点共三处（2026-09-30 核实）：

    - `repository.mark_retryable_failure`（重试耗尽）：告警在其调用方
      `worker._register_retryable_failure` 里依返回值 `state == STATE_DEAD` 发出；
    - `worker._mark_dead_and_alert`（不可重试的终结：记忆侧载荷不合法、档案侧
      载荷不合法与授权不成立），由两个消费者的三条分支调用——记忆侧那条分支
      经它收口，唯一的 `mark_dead` 调用点因此都带告警。

    Raises:
        PendingWriteNotFoundError: 记录不存在、已处于终结状态，或存在别人持有的未过期租约。
    """
    reference = now if now is not None else _utc_now()
    conditions = [
        PendingWrite.id == pending_id,
        PendingWrite.state.notin_((STATE_DONE, STATE_DEAD)),
    ]
    if lease_owner is not None:
        conditions.append(_lease_fence(lease_owner, reference))
    statement = (
        update(PendingWrite)
        .where(*conditions)
        .values(
            state=STATE_DEAD,
            finished_at=reference,
            lease_owner=None,
            lease_expires_at=None,
            last_error=error[:MAX_LAST_ERROR_LENGTH],
            # 清掉退避时刻：`dead` 是终态，留着过期的 `next_attempt_at` 会让排查
            # 误判「这条还会重试」。
            next_attempt_at=None,
            updated_at=reference,
        )
        .returning(PendingWrite)
    )
    record = (await session.execute(statement)).scalar_one_or_none()
    if record is None:
        detail = "不存在，或已是 done/dead（不可重复终结）"
        if lease_owner is not None:
            detail = f"{detail}，或租约已属于别的 Worker（迟到终结不得改变状态）"
        raise PendingWriteNotFoundError(pending_id, detail)
    return record


async def reclaim_expired_leases(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> list[uuid.UUID]:
    """把租约过期的记录放回 `pending`，返回被回收的 id 列表（第 6 节）。

    不增加 `attempts`：Worker 崩溃不是「尝试失败」，消耗重试预算会让反复崩溃的
    环境把健康记录耗成 `dead`。

    生产可达性：当前接线下恒返回空（2026-09-30 实测，不是推断）

    判据是「存在已提交的 `processing` 行」。当前没有产生者：

    - 两个消费者（`modules/memory/consumer.consume_memory_episode`、
      `modules/profile/consumer.write_from_pending`）的「领取 → 写 → 置 `done`」
      在同一个 `session_scope` 事务里，`take_for_processing` 与 `mark_done` 收的是
      调用方那一个会话；
    - 全仓的 `session.commit()` 只出现在 `core/db.session_scope` 与
      `core/auth/deletion.py`，两处消费者都不自行提交；
    - 因此 `state='processing'` 只在未提交的事务里存在，提交时它已经是 `done`
      或被回滚成上一次提交的 `pending`。

    实测（第二个连接观测，看图库写入期间的消费事务）：观测到
    `state=pending`、`lease_owner=None`；第二个事务的领取 `UPDATE` 被行锁挡住，
    1.5 秒 `statement_timeout` 到期抛 `DBAPIError`；消费提交后同一行才是 `done`。
    所以崩溃的 Worker 留下的是提交过的 `pending`，不是 `processing`。

    真实崩溃恢复走的是 `find_undelivered` 重投那条路

    连接断开 → 事务回滚 → 行仍是 `pending` → 兜底扫描（`worker.sweep_once`）
    按 `pending` 重投。本函数的逻辑因此不承重，但仍在每轮扫描里先跑一次。

    为何保留它（纵深，不是死代码）

    若将来「领取」改成单独提交（例如为了让租约栅栏承重），库里立刻会出现已提交的
    `processing` 行，本函数随即承重——同一判断也是 `mark_done` 的租约栅栏
    （D-31）保留的理由。删掉它会让那次改动没有回收者，记录永久卡在 `processing`。
    本说明与 `tests/test_pending_write_sweep_integration.py` 的
    `test_sweep_once_reclaims_expired_leases_before_dispatching` 不冲突：
    那条用例钉的是机制本身（用已提交的 `processing` 行构造前提），
    钉的不是「生产上会出现这种行」。

    Args:
        session: 关系库会话。
        now: 参照时间。
        limit: 单次回收条数上界。收敛到 `RECLAIM_MAX_LIMIT`（CORE-11）：扫描周期
            固定，无界回收会让一次扫描在积压时耗时不可控。
            超界入参（如 `limit=10**9`）不得原样放进 SQL；同一纪律在
            `store.read_timeline` 与 `derived.read_emergency_facts` 都已落地。

    Returns:
        被回收的记录 id（按 id 升序，稳定）。空列表表示没有需要回收的记录。

    Note:
        只回收仍处于 `processing` 的记录：`SELECT` 与 `UPDATE` 之间有窗口，
        期间记录可能已被正常终结；恢复 `pending` 会把已完成的记忆重新排队
        （同一记忆被抽取两次），故 `UPDATE` 也带 state 守卫。
    """
    reference = now if now is not None else _utc_now()
    effective_limit = max(1, min(limit, RECLAIM_MAX_LIMIT))
    # 先选出一批 id（有界），再按 id 更新。
    # 避免 `UPDATE ... LIMIT` 的方言差异。
    candidates = (
        await session.execute(
            select(PendingWrite.id)
            .where(
                PendingWrite.state == STATE_PROCESSING,
                PendingWrite.lease_expires_at.is_not(None),
                PendingWrite.lease_expires_at < reference,
            )
            .order_by(PendingWrite.id)
            .limit(effective_limit)
        )
    ).scalars()
    ids = list(candidates)
    if not ids:
        return []

    # `RETURNING id` 而不是直接返回 `ids`：加了 state 守卫后，窗口内被终结的记录会被
    # UPDATE 跳过，而返回值必须只含真正回收成功的——否则调用方会以为某条被回收了
    # （进而可能重复投递），与库里实际状态不符（2026-09-29 实测：守卫生效但返回值仍含
    # 那条已被终结的记录）。
    result = await session.execute(
        update(PendingWrite)
        .where(
            PendingWrite.id.in_(ids),
            # state 守卫：`SELECT` 与 `UPDATE` 之间存在真实窗口，另一事务可能在该窗口内
            # 把记录置成终态。缺这个守卫时，一条已经 `done` 的记录会被改回 `pending`
            # （且 `finished_at` 仍保留，形成 `pending` + `finished_at` 非空的自相矛盾行），
            # 随后被再次领取——同一条记忆抽取两次。
            # `mark_done`/`mark_dead` 一直是带守卫的单条 UPDATE，回收用同一条纪律。
            PendingWrite.state == STATE_PROCESSING,
        )
        .values(
            state=STATE_PENDING,
            lease_owner=None,
            lease_expires_at=None,
            # 立刻可领（不设退避）：崩溃恢复应当尽快重试。
            next_attempt_at=None,
            updated_at=reference,
        )
        .returning(PendingWrite.id)
    )
    return list(result.scalars())


async def find_undelivered(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    kinds: Collection[str] | None = None,
    limit: int = SWEEP_MAX_LIMIT,
) -> list[tuple[uuid.UUID, str]]:
    """找出该被处理却还没被处理的记录（兜底扫描的候选集，第 4.1 节）。

    它补的是什么：

    投递失败或 Worker 从未启动时，记录会永久停在 `pending`。本函数是「丢的任务
    可被检测」的那一半——见 docs/技术栈设计.md 第 2 节把 Taskiq
    列为准则 1 的例外（该库自报 Alpha），其可接受理由正是这条兼底控制。

    判据：只挑「该被处理而没被处理」的

    - `state = pending` 且 `next_attempt_at` 已到（或为空）——含从未成功投递的，
      以及退避到期的；
    - 不含 `processing`：租约过期的属于「领取后 Worker 崩溃」，由
      `reclaim_expired_leases` 处理（那条路径不消耗 `attempts`，语义不同）。
      当前接线下不会出现已提交的 `processing` 行，故崩溃恢复实际走的是本函数
      重投 `pending` 那条路——理由与实测见 `reclaim_expired_leases` 的说明；
    - 不含 `done`/`dead`：终态不得被复活（`mark_done`/`mark_dead`/回收都有 state
      守卫，这里是同一纪律的第一道）。

    为什么返回 `(id, kind)`：投递必须按 `kind` 分派（第 4 节第 3 条）。
    只返回 id 时，调用方只能把每条记录都投给同一个消费者——那正是「档案条目被投给
    记忆消费者、被当成载荷不合法判 `dead`」的成因。kind 在候选集里一并取出，
    投递方不必再回查一次。

    为什么要按 `kinds` 过滤：

    兜底扫描只该挑「当前有消费者」的 kind。没有消费者的 kind 投出去也没人接，
    投递方只能显式跳过；而它们会一直停在 `pending`，又按 `created_at` 排在最前，
    于是每轮都占满 `limit` 预算、把真正该重投的记忆记录饿死在候选集之外。
    过滤掉它们才是「不该被处理的记录不占扫描预算」。
    接上消费者后无需改这里：把 kind 加进扫描传入的集合即可自动重新进入候选集。

    为什么不需要「已投递」标记列：

    重复投递是安全的：领取是单条条件更新（并发下只有一个赢家），且确定性 episode
    uuid 使重复消费不产生重复内容（第 5 节）。因此扫描只需按状态与时间挑，无需记账
    「这条投过没有」——那会多一张状态表，而收益为零。

    有界（CORE-11）：

    `limit` 收敛到 `SWEEP_MAX_LIMIT`：扫描周期固定，无界查询在积压时耗时不可控。

    Args:
        session: 关系库会话。
        now: 参照时间。
        kinds: 只挑这些 kind 的记录；`None` 表示不按 kind 过滤（全部）。
            空集合表示「没有任何 kind 可投递」，返回空列表——不是「不过滤」。
            取值集由调用方（Worker 的分派表）给出，本模块不知道谁有消费者。
        limit: 单次返回条数上界；收敛到 `SWEEP_MAX_LIMIT`。

    Returns:
        待重投的 `(id, kind)`（按 `next_attempt_at`、`created_at`、`id` 升序，稳定）：
        最早该处理的先投，避免积压时新记录一直插到前面。
    """
    reference = now if now is not None else _utc_now()
    effective_limit = max(1, min(limit, SWEEP_MAX_LIMIT))
    statement = (
        select(PendingWrite.id, PendingWrite.kind)
        .where(
            PendingWrite.state == STATE_PENDING,
            or_(PendingWrite.next_attempt_at.is_(None), PendingWrite.next_attempt_at <= reference),
        )
        .order_by(PendingWrite.next_attempt_at.asc().nullsfirst(), PendingWrite.created_at, PendingWrite.id)
        .limit(effective_limit)
    )
    if kinds is not None:
        # 排序后入参：同一集合每次生成同一条 SQL，便于按语句缓存与排查。
        statement = statement.where(PendingWrite.kind.in_(sorted(kinds)))
    rows = (await session.execute(statement)).all()
    # 显式解包成元组：`Row` 是 SQLAlchemy 的行对象，直接外传会让调用方依赖它的取值方式。
    return [(row[0], row[1]) for row in rows]


__all__ = [
    "LEASE_SECONDS",
    "MAX_ATTEMPTS",
    "MAX_LAST_ERROR_LENGTH",
    "RECLAIM_MAX_LIMIT",
    "SWEEP_MAX_LIMIT",
    "InsufficientPayloadError",
    "PendingWriteError",
    "PendingWriteNotFoundError",
    "enqueue",
    "find_undelivered",
    "mark_dead",
    "mark_done",
    "mark_retryable_failure",
    "reclaim_expired_leases",
    "take_for_processing",
]
