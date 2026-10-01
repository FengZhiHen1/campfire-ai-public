"""集成测试：引导收束用例的幂等与双通道语义（真实 PostgreSQL）。

对应 `docs/技术设计/面/consult/tools/finish_onboarding.md` 第 4、6 节与
`docs/技术设计/technical-details/认证与账号.md` 第 8 节（双通道）。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_onboarding_completion_integration.py

本文件守住的核心判据：

1. 置位：无行时创建并写 `completed`；`in_progress` 时迁移为 `completed`。
2. 幂等：重复调用不报错，且不刷新 `updated_at`（它不是状态迁移）。
3. 不代写：已 `skipped` 时返回 `skipped`，不改写成 `completed`
   ——UI 通道与工具通道互不代写。
4. 状态表驱动：收束后 `onboarding_pending` 为假（后续日常会话不再注入引导）。
5. 词表外状态显式报错：不猜、不覆盖（`CORE-07` 无静默兜底）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.modules.accounts.errors import OnboardingWriteError
from campfire.modules.accounts.models import (
    ONBOARDING_COMPLETED,
    ONBOARDING_IN_PROGRESS,
    ONBOARDING_SKIPPED,
    CampfireOnboarding,
)
from campfire.modules.accounts.onboarding import onboarding_pending
from campfire.modules.accounts.onboarding_completion import complete_onboarding

pytestmark = pytest.mark.integration

_ACCOUNT = "it_onboarding_account"
_ACCOUNT_OTHER = "it_onboarding_other"

_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——不假装通过。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    """清掉本文件两个账号的引导状态行。"""
    await _clear()
    yield
    await _clear()


async def _clear() -> None:
    async with session_scope(get_settings()) as session:
        await session.execute(
            delete(CampfireOnboarding).where(CampfireOnboarding.account_id.in_((_ACCOUNT, _ACCOUNT_OTHER)))
        )


async def _read(account: str = _ACCOUNT) -> str | None:
    async with session_scope(get_settings()) as session:
        row = (
            await session.execute(select(CampfireOnboarding).where(CampfireOnboarding.account_id == account))
        ).scalar_one_or_none()
    return None if row is None else row.state


async def _read_updated_at(account: str = _ACCOUNT) -> datetime | None:
    async with session_scope(get_settings()) as session:
        row = (
            await session.execute(select(CampfireOnboarding).where(CampfireOnboarding.account_id == account))
        ).scalar_one_or_none()
    return None if row is None else row.updated_at


async def _seed(account: str, state: str) -> None:
    async with session_scope(get_settings()) as session:
        session.add(CampfireOnboarding(account_id=account, state=state, updated_at=_NOW))


# ---------------------------------------------------------------------------
# 置位（契约第 4 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_creates_the_row_when_the_account_was_never_guided() -> None:
    """无行时创建并写 `completed`。

    为什么必须创建（而不是「无行就无事可做」）：无行意味着从未触发过引导，而模型现在
    明确报告引导走完了。不落行的话「已完成」这件事无处安放，下次会话仍会注入引导
    （`should_inject_onboarding(None) is True`）——使用者的明确结论被丢掉。
    """
    assert await _read() is None

    async with session_scope(get_settings()) as session:
        state = await complete_onboarding(session, account_id=_ACCOUNT, now=_NOW)

    assert state == ONBOARDING_COMPLETED
    assert await _read() == ONBOARDING_COMPLETED


@pytest.mark.asyncio
async def test_moves_in_progress_to_completed() -> None:
    """`in_progress` → `completed`，且刷新 `updated_at`（这是一次真实的状态迁移）。"""
    await _seed(_ACCOUNT, ONBOARDING_IN_PROGRESS)
    later = _NOW + timedelta(hours=1)

    async with session_scope(get_settings()) as session:
        state = await complete_onboarding(session, account_id=_ACCOUNT, now=later)

    assert state == ONBOARDING_COMPLETED
    assert await _read() == ONBOARDING_COMPLETED
    assert await _read_updated_at() == later


@pytest.mark.asyncio
async def test_stops_triggering_the_onboarding_skill_afterwards() -> None:
    """契约第 6 节第一项：收束后 `onboarding_pending` 为假（状态表驱动，非时间推导）。"""
    async with session_scope(get_settings()) as session:
        assert await onboarding_pending(session, account_id=_ACCOUNT) is True

    async with session_scope(get_settings()) as session:
        await complete_onboarding(session, account_id=_ACCOUNT, now=_NOW)

    async with session_scope(get_settings()) as session:
        assert await onboarding_pending(session, account_id=_ACCOUNT) is False


# ---------------------------------------------------------------------------
# 幂等（契约第 4 节第 2 条）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_calls_are_idempotent() -> None:
    """重复调用不报错，返回同一个状态。"""
    async with session_scope(get_settings()) as session:
        first = await complete_onboarding(session, account_id=_ACCOUNT, now=_NOW)
    async with session_scope(get_settings()) as session:
        second = await complete_onboarding(session, account_id=_ACCOUNT, now=_NOW + timedelta(days=1))

    assert first == second == ONBOARDING_COMPLETED


@pytest.mark.asyncio
async def test_repeated_calls_do_not_refresh_the_timestamp() -> None:
    """重复调用不刷新 `updated_at`：它的语义是「最近一次状态迁移」，不是「最近一次被调用」。

    判别性：去掉「已终结态直接返回」，本用例失败——而每次调用都刷新会让
    「这个账号什么时候真的完成引导的」这个问题永远读不到答案（读到的是最后一次重试的时间）。
    """
    async with session_scope(get_settings()) as session:
        await complete_onboarding(session, account_id=_ACCOUNT, now=_NOW)
    first_stamp = await _read_updated_at()

    async with session_scope(get_settings()) as session:
        await complete_onboarding(session, account_id=_ACCOUNT, now=_NOW + timedelta(days=30))

    assert await _read_updated_at() == first_stamp, "重复调用不得刷新状态迁移时间"


# ---------------------------------------------------------------------------
# 双通道：不代写 skipped（契约第 1、4 节；认证与账号第 8 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_skipped_onboarding_is_not_rewritten_to_completed() -> None:
    """已 `skipped`（使用者经 UI 明确跳过）时返回 `skipped`，不改写。

    判别性：把 `existing.state in (COMPLETED, SKIPPED)` 的分支去掉（盲写 `completed`），
    本用例失败——那会抹掉使用者的显式决定。两条通道互不代写。
    """
    await _seed(_ACCOUNT, ONBOARDING_SKIPPED)
    stamp = await _read_updated_at()

    async with session_scope(get_settings()) as session:
        state = await complete_onboarding(session, account_id=_ACCOUNT, now=_NOW + timedelta(days=1))

    assert state == ONBOARDING_SKIPPED, "不得把使用者的显式跳过改写成已完成"
    assert await _read() == ONBOARDING_SKIPPED
    assert await _read_updated_at() == stamp


@pytest.mark.asyncio
async def test_completion_does_not_touch_another_account() -> None:
    """收束只写本账号的行（键取登录态）——另一账号的状态不受影响。"""
    await _seed(_ACCOUNT_OTHER, ONBOARDING_IN_PROGRESS)

    async with session_scope(get_settings()) as session:
        await complete_onboarding(session, account_id=_ACCOUNT, now=_NOW)

    assert await _read(_ACCOUNT) == ONBOARDING_COMPLETED
    assert await _read(_ACCOUNT_OTHER) == ONBOARDING_IN_PROGRESS, "不得牵连其他账号"


# ---------------------------------------------------------------------------
# 失败语义（契约第 4 节；CORE-07 无静默兜底）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_state_is_rejected_not_overwritten() -> None:
    """表里读到词表外的状态时显式报错：不猜、不覆盖。

    怎么造出这种行：`state` 有 CHECK 约束，正常写入路径造不出来。这里直接用桩会话
    给出两次 `execute` 的返回值：第一次（条件写入）返回空集表示「未写入」，
    第二次（重读既有行）返回那个词表外的状态——本用例要验的是用例函数的判据，
    而不是数据库能不能存下这个值。
    """
    from unittest.mock import AsyncMock, MagicMock

    from campfire.modules.accounts import onboarding_completion as module

    not_written = MagicMock()
    not_written.scalar_one_or_none = MagicMock(return_value=None)
    drifted = MagicMock()
    drifted.scalar_one_or_none = MagicMock(return_value="half_done")
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[not_written, drifted])

    with pytest.raises(OnboardingWriteError, match="不在词表内"):
        await module.complete_onboarding(session, account_id=_ACCOUNT, now=_NOW)


@pytest.mark.asyncio
async def test_an_empty_account_id_is_rejected() -> None:
    """空账号标识显式拒绝（`CORE-04` 数据边界运行时解析）。"""
    async with session_scope(get_settings()) as session:
        with pytest.raises(OnboardingWriteError, match="不得为空"):
            await complete_onboarding(session, account_id="")
