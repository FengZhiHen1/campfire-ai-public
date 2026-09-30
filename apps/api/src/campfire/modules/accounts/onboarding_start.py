"""引导开始用例：把账号的引导状态落成 `in_progress`（首次注入引导时的记账）。

职责：引导状态表的写入用例（唯一写 `in_progress` 的地方），供日常会话第一次运行注入引导时调用。
边界：只落 `in_progress`——不改写任何已终结状态（`completed` / `skipped` 两条通道互不代写）；
不判定要不要注入（那归 `onboarding.should_inject_onboarding`）。
参考：docs/技术设计/technical-details/认证与账号.md 第 8 节（表形状与三条通道）；
      docs/技术设计/technical-details/技能设计.md 第 4 节（触发判定）；
      `models.CampfireOnboarding.state` 的列注释（初态在首次触发注入时落行）。

为什么需要它：`should_inject_onboarding(None)` 与 `...("in_progress")` 都返回「要注入」，
因此注入本身不依赖这一行；但「这个账号的引导开始了没有」这个问题只有本行能回答。
不落行时状态表在账号终结引导之前一直是空的，`read_onboarding_state` 返回 `None`——
而 `None` 的语义是「从未触发过引导」，于是「引导进行中」与「从未开始」不可区分。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.modules.accounts.errors import OnboardingWriteError
from campfire.modules.accounts.models import (
    MAX_ACCOUNT_ID_LENGTH,
    ONBOARDING_IN_PROGRESS,
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


async def start_onboarding(
    session: AsyncSession,
    *,
    account_id: object,
    now: datetime | None = None,
) -> str:
    """把该账号的引导状态落成 `in_progress`（无行时建行），返回写入后的状态。

    幂等且不夺权：已有行时原样返回当前状态、一个字节都不写。这是「三条写入通道
    互不代写」在本用例里的含义——一次 `in_progress` 的记账不该把使用者已经明确给出的
    结论（`completed`）或跳过决定（`skipped`）覆盖回进行中。落到这个分支的现实路径是
    并发或重试：第一次注入已经落行，第二条消息又走了一次本用例。

    为什么初次落行直接写 `in_progress` 而不是「先建行再改」：初态就是它，
    一次 INSERT 足够（与 `complete_onboarding` 初次直接写 `completed` 同法）。

    Args:
        session: 关系库会话（调用方负责提交）。
        account_id: 账号标识（键取登录态，不接受调用方传入任意值）。
        now: 参照时间（测试注入用）。

    Returns:
        写入后的状态：`in_progress`（本次落行）、`completed`、或 `skipped`。

    Raises:
        OnboardingWriteError: 账号标识不合法，或表里读到了词表外的状态（表形状漂移，
            此时不猜也不覆盖——`CORE-07`）。
    """
    normalized = _validate_account_id(account_id)
    reference = now if now is not None else _utc_now()

    existing = (
        await session.execute(select(CampfireOnboarding).where(CampfireOnboarding.account_id == normalized))
    ).scalar_one_or_none()

    if existing is not None:
        if existing.state not in ONBOARDING_STATES:
            raise OnboardingWriteError(
                f"引导状态 {existing.state!r} 不在词表内（{sorted(ONBOARDING_STATES)}）——"
                "表形状与设计漂移，无法记录引导开始"
            )
        return existing.state

    session.add(CampfireOnboarding(account_id=normalized, state=ONBOARDING_IN_PROGRESS, updated_at=reference))
    return ONBOARDING_IN_PROGRESS


__all__ = ["start_onboarding"]
