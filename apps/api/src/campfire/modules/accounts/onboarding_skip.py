"""引导跳过用例：把账号的引导状态置为 `skipped`（对话页 UI 跳过入口的服务端实现）。

职责：引导状态表的写入用例（唯一写 `skipped` 的地方）。
边界：只写 `skipped`——不写 `completed`（那是模型经 `finish_onboarding` 的通道，
两条通道互不代写）；不创建会话、不判断会话类型、不取消任何运行。
参考：docs/技术设计/面/consult/HTTP与SSE契约.md 第 6 节（本用例的契约）；
      docs/技术设计/technical-details/认证与账号.md 第 8 节（表形状与双通道）。

与 `onboarding_completion.complete_onboarding` 是同一张表的另一条写通道，两者的幂等
语义对称：已终结时直接返回当前状态、一个字节都不写。**互不代写**的具体含义在这里是
「已 `completed` 时不改写成 `skipped`」——使用者（或模型）已经明确说过引导走完了，
UI 上再点一次跳过不该把那个结论覆盖掉。

入参校验与 `onboarding_completion` 各自一份（同一形状的两份实现）：那个校验是按
「模块自己承担边界」写的私有函数，跨模块引用私有名会让它的归属变含糊。这里的代价是
五行重复，换来的是两个写通道各能独立阅读与回归。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.modules.accounts.errors import OnboardingWriteError
from campfire.modules.accounts.models import (
    MAX_ACCOUNT_ID_LENGTH,
    ONBOARDING_COMPLETED,
    ONBOARDING_SKIPPED,
    ONBOARDING_STATES,
    CampfireOnboarding,
)


def _utc_now() -> datetime:
    """当前 UTC 时间。集中一处，便于测试替换时只有一个改动点。"""
    return datetime.now(timezone.utc)


def _validate_account_id(raw: object) -> str:
    """校验账号标识的形状（`CORE-04`：数据边界运行时解析）。

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


async def skip_onboarding(
    session: AsyncSession,
    *,
    account_id: object,
    now: datetime | None = None,
) -> str:
    """把该账号的引导状态置为 `skipped`，返回写入后的状态。

    契约第 6 节的三条逐一落在这里：

    1. 幂等：已 `skipped` 或已 `completed` 时**不报错**，返回当前状态。
       为什么返回当前状态而不是一律回 `skipped`：本端点与 `complete_onboarding`
       共用一条纪律——不代写。已 `completed` 时若回 `skipped`，响应就在陈述一个
       存储层并不成立的事实，而调用方（前端）据此显示「已跳过」也是错的。
    2. 无行时**先创建再置位**：无行意味着该账号从未触发过引导，而使用者现在明确
       跳过了它。建行是必要的——没有行的话这次决定无处安放，下次日常会话仍会注入
       引导（`should_inject_onboarding(None) is True`）。
    3. 写入失败明确抛错：**不得**回执 `skipped`。调用方据此返回失败，而使用者再点一次
       即可重试（本用例幂等，重试没有副作用）。

    幂等为什么不刷新 `updated_at`：该列的语义是「最近一次状态迁移时间」，
    重复调用没有发生迁移。已终结态直接返回，一个字节都不写（与 `complete_onboarding`
    的选择一致，理由见那边的 docstring）。

    Args:
        session: 关系库会话（调用方负责提交）。
        account_id: 账号标识（键取登录态，不接受调用方传入任意值）。
        now: 参照时间（测试注入用）。

    Returns:
        写入后的状态：`skipped`（本次置位，或此前已跳过）或 `completed`
        （此前已由模型经 `finish_onboarding` 收束）。

    Raises:
        OnboardingWriteError: 账号标识不合法、状态取值漂移，或存储层拒绝了写入。
    """
    normalized = _validate_account_id(account_id)
    reference = now if now is not None else _utc_now()

    # 先查再写：幂等语义要求「已 completed 时返回 completed 而不是改成 skipped」，
    # 盲写 UPSERT 会把那个结论覆盖掉。
    existing = (
        await session.execute(select(CampfireOnboarding).where(CampfireOnboarding.account_id == normalized))
    ).scalar_one_or_none()

    if existing is not None:
        if existing.state not in ONBOARDING_STATES:
            # CHECK 约束挡住词表外的值，走到这里说明表形状与设计漂移（`CORE-07`：不猜）。
            raise OnboardingWriteError(
                f"引导状态 {existing.state!r} 不在词表内（{sorted(ONBOARDING_STATES)}）——表形状与设计漂移，无法记录跳过"
            )
        if existing.state in (ONBOARDING_COMPLETED, ONBOARDING_SKIPPED):
            return existing.state
        existing.state = ONBOARDING_SKIPPED
        existing.updated_at = reference
        return ONBOARDING_SKIPPED

    session.add(CampfireOnboarding(account_id=normalized, state=ONBOARDING_SKIPPED, updated_at=reference))
    return ONBOARDING_SKIPPED


__all__ = ["skip_onboarding"]
