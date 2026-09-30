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


class OnboardingTriggerError(AccountsError):
    """一次性引导的触发判定无法给出结论。

    出现它的两种情形都不是「用户做错了什么」：

    - 状态取值漂移：引导状态表的 `state` 有 CHECK 约束，读到词表外的值只可能来自
      表形状与设计的漂移。此时「注入还是不注入」没有正确答案——两个方向都会掩盖漂移；
    - 调用方错误：缺 `account_id`。空值在等值查询里必然查不到行，而「查不到行」
      的语义是「从未引导过」，于是调用方错误会被伪装成一个合法的业务判定。

    单独一个类型而不是复用 :class:`InviteCodeStateError`：后者的语义是「邀请码状态机
    的前提不成立」，与引导状态无关；混用会让排查方向偏到邀请码上。它不是
    :class:`InviteCodeError` 的子类，理由相同——它不涉及任何邀请码。
    """


class SessionError(AccountsError):
    """会话归属相关失败的基类（登记、越权判定、列表与水合）。"""


class SessionNotFoundError(SessionError):
    """会话不可访问：不存在，或存在但不属于当前账号。

    两种情形合并为一个类型、一条文案，且只有一条文案（与
    `core/authz` 的 `OBJECT_NOT_ACCESSIBLE_MESSAGE` 同一条纪律）：
    区分「这个会话不存在」与「这个会话存在但不是你的」，等于给出一条会话枚举
    通道——攻击者据此可以确认某个 `session_id` 是否真实存在。因此本类型不携带
    任何能分辨二者的字段，文案是类常量而不是常量池里的可选项（只有一个字面量，
    就不存在两处文案漂移的可能）。

    调用方（面层）把它翻译成 404，而不是 403：越权与不存在必须给出同一个响应
    （HTTP 契约第 3.3 节：水合失败不得暴露会话是否存在）。
    """

    #: 对外文案。不存在与属主不符共用它——见上方说明。
    MESSAGE = "会话不存在或不属于当前账号"

    def __init__(self) -> None:
        """不携带会话标识：异常会经日志扩散，而 `session_id` 是越权探测的目标。"""
        super().__init__(self.MESSAGE)


class SessionRegistrationError(SessionError):
    """登记会话时前提不成立。

    目前只有一种情形：该 `session_id` 已登记在另一个账号名下。属主是不可变的
    ——允许改属主等于允许把别人的会话据为己有（整个归属表的意义就此消失）。
    因此重复登记同属主是幂等的无操作，换属主是显式错误，不是「更新成功」。
    """

    def __init__(self) -> None:
        """不携带会话标识与账号标识：两者都是可枚举的敏感值（同 :class:`SessionNotFoundError`）。"""
        super().__init__("该会话已登记在另一个账号名下，属主不可变更")


class SessionQueryError(SessionError):
    """查询参数不合法（游标无法解析、分页上限越界）。

    这是 `CORE-04`（数据边界运行时解析）的拒绝分支：不合法输入必须在边界处变成
    显式状态，而不是被当成「没有下一页」或「从头开始」静默兜底——那两种兜底都会
    让调用方拿到貌似正常的结果（`CORE-07`：无静默兜底）。
    """

    def __init__(self, reason: str) -> None:
        """记录不合法的原因（不回显原始游标文本——它可能被伪造且无诊断价值）。"""
        self.reason = reason
        super().__init__(f"会话查询参数不合法：{reason}")

class OnboardingWriteError(AccountsError):
    """引导状态的写入无法完成（形状不合法、状态漂移，或存储失败）。

    与 :class:`OnboardingTriggerError` 分开：那个是**判定**给不出结论（读路径），
    这个是**写入**没能成立（写路径）。两者的调用方与补救通道都不同——
    判定失败时本次会话不注入引导（可重试），写入失败时工具必须明确失败而不是回执
    `completed`，因为回执了会让模型以为引导已收束、而下次会话又会重新注入
    （`finish_onboarding` 契约第 5 节末行：UI 跳过入口仍是补救通道）。

    它不是 :class:`InviteCodeError` 的子类：与邀请码无关。
    """

__all__ = [
    # 基类
    "AccountsError",
    "InviteCodeError",
    "SessionError",
    # 形状
    "InviteCodeFormatError",
    # 对外拒绝
    "InviteCodeRejectedError",
    "SessionNotFoundError",
    "SessionRegistrationError",
    # 查询参数
    "SessionQueryError",
    # 内部状态与查找
    "InviteCodeNotFoundError",
    "InviteCodeStateError",
    # 引导状态
    "OnboardingTriggerError",
    "OnboardingWriteError",
]
