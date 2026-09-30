"""删除与纠正的用例层：把记忆从两条读路径上撤下。

归属（见 docs/技术设计/technical-details/通用记忆.md 第 7 节）：本模块拥有
「删除一条记忆」与「纠正一条记忆」两个用例，是 `RQ-MEM-03` / `AC-08` 的承载。
边界：只写账本、不调图库——账本过滤是语义删除的唯一生效点（理由见 `delete_episode`）；纠正 = 删旧 + 写新（见 `correct_episode`）。
参考：`docs/技术设计/technical-details/通用记忆.md` 第 7 节。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.modules.memory.errors import EpisodeKeyOwnedByAnotherAccountError, MemoryDataError
from campfire.modules.memory.identity import AccountId, EpisodeUuid, to_account_id, to_episode_key
from campfire.modules.memory.ledger import DeletionOutcome, DeletionRecord, record_deletion
from campfire.modules.memory.models import (
    DELETION_REASON_CORRECTION,
    DELETION_REASON_USER_REQUEST,
    MemoryDeletionLedger,
)


@dataclass(frozen=True, slots=True)
class DeletionResult:
    """一次删除/纠正中，账本记录的结果。

    字段刻意与 `ledger.DeletionRecord` 同形但有语义差异：这里的 `newly_deleted`
    是面向使用者的结论（`False` = 这条记忆此前已删除），调用方据此决定文案；
    而 `DeletionOutcome` 是存储层的机械结果（`RECORDED` / `ALREADY_RECORDED`）。
    """

    episode_key: str
    #: 本次是否真的新记入了账本（`False` = 此前已删除，幂等命中）。
    newly_deleted: bool
    #: 删除原因（`user_request` / `correction` / `account_deletion`）。
    reason: str


# quality-floor: ignore docstring-promise 异常由 _record 与 record_deletion 抛出并原样传播，函数体只做编排
async def delete_episode(
    session: AsyncSession,
    *,
    account_id: AccountId,
    episode_key: EpisodeUuid | str,
    deleted_by: str | None = None,
    derived_uuids: list[str] | None = None,
) -> DeletionResult:
    """删除一条记忆（幂等）：记入账本后，两条读路径都不再返回它。

    为什么删除只需要写账本：

    账本过滤是语义删除的唯一生效点（第 7 节），图库物理删除不是。因此删除的
    正确性不依赖任何图库操作：把 key 记入账本后，两条读路径（`store.read_timeline`
    与 `derived.read_emergency_facts`）在下一次查询时就已经看不到它了。

    这带来一个重要性质：删除不会因为图库不可用而失败。若把图库操作放进删除路径，
    一个正常的删除请求会因基础设施故障而不可用——而账本写入是本库（PostgreSQL）的
    事务，与图库是两回事。因此本模块不调图库，`derived_uuids` 只做尽力记录
    （第 7 节已明确它「不作过滤依据」）。

    Args:
        session: 关系库会话（调用方负责提交事务）。
        account_id: 归属账号（分区键同源，由登录态决定）。
        episode_key: 要删除的 episode 标识（`identity.to_episode_key` 会校验形状）。
        deleted_by: 发起删除的账号；一期与 `account_id` 同值。
        derived_uuids: 删除时已知的派生物清单（尽力记录，不作过滤依据）。

    Returns:
        `DeletionResult`，含「是否本次真的新删除」。

    Raises:
        EpisodeKeyOwnedByAnotherAccountError: 该 key 已被其它账号记入删除账本
            （fail-closed，见 `ledger.record_deletion` 的 Note）。
        MemoryDataError: `episode_key` 形状非法，或删除原因不在词表内。

    Note:
        重复删除不是错误：`newly_deleted=False` 表示此前已删除。把幂等命中当错误
        会让调用方在重试时收到失败，而删除实际上已经生效。
    """
    record = await _record(
        session,
        account_id=account_id,
        episode_key=episode_key,
        reason=DELETION_REASON_USER_REQUEST,
        deleted_by=deleted_by,
        derived_uuids=derived_uuids,
    )
    return _to_result(record)


# quality-floor: ignore docstring-promise 异常由 _record 抛出并原样传播，函数体只做编排
async def correct_episode(
    session: AsyncSession,
    *,
    account_id: AccountId,
    corrected_episode_key: EpisodeUuid | str,
    deleted_by: str | None = None,
    derived_uuids: list[str] | None = None,
) -> DeletionResult:
    """纠正一条记忆的第一步：把旧 episode 记入账本（原因 `correction`）。

    纠正为什么是「删旧 + 写新」而不是「改」：

    第 7 节：纠正 = 删除旧 episode + `write_memory` 写新 episode（`occurred_at` 用纠正
    所指的发生时间）。不能指望旧派生边自动失效——已实测（2026-09-29，纯函数
    `resolve_edge_contradictions`）：只有新事实 `valid_at` 严格更晚时旧边才被置
    `invalid_at`，更早或同时间都不失效，而纠正恰恰允许更早。因此纠正的正确性同样
    落在账本过滤上：旧 episode 一进账本，引用它的派生边就不再注入。

    本函数只做「撤下旧记忆」这一步；写新记忆是调用方的责任
    （`store.write_episode` + 写入路径的幂等标记，见写入路径.md 第 5 节）。
    分开的理由：两步的失败语义完全不同——账本写入是本库事务（要么成功要么回滚），
    而写新记忆要走图库与模型抽取（可能失败、可重试）。把它们塞进一个函数会让
    「旧记忆已撤下、新记忆没写成」这个中间态对调用方不可见；分开后调用方明确知道
    自己处在哪一步，可以按写入路径的重试纪律处理。

    顺序是先撤下旧记忆再写新的：反过来会有一段「新旧同时有效」的窗口，而纠正
    的语义是旧内容不得再作为依据（`RQ-MEM-01`）。先撤下则最坏情形是「暂时没有这条
    记忆」，比「旧错误内容继续被当作当前认识」安全。

    Args:
        session: 关系库会话（调用方负责提交事务）。
        account_id: 归属账号。
        corrected_episode_key: 被纠正的旧 episode 标识。
        deleted_by: 发起纠正的账号。
        derived_uuids: 尽力记录的被撤下派生物。

    Returns:
        旧记忆的账本记录结果。

    Raises:
        EpisodeKeyOwnedByAnotherAccountError: 该 key 已被其它账号记入删除账本
            （fail-closed，见 `ledger.record_deletion` 的 Note）。
    """
    record = await _record(
        session,
        account_id=account_id,
        episode_key=corrected_episode_key,
        reason=DELETION_REASON_CORRECTION,
        deleted_by=deleted_by,
        derived_uuids=derived_uuids,
    )
    return _to_result(record)


async def _record(
    session: AsyncSession,
    *,
    account_id: AccountId,
    episode_key: EpisodeUuid | str,
    reason: str,
    deleted_by: str | None = None,
    derived_uuids: list[str] | None = None,
) -> DeletionRecord:
    """记一次删除，并把「该 key 已被别的账号记过」翻译成类型化失败。

    为什么需要这一层翻译（2026-09-30）：`record_deletion` 对三种失败抛的是同一个
    `MemoryDataError`——原因不在词表、账本状态不一致、跨账号守卫。而调用方（删除面
    路由）必须把跨账号守卫报成 404（越权与不存在逐字同文案），其余两种是形状或
    存储不变量问题，不能混为一谈。判据只能是异常类型，不能靠错误消息文本
    （见 `MemoryModuleError`）；靠文案匹配时改一个字的措辞就会让跨账号命中静默
    降级成 422「标识形状非法」。

    为什么落在这里：`delete_episode` / `correct_episode` 的 Raises 契约本来就声明了
    「该 key 已被其它账号记录删除」这一失败模式，把它类型化是用例的职责。
    分类依据是账本事实本身（该 `episode_key` 的那一行归属谁），不是异常文案；
    这也是本模块唯一读账本归属的地方——写入端仍然只有 `record_deletion` 一处。

    Raises:
        EpisodeKeyOwnedByAnotherAccountError: 账本里该 key 属于别的账号。
        MemoryDataError: 其余失败原样上抛（形状非法、原因不在词表、账本状态不一致）。
        其它异常同样原样上抛。
    """
    try:
        return await record_deletion(
            session,
            account_id=account_id,
            episode_key=episode_key,
            reason=reason,
            deleted_by=deleted_by,
            derived_uuids=derived_uuids,
        )
    except MemoryDataError as exc:
        if not await _owned_by_another_account(session, account_id=account_id, episode_key=episode_key):
            raise
        raise EpisodeKeyOwnedByAnotherAccountError(
            "该 episode_key 已被其它账号记录删除，本账号的删除不会生效",
            operation="record_deletion",
            detail="账本里该 episode_key 的归属账号不是请求账号（uuid 被跨账号共用）",
        ) from exc


async def _owned_by_another_account(
    session: AsyncSession,
    *,
    account_id: AccountId,
    episode_key: EpisodeUuid | str,
) -> bool:
    """账本里这条 key 是否属于别的账号——给 `record_deletion` 的失败定性用。

    标识形状非法时返回假：那种失败原样上抛，不冒充跨账号（否则一次载荷问题会被
    报成「这条记忆不是你的」）。`episode_key` 全局唯一，因此这里是一次索引命中。
    """
    try:
        key = to_episode_key(episode_key)
        account = to_account_id(account_id)
    except MemoryDataError:
        return False
    owner = (
        await session.execute(select(MemoryDeletionLedger.account_id).where(MemoryDeletionLedger.episode_key == key))
    ).scalar_one_or_none()
    return owner is not None and owner != account


def _to_result(record: DeletionRecord) -> DeletionResult:
    """把存储层结果转成面向调用方的结论。

    原因取 `record.reason`——幂等命中时它是账本里的原原因，不是本次请求传的原因
    （一条记忆先按 `correction` 撤下、之后又收到 `user_request` 删除请求时，账本里
    仍是 `correction`）。如实回报，避免审计与文案读到与账本不符的信息。
    """
    return DeletionResult(
        episode_key=record.episode_key,
        newly_deleted=record.outcome is DeletionOutcome.RECORDED,
        reason=record.reason,
    )


__all__ = [
    "DeletionResult",
    "correct_episode",
    "delete_episode",
]
