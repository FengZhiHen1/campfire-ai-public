"""授权端口的一期实现：属主即允许。

职责：实现 `core/authz` 的 `Authorizer` 协议——查支持对象表，判定属主与归档状态。
边界：本模块是实现，端口的协议与错误类型在 `core/authz`；由装配处注入。
参考：docs/技术设计/technical-details/支持对象.md 第 5.1、5.3 节。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from campfire.core.authz import (
    OBJECT_ARCHIVED_MESSAGE,
    OBJECT_NOT_ACCESSIBLE_MESSAGE,
    AuthorizationError,
    ObjectArchivedError,
)
from campfire.core.config import Settings
from campfire.core.db import session_scope
from campfire.modules.profile.errors import ProfileDataError
from campfire.modules.profile.models import SupportObject
from campfire.modules.profile.repository import get_support_object

# 为什么实现在 modules/profile、由装配处注入（支持对象 5.1）：
# 判定要读 `campfire_support_object`（属主与归档状态），而 `core/*` 不得依赖
# `modules/*`。因此协议与错误类型在 `core/authz`、实现在此、由 main/worker/cli 注入
# ——与注销 purger 同一模式。二期 `spaces` 实现同一协议即可，调用点不变。
#
# 为什么实现自开会话而不是由调用方传入：
# 端口的两个函数只收 `(account_id, support_object_id)`（支持对象 5.1 的形状），
# 而注入发生在装配处、只发生一次——注入进来的实例不能绑定某个请求的会话。
# 因此它按调用自开事务（与 `modules/memory/purge.MemoryAccountPurger` 同一做法）。
# 代价如实写明：判定与随后的写入不在同一事务内，因此「判定通过」到「写入」之间
# 存在一个窗口。该窗口是设计本身接受的（写入路径第 6 节要求「授权在领取时重新判定
# 一次」，而不是要求判定与写入原子）；真正的写入仍由存储层的对象外键与
# `pending_write.support_object_id` 的 NOT NULL 约束兜底。


class OwnerAuthorizer:
    """一期唯一的授权实现：对象属主即允许读写；写路径额外要求未归档。

    实现 :class:`campfire.core.authz.Authorizer`（结构性满足，不显式继承
    ——Protocol 的用法）。

    越权文案必须逐字相同（支持对象 5.3）

    「对象不存在」与「对象不属于当前账号」抛同一个类型、同一份文案常量。
    区分二者等于提供对象枚举通道——与登录限流「不区分账号不存在与密码错误」
    同一条纪律。测试逐字断言（`str(e1) == str(e2)`），消融：让文案区分二者，
    测试必须失败。

    归档文案区分（5.3）

    写路径命中已归档对象时抛 :class:`ObjectArchivedError`，文案是
    「该对象已归档，不能新增记录」。它不是「区分了不该区分的二者」：
    属主自己的对象，告知归档状态不泄露任何信息，且使用者需要知道原因才能去恢复。

    判定不可用时拒绝，不降级（5.3 末行）

    本实现不捕获数据库异常转成「放行」：库不可达时异常向上传播，调用方
    收到的是明确失败（fail-closed）。之所以不把驱动异常包成
    `AuthorizationError`，是因为那会掩盖真实的基础设施故障类型——
    而「拒绝受限操作」这一结果无论包不包成都成立（调用方拿到的是异常而不是放行）。
    """

    def __init__(self, settings: Settings) -> None:
        """记录配置。

        Args:
            settings: 应用配置（数据库连接的唯一来源）。
        """
        self._settings = settings

    async def require_owned(self, account_id: object, support_object_id: object) -> None:
        """读路径：对象存在且属主为 `account_id` 则返回，否则抛异常。

        Raises:
            AuthorizationError: 对象不存在、不属于该账号，或对象标识本身不合法。
                三种情形文案逐字相同——标识不合法同样不得与「不属于你」区分开，
                否则畸形标识会变成一条探测通道。
        """
        async with session_scope(self._settings) as session:
            record = await _load(session, support_object_id)
        if record is None or record.account_id != _normalize_account(account_id):
            raise AuthorizationError(OBJECT_NOT_ACCESSIBLE_MESSAGE)

    async def require_writable(self, account_id: object, support_object_id: object) -> None:
        """写路径：判定属主与未归档，两者在一次查询内完成。

        为什么一次查询而不是先调 `require_owned` 再查归档：两次查询之间对象可能被
        归档，于是「读判定通过」与「写判定基于旧状态」会给出互相矛盾的结论；
        且两次查询必然多一次往返，而这是写路径的热点。

        Raises:
            ObjectArchivedError: 对象属于该账号但已归档（文案区分于越权）。
            AuthorizationError: 对象不存在或不属于该账号（文案与前者相同）。
        """
        async with session_scope(self._settings) as session:
            record = await _load(session, support_object_id)

        if record is None or record.account_id != _normalize_account(account_id):
            # 越权与不存在在此合并（文案逐字相同）。
            raise AuthorizationError(OBJECT_NOT_ACCESSIBLE_MESSAGE)
        # 归档判定只在确认属主之后做：若先判归档，别人的归档对象会得到
        # 「已归档」文案，那正是一条枚举通道（5.3 的顺序要求）。
        if record.archived_at is not None:
            raise ObjectArchivedError(OBJECT_ARCHIVED_MESSAGE)


async def _load(session: AsyncSession, support_object_id: object) -> SupportObject | None:
    """按标识取对象；畸形标识归入「不可访问」。

    `get_support_object` 对非法 UUID 抛 `ProfileDataError`。这里把它转成
    `None`（即「查不到」）：调用方据此得到与「不属于你」相同的文案。
    不把它转成「参数错误」是因为那会让调用方得以区分
    「这个标识存在但不是你的」与「这个标识根本不是合法标识」——
    后者对攻击者反而是有价值的信息（前者说明碰巧猜中了一个真实标识）。

    Returns:
        `SupportObject` 或 `None`（不存在、或标识不合法）。
    """
    try:
        return await get_support_object(session, support_object_id=support_object_id)
    except ProfileDataError:
        return None


def _normalize_account(account_id: object) -> str:
    """把账号标识收窄成字符串；非法输入归为不可能匹配的值。

    不抛异常：账号来自登录态，理论上总是合法；但若传入 `None` 或非字符串，
    正确的行为是「判定不通过」（fail-closed），而不是让一个类型错误穿透成
    「对象不存在」。空串不可能与真实的 `account_id` 相等（它非空），
    因此后续比较会自然失败。
    """
    return account_id if isinstance(account_id, str) else ""


__all__ = [
    "OwnerAuthorizer",
]
