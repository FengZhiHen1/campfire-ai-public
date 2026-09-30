"""授权端口：两个具名判定函数与它们的注入点。

职责：声明 `Authorizer` 协议、承载装配处注入的实现，并对外提供
`require_owned` / `require_writable` 两个可调用入口。
边界：不依赖任何业务模块——实现由装配处注入（见 `set_authorizer`）。
参考：docs/技术设计/technical-details/支持对象.md 第 5.1、5.2 节。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from campfire.core.authz.errors import AUTHORIZER_UNAVAILABLE_MESSAGE, AuthorizationError

# 端口为什么在 core/authz、实现为什么在 modules/profile（支持对象 5.1、5.2）：
#
# Worker 领取 `profile_item` 时也要做这条判定，而 Worker 的白名单只放行
# `core/*` 与 `modules/{profile,memory}`、禁止回查业务用例（写入路径第 6 节）。
# 若端口定义在 `modules/profile`，Worker 就得 import 业务用例——那是白名单禁止的。
# 因此协议与错误类型落在 `core/authz`，实现由装配处注入。
#
# 为什么是两个具名函数而不是一个带布尔参数（支持对象 5.1）：
# 布尔参数在调用点读不出语义（`require(x, y, False)` 看不出是不是「允许归档对象」），
# 而读写两类调用点都要用，写错方向的后果不对称——把归档对象当可写会污染档案，
# 把可写对象当只读只是行为不变。
#
# 为什么这两个函数是 async：实现要查支持对象表（属主与归档状态都在库里）。

#: 当前注入的实现；`None` 表示装配处尚未注入。
_authorizer: Authorizer | None = None


@runtime_checkable
class Authorizer(Protocol):
    """授权判定的实现契约（一期只有「属主即允许」一个实现）。

    实现者的契约：

    - `require_owned`：对象存在且属主为 `account_id` 则正常返回，否则抛
      :class:`~campfire.core.authz.errors.AuthorizationError`。
    - `require_writable`：在 `require_owned` 之上再要求对象未归档；已归档时抛
      :class:`~campfire.core.authz.errors.ObjectArchivedError`。
    - 两种失败都必须抛错，不得返回布尔值——见 `errors` 模块说明。
    - 对象不存在与不属于当前账号必须抛逐字相同文案的同一个异常类型
      （支持对象 5.3）。本协议无法机械校验这一点，由实现侧的测试断言钉住。
    - 不得把基础设施故障降级为放行：库不可达时同样抛
      :class:`AuthorizationError`（fail-closed，见 `errors` 模块说明）。
    """

    async def require_owned(self, account_id: object, support_object_id: object) -> None:
        """读路径：对象存在且属主为 `account_id` 则返回，否则抛异常。

        Args:
            account_id: 当前账号（来自登录态，不接受调用方传入的任意值）。
            support_object_id: 被判定对象的标识。类型是 `object`：这是运行时数据
                边界（CORE-04），实现方负责解析并拒绝畸形输入。

        Raises:
            AuthorizationError: 对象不存在、不属于该账号，或判定不可用。
        """
        ...  # pragma: no cover —— Protocol 抽象体，合法空体

    async def require_writable(self, account_id: object, support_object_id: object) -> None:
        """写路径：在 `require_owned` 之上再要求对象未归档。

        Raises:
            ObjectArchivedError: 对象属于该账号但已归档。文案与越权不同
                （支持对象 5.3）：属主自己的对象，告知归档状态不泄露信息。
            AuthorizationError: 对象不存在或不属于该账号（文案与前者相同）。
        """
        ...  # pragma: no cover —— Protocol 抽象体，合法空体


def set_authorizer(authorizer: Authorizer | None) -> None:
    """设置（或清除）授权实现。只在装配处调用。

    与 `core/jobs.set_dispatch_hook` 同一种做法：注入而非 import，
    依赖方向保持单向（`core/*` 不 import `modules/*`）。

    传 `None` 可清除——测试据此隔离彼此，避免实现跨用例泄漏。
    清除后不是「放行」而是「拒绝」：见 :func:`require_owned`。

    Args:
        authorizer: 实现 :class:`Authorizer` 的对象；`None` 表示清除。
    """
    global _authorizer
    _authorizer = authorizer


def get_authorizer() -> Authorizer | None:
    """返回当前注入的实现（诊断与测试用）；未注入时为 `None`。

    存在的理由：调用方（含测试）需要区分「没注入」与「判定失败」这两件事，
    而后者只能靠异常。没有这个读取入口时，排查只能去猜装配是否真的跑了。
    """
    return _authorizer


def _require_injected(operation: str) -> Authorizer:
    """取出实现；未注入时显式失败。

    未注入即拒绝（fail-closed）：授权不可用时不得让受限操作通过
    （支持对象 5.3 末行）。这里不为便利返回一个「一律放行」的实现——
    那会把一次装配遗漏变成静默的越权。

    Raises:
        AuthorizationError: 装配处未注入实现。
    """
    if _authorizer is None:
        raise AuthorizationError(f"{AUTHORIZER_UNAVAILABLE_MESSAGE}（{operation} 无实现）")
    return _authorizer


async def require_owned(account_id: object, support_object_id: object) -> None:
    """读路径判定：对象存在且属于当前账号，否则抛 `AuthorizationError`。

    这是读调用点（`read_profile_summary`、`read_profile_items`、
    `emergency_context`、档案面的纠正与删除）唯一该用的入口。

    Raises:
        AuthorizationError: 对象不存在、不属于当前账号，或端口实现不可用。
            三者对外都是明确失败；前两者文案逐字相同，调用方无法据此枚举对象。
    """
    await _require_injected("require_owned").require_owned(account_id, support_object_id)


async def require_writable(account_id: object, support_object_id: object) -> None:
    """写路径判定：`require_owned` 之上再要求对象未归档。

    这是写调用点（`propose_profile_item`、Worker 领取 `profile_item`、
    咨询面建立会话绑定）唯一该用的入口。

    Raises:
        ObjectArchivedError: 对象属于该账号但已归档（文案区分于越权）。
        AuthorizationError: 对象不存在、不属于该账号，或端口实现不可用。
    """
    await _require_injected("require_writable").require_writable(account_id, support_object_id)


__all__ = [
    "Authorizer",
    "get_authorizer",
    "require_owned",
    "require_writable",
    "set_authorizer",
]
