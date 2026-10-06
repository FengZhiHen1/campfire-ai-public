"""账号注销时清除该账号的引导状态行（实现 `core/auth` 的 purger 端口）。

职责：真删 `campfire_onboarding` 里该账号的状态行（设计真源：[认证与账号] 第 8 节
处置顺序第 8 步，`RQ-ACC-09`）。
边界：端口定义在 `core/auth/deletion.py`——`core/*` 不得依赖 `modules/*`，
因此实现放这边、由装配处（CLI）注入。注销的编排与顺序不在此。
参考：docs/技术设计/technical-details/认证与账号.md 第 8 节；
docs/技术设计/decisions/账号注销与墓碑.md。
"""

from __future__ import annotations

import logging

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.core.auth.deletion import PurgeOutcome
from campfire.core.config import Settings
from campfire.core.db import session_scope
from campfire.modules.accounts.models import CampfireOnboarding
from campfire.modules.accounts.session_repository import validate_account_id

logger = logging.getLogger(__name__)


class OnboardingAccountPurger:
    """清除某账号的引导状态行（第 8 步第 8 项，`RQ-ACC-09`）。

    实现 :class:`campfire.core.auth.deletion.AccountDataPurger`（结构性满足，
    不显式继承——Protocol 的用法）。

    为什么单立一个清除者，而不是并进 :class:`~campfire.modules.accounts.sessions.SessionAccountPurger`

    判据是端口 docstring 对 `name` 的规定：「领域名，如 `memory`」、
    「编排步骤名与失败点名共用……多个清除者并存时，操作者据此分辨『哪个领域已清过、
    哪个失败』」。引导状态与会话归属是**两件不同的业务事实**：

    - 会话归属行（`campfire_session`）回答「这个会话属于谁」——它是**越权判定的真源**，
      删掉它是 fail-closed（残留会让已注销账号的会话仍通过归属判定）；
    - 引导状态行（`campfire_onboarding`）回答「这位使用者是否已被引导过」——
      它是**一次性引导的判定真源**，与会话的存在性无关（模型 docstring 写明
      「判定不推导」：不从档案或会话推断）。

    两者既不同源、也不同失效原因，只是恰好都以 `account_id` 为键。并成一个清除者会
    让**失败点名说谎**：引导表因故删除失败时，操作者看到的是「清除 session-owner 失败」，
    而他会去查会话归属表——那张表可能已经清干净了。分开之后失败点名逐字对应领域
    （`清除 onboarding`），操作者的排查方向与重试范围都是确定的。

    代价如实写明：多一个 purger 实例与一次 `session_scope`（注销是低频运维操作，
    不值得为省它把两个领域的失败点混成一个）。

    为什么 `name` 取 `"onboarding"` 而不是 `"accounts"`：`"accounts"` 是模块名，
    会把两个领域重新合成一个失败点——这正是上面要避免的。取 `"onboarding"` 与
    `"memory"` / `"profile"` 同一种粒度（都是「该账号在某个领域的全部数据」）。

    为什么删行而不是置一个「已注销」状态

    第 8 步的原文是「删除……状态行」，且 `RQ-ACC-09` 的语义是「随内容一并真删」。
    这张表没有软删除列（`account_id` 主键 / `state` / `updated_at`），
    也没有任何读路径按「已注销」解释某个取值——约束 `state` 的词表是
    `in_progress | completed | skipped` 三值，加第四值要先改设计。
    留着行还会让「从未引导」与「已注销」在该表的语义里变得不可区分。

    幂等

    账号没有引导行时正常返回「删除引导状态行 0 条」，不报错——重试注销是正常路径
    （见 `core/auth/deletion` 的幂等说明）。依据：`DELETE ... WHERE` 命中 0 行不报错。

    `name` 属性（`"onboarding"`）：注销编排的步骤名从它取（如
    `领域清除（onboarding）`），与 :class:`PurgeOutcome` 的 `name` 同源。
    """

    #: 清除者的领域名（编排步骤名与结果汇总共用，勿与类名耦合）。
    name = "onboarding"

    def __init__(self, settings: Settings) -> None:
        """记录配置。

        Args:
            settings: 应用配置（数据库连接的唯一来源）。
        """
        self._settings = settings

    async def purge_account(self, account_id: str) -> PurgeOutcome:
        """真删该账号的引导状态行。

        Args:
            account_id: 账号标识（引导状态表的唯一判定键）。

        Returns:
            :class:`PurgeOutcome`，说明删了多少行。

        Raises:
            Exception: 数据库操作失败。不吞——静默失败会让「已删除」成为一句谎话
                （见端口的实现者契约）。
            SessionQueryError: 账号标识形状不合法（判据与仓储层同源）。
        """
        async with session_scope(self._settings) as session:
            deleted = await delete_onboarding_state(session, account_id=account_id)

        detail = f"删除引导状态行 {deleted} 条"
        logger.info("引导状态清除完成：标识=%s %s", account_id, detail)
        return PurgeOutcome(name=self.name, detail=detail)


async def delete_onboarding_state(session: AsyncSession, *, account_id: str) -> int:
    """删除某账号的引导状态行，返回条数。

    单独抽出成函数（而不是内联在 purger 里）以便测试直接调用，也让「引导状态清除」
    这一动作只有一个实现点——与 `modules/memory/purge.delete_ledger_rows` 同法。

    复用 `session_repository.validate_account_id` 而不是本文件再写一份形状校验：
    该函数是 `modules/accounts` 里账号标识校验的实现点（会话归属清除也用它），
    第二份定义会漂移。它同时让「形状不合法」在**进 SQL 之前**变成显式领域错误，
    而不是一个驱动层异常。

    Raises:
        SessionQueryError: 账号标识非字符串、为空，或超过 `MAX_ACCOUNT_ID_LENGTH`。
    """
    normalized = validate_account_id(account_id)
    result = await session.execute(delete(CampfireOnboarding).where(CampfireOnboarding.account_id == normalized))
    # `rowcount` 在 `CursorResult` 上；`session.execute` 的静态类型是 `Result`
    # （mypy 实测抓到），故显式取属性并给安全默认值。
    return int(getattr(result, "rowcount", 0) or 0)


__all__ = [
    "OnboardingAccountPurger",
    "delete_onboarding_state",
]
