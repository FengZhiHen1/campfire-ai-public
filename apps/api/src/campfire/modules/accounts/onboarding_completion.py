"""引导收束用例：把账号的引导状态置为 `completed`（`finish_onboarding` 的服务端实现）。

职责：引导状态表的写入用例（唯一写 `completed` 的地方）。
边界：只写 `completed`——不写 `skipped`（那是对话页 UI 跳过入口的通道，两条通道互不代写）；
不创建会话、不判断会话类型；不读档案。
参考：docs/技术设计/面/consult/tools/finish_onboarding.md（本用例的契约）；
      docs/技术设计/technical-details/认证与账号.md 第 8 节（表形状与双通道）；
      docs/技术设计/面/consult/HTTP与SSE契约.md 第 6 节（另一条通道的幂等语义）。

为什么单独一个文件而不是塞进 `onboarding.py`：

`onboarding.py` 的职责范围写的是「触发判定」，其模块 docstring 明确写着「不写状态」。
把写路径塞进去会让那个边界陈述当场失效，而边界陈述是后续维护者判断「该往哪加代码」的
唯一依据。分成两个文件后：读路径与写路径各有自己的模块说明，`__init__` 一起再导出。

为什么归 `modules/accounts`（T04 裁决 3）：

`campfire_onboarding` 是账号级的引导状态表，表的所有者是 `modules/accounts`。
工具层（`tools/`）只做契约映射，状态机与幂等语义留在这里——与 `propose_profile_item`
把落层判据留在 `modules/profile` 是同一种分工。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.modules.accounts.errors import OnboardingWriteError
from campfire.modules.accounts.models import (
    MAX_ACCOUNT_ID_LENGTH,
    ONBOARDING_COMPLETED,
    ONBOARDING_IN_PROGRESS,
    ONBOARDING_STATES,
    CampfireOnboarding,
)

#: 引导的段名（`skipped_sections` 的合法取值）。
#:
#: 契约第 2 节列出三个段名，并明写「仅作记录，不影响状态取值」——它不进状态机，
#: 因此本模块不校验、不存储它们。为什么保留这个词表：工具层的参数模型要有一个
#: 可枚举的取值域（否则模型可以塞任意字符串，而那会变成一条没有消费者的自由文本），
#: 而词表的语义所有者是 skill 的引导流程（onboarding SKILL.md 第 2 节的三段）。
#: 放在此处是为了让工具层从本模块取词表，而不是在工具里另抄一份。
SKIPPED_SECTIONS: frozenset[str] = frozenset({"onboarding", "profile_seed", "memory_seed"})


def _utc_now() -> datetime:
    """当前 UTC 时间。集中一处，便于测试替换时只有一个改动点。"""
    return datetime.now(timezone.utc)


def _validate_account_id(raw: object) -> str:
    """校验账号标识的形状（`CORE-04`：数据边界运行时解析）。

    与 `repository._validate_account_id` 的判据一致（非字符串 / 空 / 超宽），但不复用它：
    那个函数是私有的（下划线前缀），跨模块引用私有名会让「它的归属是邀请码仓储」这件事
    变得含糊。这里是一个独立用例模块，重复五行校验比跨模块借用私有函数更清楚。

    Raises:
        OnboardingWriteError: 非字符串、空值或超宽。
    """
    if not isinstance(raw, str):
        raise OnboardingWriteError(f"账号标识必须是字符串，收到 {type(raw).__name__}")
    if not raw:
        raise OnboardingWriteError("账号标识不得为空——无法写入引导状态")
    if len(raw) > MAX_ACCOUNT_ID_LENGTH:
        raise OnboardingWriteError(f"账号标识超过 {MAX_ACCOUNT_ID_LENGTH} 字符上界")
    return raw


async def complete_onboarding(
    session: AsyncSession,
    *,
    account_id: object,
    now: datetime | None = None,
) -> str:
    """把该账号的引导状态置为 `completed`，返回写入后的状态。

    契约第 4 节的四条逐一落在这里：

    1. 幂等：已 `completed` 时不报错，直接返回当前状态（也不重复刷新时间戳，见下）。
       并发调用同一账号时同样成立：幂等承载在主键冲突上（一条带终结态谓词的条件语句），
       不靠「先读一次再决定写不写」——后者在并发下会让第二个调用撞主键（见实现处说明）。
    2. 已 `skipped` 时同样成功返回 `skipped`——不把它改写成 `completed`。
       为什么：两条通道互不代写（认证与账号第 8 节）。使用者经 UI 明确跳过了引导，
       模型的收束调用不该覆盖那个决定；而报错也不对——契约第 4 节第 2 条要的是幂等，
       且「跳过之后又走完收束段」是合法时序（SKILL.md 第 6 条：即使全程跳过，收束段仍要走完）。
    3. 无行时先创建再置位：无行意味着该账号从未触发过引导，而模型现在明确报告
       引导走完了。创建行是必要的——没有行的话「已完成」这件事无处安放，下次会话仍会注入
       引导（`should_inject_onboarding(None) is True`），使用者的明确结论被丢掉。
       初始状态写 `completed` 而不是 `in_progress` 再改（一次 INSERT 而不是 INSERT+UPDATE）。
    4. 写入失败明确抛错：不得回执 `completed`——工具层据此返回失败，
       而 UI 跳过入口仍是补救通道（契约第 5 节末行）。

    幂等为什么不刷新 `updated_at`（一条需要讲清的选择）：`updated_at` 的语义是
    「最近一次状态迁移时间」（模型侧的列注释原文），而重复调用没有发生迁移。
    每次调用都刷新会让这个字段变成「最近一次被调用时间」——那是另一个字段，
    且会掩盖真实的状态迁移时间（排查「这个账号什么时候真的完成引导的」时读到的
    是最后一次重试的时间）。因此已终结态直接返回，一个字节都不写。

    Args:
        session: 关系库会话（调用方负责提交）。
        account_id: 账号标识（键取登录态，不接受调用方传入任意值）。
        now: 参照时间（测试注入用）。

    Returns:
        写入后的状态：`completed`（本次置位）或 `skipped`（此前已被 UI 跳过）。

    Raises:
        OnboardingWriteError: 账号标识不合法、状态取值漂移（含键冲突后重读不到状态行）。
    """
    normalized = _validate_account_id(account_id)
    reference = now if now is not None else _utc_now()

    # 写靠主键冲突判定，不先查后写（与 `session_repository.insert_session_owner`、
    # `memory.ledger.record_deletion` 同法）。先查后写会让两个并发调用都读到自己该写，
    # 第二个 INSERT 撞主键（23505）——那正是本用例 docstring 承诺的幂等在并发下失效的地方。
    #
    # 一条语句承担三种情形，幂等与「两条通道互不代写」都落在存储层（`CORE-05` 的通道阶梯）：
    #   无行 → 落 `completed`（初态直接写终结态，一次 INSERT 而不是 INSERT+UPDATE）；
    #   行是 `in_progress` → 条件更新为 `completed` 并刷新 `updated_at`（真实的状态迁移）；
    #   行已终结（`completed` / `skipped`）→ `WHERE` 不中，一个字节都不写（含 `updated_at`）。
    # 条件更新而不是盲写 UPSERT：后者会把使用者的 `skipped` 覆盖成 `completed`。
    statement = (
        pg_insert(CampfireOnboarding)
        .values(account_id=normalized, state=ONBOARDING_COMPLETED, updated_at=reference)
        .on_conflict_do_update(
            index_elements=[CampfireOnboarding.account_id],
            set_={"state": ONBOARDING_COMPLETED, "updated_at": reference},
            where=CampfireOnboarding.state == ONBOARDING_IN_PROGRESS,
        )
        .returning(CampfireOnboarding.state)
    )
    written = (await session.execute(statement)).scalar_one_or_none()
    if written is not None:
        return ONBOARDING_COMPLETED

    # 未写入 = 冲突行已处于终结态（`WHERE` 不中），本次调用只回报它的结论。
    existing_state = (
        await session.execute(select(CampfireOnboarding.state).where(CampfireOnboarding.account_id == normalized))
    ).scalar_one_or_none()

    if existing_state is None:
        # 理论上不可达（未写入意味着冲突行存在）。显式失败而不是编造一个状态。
        raise OnboardingWriteError("引导状态行在键冲突后既未写入也重读不到——表形状与设计漂移，无法完成引导")
    if existing_state not in ONBOARDING_STATES:
        # CHECK 约束挡住词表外的值，走到这里说明表形状与设计漂移。
        # 不猜：既不能把它当已终结，也不能覆盖——两者都会掩盖漂移（`CORE-07`）。
        raise OnboardingWriteError(
            f"引导状态 {existing_state!r} 不在词表内（{sorted(ONBOARDING_STATES)}）——表形状与设计漂移，无法完成引导"
        )
    return existing_state


__all__ = [
    "SKIPPED_SECTIONS",
    "complete_onboarding",
]
