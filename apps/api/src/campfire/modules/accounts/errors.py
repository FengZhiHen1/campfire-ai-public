"""账号模块的异常层次。

职责：定义 `modules/accounts` 的异常基类与邀请码相关的失败类型。
边界：只定义失败类型，不含重试策略，不复述凭据（见下方「模块说明」）。
参考：docs/项目结构设计.md 第 6 节；分层理由见 :class:`AccountsError`。
"""

# 归属：`modules/accounts`（见 docs/项目结构设计.md 第 6 节）。
#
# 模块说明（刻意不放进异常里的东西）：
#
# 邀请码本身不进异常消息、不进日志。它是一次性准入凭据，把它写进异常文本会让它
# 随日志扩散；而`AC-15` 只要求「明确拒绝」，不要求把被拒的值回报出来。
# 这条与 `core/pending_write` 对 `last_error` 的纪律同源（不复述凭据）。

from __future__ import annotations


class AccountsError(Exception):
    """账号模块所有异常的基类。

    存在的意义是让上层能用一次 `except` 收口本模块的全部失败，
    而不必逐个列举内部实现可能抛出的类型。

    为什么单独一份层次：

    调用方（CLI、认证端点）需要能一句 `except AccountsError` 收口，而不必知道底层是
    SQLAlchemy、Redis 还是身份服务的 Python SDK。分叉依据是「调用方该不该重试」，
    不是「错误来自哪个依赖」——这一点与 `core/pending_write`、
    `modules/memory` 的既有分层同一种思路（邻近一致性）：

    - 调用方给错了（码格式不对、状态不匹配）→ 不该重试，属明确拒绝；
    - 依赖不可用（core 连不上）→ 可重试，且必须 fail-closed（认证文档第 2 节）。
    """


class InviteCodeError(AccountsError):
    """邀请码相关失败的基类（发放、占用、释放、撤销、校验）。"""


class InviteCodeFormatError(InviteCodeError):
    """调用方给的邀请码形状不合法（长度不对、含字母表外字符）。

    这是`CORE-04`（数据边界运行时解析）的拒绝分支：不合法输入必须在边界处变成
    显式状态，而不是拿去拼 SQL 后由数据库报一个看不懂的错。

    不携带被拒的值：见模块说明「刻意不放进异常里的东西」。
    """

    def __init__(self, reason: str) -> None:
        """记录形状不合法的原因（不含邀请码本身）。"""
        self.reason = reason
        super().__init__(f"邀请码形状不合法：{reason}")


class InviteCodeRejectedError(InviteCodeError):
    """邀请码未被接受：不存在、已过期、已被使用或已被撤销。

    四种情形合并为一个类型是有意的，不是省事：`AC-15` 与认证文档第 9 节
    要求「明确拒绝」，而把四者分成四个可区分的错误，会让限流之外的调用方逐字
    区分出「这个码存在但过期」与「这个码不存在」——那本身就是账号枚举渠道
    （第 5 节「不区分『账号不存在』与『密码错误』」同一条纪律）。

    代价（如实写明）：运维排查「用户说码用不了」时，不能只看异常类型；须走
    `list_invite_codes` 查该码的实际状态。这是有意用不便换取不可枚举。
    """


class InviteCodeStateError(InviteCodeError):
    """状态推进的前提不成立（如释放一个已绑定账号的码、撤销一个非签发的码）。

    与 :class:`InviteCodeRejectedError` 的区别：这个不是对外拒绝，而是内部
    调用顺序错误——它意味着编排逻辑与存储层的不变量不一致，必须显式暴露，
    不得静默当作「操作成功」（`CORE-07`：无静默兜底）。
    """

    def __init__(self, code_state: str, operation: str) -> None:
        """记录当前状态与试图执行的操作（不含邀请码本身）。"""
        self.code_state = code_state
        self.operation = operation
        super().__init__(f"邀请码当前状态为 {code_state!r}，不能执行 {operation}")


class InviteCodeNotFoundError(InviteCodeError):
    """邀请码不存在（用于运维路径：释放、撤销、绑定）。

    与 :class:`InviteCodeRejectedError` 分开：这个只出现在运营 CLI 与编排内部，
    不出现在面向使用者的拒绝路径上——运维需要知道「这个码我库里根本没有」，
    而使用者不需要知道任何关于存在性的细节。
    """

    def __init__(self, operation: str) -> None:
        """记录试图执行的操作（不含邀请码本身）。"""
        self.operation = operation
        super().__init__(f"邀请码不存在，无法执行 {operation}")


__all__ = [
    # 基类
    "AccountsError",
    "InviteCodeError",
    # 形状
    "InviteCodeFormatError",
    # 对外拒绝
    "InviteCodeRejectedError",
    # 内部状态与查找
    "InviteCodeNotFoundError",
    "InviteCodeStateError",
]
