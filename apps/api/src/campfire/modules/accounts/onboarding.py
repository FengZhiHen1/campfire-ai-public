"""一次性引导的触发判定：查引导状态表，决定本次会话是否注入 onboarding skill。

职责：引导状态表的读取与触发判定（无行或 `in_progress` → 注入；`completed` / `skipped` → 不注入）。
边界：只回答「要不要注入」，不创建会话、不写状态、不判断会话类型（应急会话永不触发由调用方保证）。
参考：docs/技术设计/technical-details/技能设计.md 第 4 节；认证与账号第 8 节（表形状）；
      docs/技术设计/面/consult/skills/onboarding.md 第 2 节。
"""

from __future__ import annotations

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.modules.accounts.errors import OnboardingTriggerError

# 状态词表与表名从表模型（`models`）再导出，本模块不声明第二份定义。两份定义并存时，
# 漂移既不被存储层 CHECK 拦住、也不被任何检查发现：模型侧加一个状态而判定模块没跟进时，
# 该账号每次建会话都被判成「词表外状态」；反向漂移则撞 CHECK。
# 与设计文档取值（认证与账号第 8 节的三值）的一致由 `test_skills_content.py` 的字面量断言守门。
#
# 本模块仍不声明 SQLAlchemy 模型：读取走带绑定参数的显式 SQL，`core/db.metadata` 里没有
# 本表的第二份定义（项目结构设计第 10 节）；表名取模型的 `__tablename__`，不再写字面量。
from campfire.modules.accounts.models import (
    ONBOARDING_COMPLETED,
    ONBOARDING_IN_PROGRESS,
    ONBOARDING_SKIPPED,
    ONBOARDING_STATES,
    CampfireOnboarding,
)

#: 引导状态表的表名。表形状由认证与账号第 8 节拥有（`account_id` 主键 / `state` / `updated_at`）。
ONBOARDING_TABLE_NAME: str = CampfireOnboarding.__tablename__

#: 已终结的状态：引导不再注入。「终结」的判据是用户侧已有明确结论，
#: 不是「流程走过一遍」——模型漏调 `finish_onboarding` 时状态仍是 `in_progress`，
#: 下次会话重新注入，这正是该设计选择的修复通道。
TERMINAL_STATES: frozenset[str] = frozenset({ONBOARDING_COMPLETED, ONBOARDING_SKIPPED})


def should_inject_onboarding(state: str | None) -> bool:
    """依据引导状态决定本次会话是否注入 onboarding skill。

    纯函数：状态到判定的映射集中在此处，不与读表、会话创建混在一起（可单独回归）。

    为什么「无行」按注入处理：无行意味着该账号从未触发过引导。把它当作「已完成」
    会把首次引导整批跳过，而使用者此后没有任何入口回到引导——静默丢功能，不可恢复。
    反过来，误注入一次的代价是重复一段可跳过的引导（契约已写明「漏写的最坏后果是重复注入，
    不损失数据」）。两个方向的代价不对称，故无行取注入。

    为什么词表外的状态显式报错：`state` 有 CHECK 约束，词表外的值只可能来自表形状
    与设计漂移。此时「注入还是不注入」没有正确答案——两个方向都会掩盖漂移（注入会让人
    以为状态没问题，不注入会让人以为引导已完成）。因此不猜，抛出明确错误（`CORE-07`：
    无静默兜底）。

    Args:
        state: 该账号在引导状态表中的 `state`；无行传 `None`。

    Returns:
        需要注入 onboarding skill 时为 `True`。

    Raises:
        OnboardingTriggerError: `state` 不在状态词表内（表形状与设计漂移）。
    """
    if state is None:
        return True
    if state not in ONBOARDING_STATES:
        raise OnboardingTriggerError(
            f"引导状态 {state!r} 不在词表内（{sorted(ONBOARDING_STATES)}）——"
            "表形状与设计漂移，无法判定本次会话是否注入引导"
        )
    return state not in TERMINAL_STATES


async def read_onboarding_state(session: AsyncSession, *, account_id: str) -> str | None:
    """读取某账号的引导状态；无行返回 `None`。

    用绑定参数而不是字符串拼接：`account_id` 来自登录态，经本函数进入 SQL 文本，
    拼接会让一个可控值变成语句片段。绑定参数让它在协议层就是值。

    Args:
        session: 关系库会话（只读，不提交）。
        account_id: 账号标识（键取登录态）。

    Returns:
        该账号的 `state`；表中没有该账号的行时返回 `None`。

    Raises:
        OnboardingTriggerError: `account_id` 为空——属调用方错误，显式拒绝而不是
            静默查空。空值在等值查询里必然查不到行，而查不到行的语义是「从未引导」，
            于是调用方错误会被伪装成一个合法的业务判定。
    """
    if not account_id:
        raise OnboardingTriggerError("账号标识不得为空——无法判定引导状态")

    statement = sql_text(f"SELECT state FROM {ONBOARDING_TABLE_NAME} WHERE account_id = :account_id")
    row = (await session.execute(statement, {"account_id": account_id})).first()
    return None if row is None else str(row[0])


async def onboarding_pending(session: AsyncSession, *, account_id: str) -> bool:
    """引导是否待进行——会话创建时调用的一次性判定入口。

    调用方契约（不能省）：本函数只回答状态表一侧的问题。调用方必须先判定本次是
    日常会话——应急会话永不触发引导（时延硬约束），且该判断不由本函数承担，
    因为状态表里没有任何字段能表达会话类型。

    「首次」不从这里推导：是否注入只查本表，不从档案或会话的存在性推断——
    档案为空与「未经引导」是两件事，跳过对象创建的用户会因此被误判（认证与账号第 8 节
    「判定不推导」）。

    Args:
        session: 关系库会话（只读，不提交）。
        account_id: 账号标识（键取登录态）。

    Returns:
        需要注入 onboarding skill 时为 `True`。

    Raises:
        OnboardingTriggerError: `account_id` 为空，或状态取值漂移出词表。
    """
    # 在公开入口自身校验一次入参，而不是只依赖被调函数的守卫：本函数是会话创建时的
    # 调用点，空标识在这里被拒才能真正拦在请求路径上（`CORE-04`：数据边界运行时解析）。
    if not account_id:
        raise OnboardingTriggerError("账号标识不得为空——无法判定引导状态")
    state = await read_onboarding_state(session, account_id=account_id)
    return should_inject_onboarding(state)


__all__ = [
    # 常量
    "ONBOARDING_STATES",
    "ONBOARDING_TABLE_NAME",
    "ONBOARDING_COMPLETED",
    "ONBOARDING_IN_PROGRESS",
    "ONBOARDING_SKIPPED",
    "TERMINAL_STATES",
    # 判定
    "onboarding_pending",
    "read_onboarding_state",
    "should_inject_onboarding",
]
