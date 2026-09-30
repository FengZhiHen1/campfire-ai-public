"""授权端口的错误类型与对外文案。

职责：定义 `AuthorizationError` 家族与两条对外文案——文案本身是契约的一部分。
边界：只放错误类型与文案；端口协议与注入在 `port.py`，实现归 `modules/profile`。
参考：docs/技术设计/technical-details/支持对象.md 第 5.1、5.3 节。
"""

from __future__ import annotations

#: 「对象不存在」与「对象不属于当前账号」的共用文案。
#:
#: 两种情形必须逐字相同：区分二者等于提供对象枚举通道——与登录限流
#: 「不区分账号不存在与密码错误」同一条纪律（支持对象 5.3）。
#: 做成常量而不是在两个分支各写一遍：只有一个字面量，就不存在两处文案漂移的可能。
OBJECT_NOT_ACCESSIBLE_MESSAGE = "支持对象不存在或不属于当前账号"

#: 归档对象上的写路径文案。它与越权文案刻意不同。
#:
#: 属主自己的对象，告知归档状态不泄露任何信息，且使用者需要知道原因才能去恢复
#: （支持对象 5.3）。因此这条不是「区分了不该区分的二者」，而是「本就该说明的事实」。
OBJECT_ARCHIVED_MESSAGE = "该对象已归档，不能新增记录"

#: 端口实现不可用时的文案。
#:
#: 装配处未注入实现（或实现自身不可用）时拒绝受限操作，不降级为放行
#: （支持对象 5.3 末行、技术栈设计第 5 节）。它描述的是基础设施状态，
#: 不泄露任何对象是否存在。
AUTHORIZER_UNAVAILABLE_MESSAGE = "授权判定不可用，已拒绝该操作"


class AuthorizationError(Exception):
    """授权判定失败：对象不可访问，或端口实现不可用。

    为什么抛错而不是返回 `bool`：返回布尔值时「忘了检查返回值」是一条静默失效路径；
    抛错让漏检不可能通过——`AC-22` 的判定不能靠调用方自觉（支持对象 5.1）。

    分派顺序（对实现者的要求）：本类型是家族基类，`ObjectArchivedError` 是它的子类。
    调用方一段 `except AuthorizationError` 即可收口全部越权；但若要按对外状态码区分，
    必须先判 `ObjectArchivedError`（HTTP 契约第 1 节的 409），再判本类型（404）。
    顺序写反会把「已归档」变成「不存在」，使用者就看不到该去恢复的原因。
    """


class ObjectArchivedError(AuthorizationError):
    """写路径命中一个已归档对象：属主自己的对象，但 lifecycle 不接受新增写入。

    单独成型是为了让调用方能把这一个情形与越权分开（文案与状态码都不同），
    同时仍是 :class:`AuthorizationError` 的子类——越权的宽收口不受影响。
    """


__all__ = [
    "AUTHORIZER_UNAVAILABLE_MESSAGE",
    "OBJECT_ARCHIVED_MESSAGE",
    "OBJECT_NOT_ACCESSIBLE_MESSAGE",
    "AuthorizationError",
    "ObjectArchivedError",
]
