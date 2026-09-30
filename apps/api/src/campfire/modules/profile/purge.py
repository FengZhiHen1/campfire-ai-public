"""账号注销时清除该账号的档案与支持对象（实现 `core/auth` 的 purger 端口）。

职责：真删该账号的支持对象（含已归档）、会话-对象绑定与全部档案条目。
边界：端口定义在 `core/auth/deletion.py`——`core/*` 不得依赖 `modules/*`，
因此实现放这边、由装配处注入。注销的编排与顺序不在此。
参考：docs/技术设计/technical-details/支持对象.md 第 7 节；
docs/技术设计/technical-details/认证与账号.md 第 8 节。
"""

from __future__ import annotations

import logging

from campfire.core.auth.deletion import PurgeOutcome
from campfire.core.config import Settings
from campfire.core.db import session_scope
from campfire.modules.profile import repository as repo

logger = logging.getLogger(__name__)


class ProfileAccountPurger:
    """清除某账号的档案数据：档案条目 + 会话绑定 + 支持对象（三者都真删）。

    实现 :class:`campfire.core.auth.deletion.AccountDataPurger`（结构性满足，
    不显式继承——Protocol 的用法）。

    为什么归档不是注销的豁免

    归档是生命周期状态（支持对象第 4 节：对象仍在用与否），而注销是
    「这条数据不该再存在」。`AC-24` 要求「其档案与待处理写入记录不再存在」，
    因此已归档的对象同样真删——`支持对象第 7 节` 明文写了这一条。

    删除顺序是硬约束

    档案条目对 `campfire_support_object.id` 声明了外键，因此必须先删条目、
    再删对象（第 7 节：若档案条目对对象声明了外键，须先删条目再删对象）。
    顺序反了会被外键拒绝，而那是一次部分完成的注销失败——操作者要重试，
    但已经删掉的部分不会回来。

    三项都必须在墓碑写入之后执行

    编排（`core/auth/deletion.delete_account`）已保证这一点：领域清除是第 4 步、
    墓碑是第 1 步（第 5 步是删身份用户）。purger 自身不检查墓碑——那是编排的职责，
    重复检查会让「顺序」这条不变量有两处判据。

    幂等

    账号没有对象、没有条目时都正常返回「无数据可清」，不报错——重试注销是正常路径
    （第一次可能在后续步骤失败）。依据：`DELETE ... WHERE` 命中 0 行不报错。

    `name` 属性（`"profile"`）：注销编排的步骤名从它取（如 `领域清除（profile）`），
    与 :class:`PurgeOutcome` 的 `name` 同源——多个清除者并存时，操作者据此分辨
    「哪个领域已清过」。
    """

    #: 清除者的领域名（编排步骤名与结果汇总共用，勿与类名耦合）。
    name = "profile"

    def __init__(self, settings: Settings) -> None:
        """记录配置。

        Args:
            settings: 应用配置（数据库连接的唯一来源）。
        """
        self._settings = settings

    async def purge_account(self, account_id: str) -> PurgeOutcome:
        """真删该账号的档案条目、会话绑定与支持对象。

        三者在同一事务内完成：注销的语义是「内容真删」，留下「条目删了但对象还在」
        的中间态会让下一次重试面对一个自称属于已注销账号的对象。

        Args:
            account_id: 账号标识。

        Returns:
            :class:`PurgeOutcome`，说明三类各删了多少行。

        Raises:
            Exception: 数据库操作失败。不吞——静默失败会让「已删除」成为谎话
                （见端口的实现者契约）。
        """
        async with session_scope(self._settings) as session:
            # 顺序不可换：条目引用对象，先删条目（支持对象第 7 节）。
            items_deleted = await repo.delete_items_for_account(session, account_id=account_id)
            bindings_deleted = await repo.delete_session_bindings_for_account(session, account_id=account_id)
            objects_deleted = await repo.delete_support_objects_for_account(session, account_id=account_id)

        detail = f"删除档案条目 {items_deleted} 条；会话绑定 {bindings_deleted} 条；支持对象 {objects_deleted} 个"
        logger.info("档案清除完成：标识=%s %s", account_id, detail)
        return PurgeOutcome(name=self.name, detail=detail)


__all__ = [
    "ProfileAccountPurger",
]
