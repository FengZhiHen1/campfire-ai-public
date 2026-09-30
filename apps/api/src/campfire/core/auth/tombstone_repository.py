"""注销墓碑的写入与查询。

形状由 docs/技术设计/decisions/账号注销与墓碑.md
与 docs/技术设计/technical-details/认证与账号.md
第 8 节拥有。表结构见本包的 `tombstone.py`。

为什么写入必须幂等，且「已存在」算成功：

注销的编排者（`core/auth/deletion.delete_account`；CLI 经它调用）可能在重试时
再次调用它（例如第 2 步失败后整体重跑）。若第二次调用报错，重试路径会把「其实已经
写好了」当作失败——而墓碑先于所有删除动作，这会让操作者以为注销没有开始，
转而排查一个不存在的问题。

因此 :func:`record_deletion` 的语义是「确保该账号已有墓碑」：
已存在则返回既有行，并明确告知「本次是已存在」（返回值里带 `created` 标志），
让调用方能区分「我刚写的」与「之前就有的」——不推测、不猜测（`CORE-07`）。

为什么查询要能批量：

Worker 的消费路径按 `pending_id` 单条处理，但注销编排与排查需要「这批账号里
哪些已注销」。批量查询用一条 `IN` 查询而不是循环——避免 N+1（性能维度包）。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.core.auth.tombstone import (
    DELETION_REASON_USER_REQUEST,
    MAX_ACCOUNT_ID_LENGTH,
    TOMBSTONE_REASONS,
    AccountDeletionTombstone,
)

#: 批量查询的条数上界（CORE-11：外部输入必须有界）。
BATCH_MAX_ACCOUNTS = 1000


class TombstoneError(Exception):
    """墓碑操作的统一异常基类。

    与其他 `core/*` 组件一致：调用方（Worker、注销用例）需要能一句 `except`
    收口，而不必知道底层是 SQLAlchemy。
    """


class TombstonePayloadError(TombstoneError):
    """入参不满足墓碑的形状约束。

    与 :class:`TombstoneError` 的其它子类区分：这个不该重试（是调用方的问题），
    而依赖故障应当是可重试的——与 `core/pending_write` 的
    `InsufficientPayloadError` 同一种分层思路。
    """

    def __init__(self, detail: str) -> None:
        """记录不合格的原因（不含账号内容）。"""
        self.detail = detail
        super().__init__(f"墓碑的形状不合法：{detail}")


class TombstoneResult(NamedTuple):
    """`record_deletion` 的结果。

    为什么要有 `created` 标志而不是只返回记录：注销编排在重试时需要区分
    「本次写入的墓碑」（说明这是第一次、后续删除步骤尚未执行）与
    「之前就已存在的墓碑」（说明上一次执行已经走过这一步，可能是重跑）。
    两者的正确后续动作不同，而从记录本身看不出这个差别。
    """

    account_id: str
    deleted_at: datetime
    reason: str
    #: True 表示本次调用新建了墓碑；False 表示该账号此前已有墓碑。
    created: bool


def _utc_now() -> datetime:
    """当前 UTC 时间。集中一处，便于测试替换时只有一个改动点。"""
    return datetime.now(timezone.utc)


def _validate_account_id(account_id: object) -> str:
    """校验账号标识的形状（长度与空值）。

    只校验长度与空值，不校验字符集：字符集判据（Graphiti 的 `group_id`）
    属于业务模块（`modules/memory/identity.to_account_id`），而 `core/*`
    不得依赖业务模块（依赖白名单）。本层保证的是「落库不会因超宽而抛裸
    `DBAPIError`」——与 `PendingWrite.account_id` 同一条说明。
    """
    if not isinstance(account_id, str):
        raise TombstonePayloadError(f"账号标识必须是字符串，收到 {type(account_id).__name__}")
    if not account_id:
        raise TombstonePayloadError("账号标识为空")
    if len(account_id) > MAX_ACCOUNT_ID_LENGTH:
        raise TombstonePayloadError(f"账号标识超过 {MAX_ACCOUNT_ID_LENGTH} 字符上界（实际 {len(account_id)}）")
    return account_id


async def record_deletion(
    session: AsyncSession,
    *,
    account_id: object,
    reason: str = DELETION_REASON_USER_REQUEST,
    now: datetime | None = None,
) -> TombstoneResult:
    """确保该账号有注销墓碑（幂等）。

    调用契约（不能省）：这是注销五步中的第 1 步，必须先于任何删除动作
    （[认证与账号] 第 8 节：顺序不可调换）。理由见 `tombstone.py`：墓碑是 Worker
    判定「已注销」的唯一依据，先删账号会让中间窗口内的消费把数据写回。

    幂等性由存储层主键承载（`ON CONFLICT DO NOTHING`），不在应用层先查后写——
    并发两次注销请求若都先查到「没有墓碑」，就会都去插入，其中一个撞主键报错。

    Args:
        session: 关系库会话（调用方负责提交）。
        account_id: 账号标识（运行时边界，类型未知）。
        reason: 注销原因，取值见 `tombstone.TOMBSTONE_REASONS`。
        now: 参照时间，默认当前 UTC。

    Returns:
        :class:`TombstoneResult`；`created` 区分本次是否新建。

    Raises:
        TombstonePayloadError: 账号标识不合法，或 `reason` 不在词表内。
            词表在应用层也校验一次：存储层 CHECK 会抛裸 `IntegrityError`，
            调用方看不出是哪个字段的问题。
    """
    normalized = _validate_account_id(account_id)
    if reason not in TOMBSTONE_REASONS:
        raise TombstonePayloadError(f"reason 不在词表内：{reason!r}（合法取值={sorted(TOMBSTONE_REASONS)}）")

    reference = now if now is not None else _utc_now()

    # `ON CONFLICT DO NOTHING` + `RETURNING`：插入成功则返回新行（created=True）；
    # 冲突则返回空（created=False），此时再读既有行。
    # 这样「是否新建」由存储层的事实决定，不是应用层的猜测。
    statement = (
        pg_insert(AccountDeletionTombstone)
        .values(account_id=normalized, deleted_at=reference, reason=reason)
        .on_conflict_do_nothing(index_elements=[AccountDeletionTombstone.account_id])
        .returning(AccountDeletionTombstone)
    )
    inserted = (await session.execute(statement)).scalar_one_or_none()
    if inserted is not None:
        return TombstoneResult(
            account_id=inserted.account_id,
            deleted_at=inserted.deleted_at,
            reason=inserted.reason,
            created=True,
        )

    existing = await get_tombstone(session, account_id=normalized)
    if existing is None:
        # 冲突了却查不到：只可能是并发事务尚未提交。显式失败，不猜。
        raise TombstoneError("墓碑插入未成功但查询不到既有记录（疑似并发注销尚未提交）")
    return TombstoneResult(
        account_id=existing.account_id,
        deleted_at=existing.deleted_at,
        reason=existing.reason,
        created=False,
    )


async def get_tombstone(
    session: AsyncSession,
    *,
    account_id: object,
) -> AccountDeletionTombstone | None:
    """按账号取墓碑；不存在返回 `None`。

    这是 Worker 写入前判定的入口：拿到非 `None` 即表示该账号已注销，
    对应的在途写入必须丢弃（不得写回图库）。

    Raises:
        TombstonePayloadError: 账号标识不合法（长度/空值/类型）。
    """
    # quality-floor: ignore docstring-promise 异常由 _validate_account_id 抛出（间接 raise），本函数只做查询
    normalized = _validate_account_id(account_id)
    return (
        await session.execute(select(AccountDeletionTombstone).where(AccountDeletionTombstone.account_id == normalized))
    ).scalar_one_or_none()


async def is_account_deleted(session: AsyncSession, *, account_id: object) -> bool:
    """该账号是否已注销（最常用的问法，只取存在性、不取整行）。

    实现上用 `SELECT 1 ... LIMIT 1` 而不是取整行：Worker 在每个待处理记录上都会问
    一次，少取列就少一次行构造（性能维度包：热路径不做多余工作）。

    Raises:
        TombstonePayloadError: 账号标识不合法（长度/空值/类型）。
    """
    # quality-floor: ignore docstring-promise 异常由 _validate_account_id 抛出（间接 raise），本函数只做查询
    normalized = _validate_account_id(account_id)
    found = (
        await session.execute(
            select(1)
            .select_from(AccountDeletionTombstone)
            .where(AccountDeletionTombstone.account_id == normalized)
            .limit(1)
        )
    ).scalar_one_or_none()
    return found is not None


async def deleted_account_ids(
    session: AsyncSession,
    *,
    account_ids: Sequence[str],
) -> set[str]:
    """批量查询：这批账号里哪些已注销。

    用一条 `IN` 查询而不是逐个查（避免 N+1）。

    为什么入口要拒绝 `str`（2026-09-30 评审抓出的静默误报）：

    第一版只校验 `len()` 上界，不校验容器类型。传入 `str` 时
    `for value in account_ids` 会逐字符迭代，于是
    `IN ('i','t','_')` → 返回空集，即静默回答「这些账号都没注销」。
    这正是墓碑要防的「删后复活」的入口——调用方少写一层 `[ ... ]` 就会拿到
    与事实相反的答案，而且不报错。评审实测：传 `str` 返回空集、传 `None`
    或生成器抛裸 `TypeError`。

    Args:
        session: 关系库会话。
        account_ids: 待查的账号标识序列（list/tuple/set）。空序列直接返回空集
            （不发查询）。不接受 `str`/`bytes`/生成器/`None`——见上。

    Returns:
        已注销账号的集合（可能是空集）。

    Raises:
        TombstonePayloadError: 容器类型不对、超长（`BATCH_MAX_ACCOUNTS`），
            或含不合法的标识。
    """
    # 类型守卫必须在 `len()` 之前：`str` 与 `bytes` 都有 `len()`，但它们迭代出的是
    # 字符/整数，会造成上面说的静默空集。生成器与 None 没有 `len()`，会抛裸 TypeError。
    if isinstance(account_ids, (str, bytes)) or not isinstance(account_ids, (list, tuple, set, frozenset)):
        raise TombstonePayloadError(
            f"account_ids 必须是账号标识的序列（list/tuple/set），收到 {type(account_ids).__name__}"
            "——传字符串会被逐字符校验并静默返回空集（误报「都没注销」）"
        )
    # 先转成 list：`set`/`frozenset` 没有稳定的顺序，重复元素也不该重复查。
    candidates = list(account_ids)
    if len(candidates) > BATCH_MAX_ACCOUNTS:
        raise TombstonePayloadError(f"批量查询超过 {BATCH_MAX_ACCOUNTS} 个账号上界（实际 {len(candidates)}）")
    if not candidates:
        return set()
    normalized = [_validate_account_id(value) for value in candidates]
    rows = (
        await session.execute(
            select(AccountDeletionTombstone.account_id).where(AccountDeletionTombstone.account_id.in_(normalized))
        )
    ).scalars()
    return set(rows)


__all__ = [
    # 常量
    "BATCH_MAX_ACCOUNTS",
    # 异常
    "TombstoneError",
    "TombstonePayloadError",
    # 结果
    "TombstoneResult",
    # 读写
    "deleted_account_ids",
    "get_tombstone",
    "is_account_deleted",
    "record_deletion",
]
