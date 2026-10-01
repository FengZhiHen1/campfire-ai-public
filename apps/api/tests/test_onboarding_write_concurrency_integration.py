"""集成测试：引导状态三条写入通道的并发与冲突语义（真实 PostgreSQL）。

对应 D-53：三条写入用例此前都是「SELECT → 判终结态 → `session.add`」，而
`campfire_onboarding.account_id` 是主键——两个并发调用里第二个 INSERT 撞主键
（SQLSTATE 23505），而三份 docstring 都声明了幂等。幂等与「三条通道互不代写」现在落在
存储层（主键冲突 + 终结态谓词的条件更新），本文件钉住这一点。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_onboarding_write_concurrency_integration.py

两层并发用例，各自回答不同的问题：

1. `asyncio.gather` 两个写入：回答「两个真并发调用会不会互相撞死、会不会各自谎报」。
   它不保证交错真的发生——两个协程可能被调度成先后完成。
2. 未提交行 + 金丝雀：先到者的写入持有主键且不提交，后到者必须卡在它上面（判据是
   PostgreSQL 自己的等待事件，不是时间猜测）。它回答「冲突分支真的被走到了」，
   这正是 gather 用例给不出的保证。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy import text as sql_text

from campfire.core.config import Settings, get_settings
from campfire.core.db import get_session_factory, session_scope
from campfire.modules.accounts.errors import OnboardingWriteError
from campfire.modules.accounts.models import (
    ONBOARDING_COMPLETED,
    ONBOARDING_IN_PROGRESS,
    ONBOARDING_SKIPPED,
    CampfireOnboarding,
)
from campfire.modules.accounts.onboarding_completion import complete_onboarding
from campfire.modules.accounts.onboarding_skip import skip_onboarding
from campfire.modules.accounts.onboarding_start import start_onboarding

# 本文件的用例全是 async（仓库未开 pytest-asyncio 的 auto 模式，逐个加标记是既有做法）。
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: 本文件的账号。清库只按它过滤：别的集成测试文件同时在跑，全表删除会互相删行。
_ACCOUNT = "it_onboarding_write_account"

_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
_NOW_RACER = _NOW + timedelta(hours=1)

#: 金丝雀的等待上限与轮询间隔（秒）。正确实现下等待在毫秒级出现。
_BLOCK_TIMEOUT_SECONDS = 5.0
_BLOCK_POLL_SECONDS = 0.02

#: 写入用例的调用形状（三条通道同形：会话 + 关键字参数）。
WriteCall = Callable[..., Awaitable[str]]


# ---------------------------------------------------------------------------
# 夹具与辅助
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——不假装通过。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    """清掉本文件账号的引导状态行：前后各一次。"""
    await _clear()
    yield
    await _clear()


async def _clear() -> None:
    async with session_scope(get_settings()) as session:
        await session.execute(delete(CampfireOnboarding).where(CampfireOnboarding.account_id == _ACCOUNT))


async def _state() -> str | None:
    async with session_scope(get_settings()) as session:
        return (
            await session.execute(select(CampfireOnboarding.state).where(CampfireOnboarding.account_id == _ACCOUNT))
        ).scalar_one_or_none()


async def _updated_at() -> datetime | None:
    async with session_scope(get_settings()) as session:
        return (
            await session.execute(
                select(CampfireOnboarding.updated_at).where(CampfireOnboarding.account_id == _ACCOUNT)
            )
        ).scalar_one_or_none()


async def _seed(state: str, *, now: datetime = _NOW) -> None:
    """预置一行既有状态（已提交）。"""
    async with session_scope(get_settings()) as session:
        session.add(CampfireOnboarding(account_id=_ACCOUNT, state=state, updated_at=now))


async def _gather_writes(writes: Sequence[WriteCall], *, now: datetime = _NOW) -> list[str]:
    """每个写入各用一个会话真并发执行，按入参顺序返回结果。

    任一写入抛出都原样冒出去（`gather` 默认行为）：这是本文件「撞主键」的判据通道，
    吞掉异常会让用例在最该报错的时候保持绿色。
    """
    settings = get_settings()

    async def _run(write: WriteCall) -> str:
        async with session_scope(settings) as session:
            return await write(session, account_id=_ACCOUNT, now=now)

    return list(await asyncio.gather(*(_run(write) for write in writes)))


async def _wait_until_blocked_on_the_key(settings: Settings) -> bool:
    """轮询到「真有一条引导写入正等在主键上」为止，返回是否等到。

    判据取自 PostgreSQL 自己的等待事件，不是时间猜测：只有后到者的 INSERT 真的落在
    先到者的未提交行上时，才会出现一条 `wait_event_type = 'Lock'` 且语句指向
    `campfire_onboarding` 的会话。
    """
    deadline = asyncio.get_running_loop().time() + _BLOCK_TIMEOUT_SECONDS
    while True:
        async with session_scope(settings) as session:
            waiting = (
                await session.execute(
                    sql_text(
                        "SELECT count(*) FROM pg_stat_activity"
                        " WHERE pid <> pg_backend_pid()"
                        " AND wait_event_type = 'Lock'"
                        " AND query ILIKE '%campfire_onboarding%'"
                    )
                )
            ).scalar_one()
        if waiting:
            return True
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(_BLOCK_POLL_SECONDS)


# ---------------------------------------------------------------------------
# 同通道并发（三条通道各自的「两个并发调用」）
# ---------------------------------------------------------------------------

_SAME_CHANNEL_WRITES: tuple[tuple[WriteCall, str], ...] = (
    (start_onboarding, ONBOARDING_IN_PROGRESS),
    (complete_onboarding, ONBOARDING_COMPLETED),
    (skip_onboarding, ONBOARDING_SKIPPED),
)


@pytest.mark.parametrize(("write", "expected"), _SAME_CHANNEL_WRITES, ids=("start", "complete", "skip"))
async def test_gathered_writes_of_one_channel_report_one_conclusion(write: WriteCall, expected: str) -> None:
    """两个真并发的同通道写入：一个落行，另一个既不撞主键也不谎报。

    判别性：改回「先查后写」时，两个调用都读到自己该写，第二个的 INSERT 撞主键，
    `asyncio.gather` 把 `IntegrityError` 原样抛出来，本用例直接报错。
    """
    results = await _gather_writes((write, write))

    assert results == [expected, expected]
    assert await _state() == expected


async def test_gathered_start_and_completion_both_land_and_completion_wins_the_state() -> None:
    """首轮注入结算（`start_onboarding`）与工具收束（`complete_onboarding`）同时写同一账号。

    与「两条终态通道」不同，这里不断言两次回报一致：`in_progress` 的回报在它返回的那一刻
    是真的，随后被收束迁移成 `completed` 是合法的线性化，不是谎报。钉住的是
    「都不撞主键」以及「收束最终生效、没有任何一次写入把 `completed` 退回去」。
    """
    results = await _gather_writes((start_onboarding, complete_onboarding))

    assert set(results) <= {ONBOARDING_IN_PROGRESS, ONBOARDING_COMPLETED}
    assert ONBOARDING_COMPLETED in results, "收束调用必须给出 `completed`"
    assert await _state() == ONBOARDING_COMPLETED


# ---------------------------------------------------------------------------
# 跨通道并发（互不代写）
# ---------------------------------------------------------------------------


async def test_gathered_completion_and_skip_agree_with_the_stored_conclusion() -> None:
    """空账号上两条终态通道同时写：只有一条落行，另一条重读后回报同一个结论。

    判别性：把条件写入换成盲写 UPSERT（或去掉终结态谓词），两条通道会各自回报自己的
    目标值，而存储里只有一个——`set(results) == {stored}` 立刻失败。
    """
    results = await _gather_writes((complete_onboarding, skip_onboarding))

    stored = await _state()
    assert stored in (ONBOARDING_COMPLETED, ONBOARDING_SKIPPED)
    assert set(results) == {stored}, "两条通道的回报必须与存储事实一致"


async def test_gathered_completion_and_skip_migrate_in_progress_exactly_once() -> None:
    """行已 `in_progress` 时两条终态通道同时写：只有一次迁移，另一次回报赢家的结论。

    这里是「两条通道互不代写」在并发下唯一可能被破坏的地方：两者都读到 `in_progress` 时，
    先查后写会让两次 UPDATE 都发出，后提交的那次把前一次的终结结论覆盖掉。
    """
    await _seed(ONBOARDING_IN_PROGRESS)

    results = await _gather_writes((complete_onboarding, skip_onboarding))

    stored = await _state()
    assert stored in (ONBOARDING_COMPLETED, ONBOARDING_SKIPPED)
    assert set(results) == {stored}, "先到者已给出的终结结论不得被后到者覆盖"


# ---------------------------------------------------------------------------
# 确定性交错（后到者必须等在先到者的未提交行上）
# ---------------------------------------------------------------------------


async def test_a_write_racing_an_uncommitted_row_neither_collides_nor_lies() -> None:
    """先到者的写入持主键未提交时，后到者等在主键上，并回报先到者的结论。

    为什么不用 `asyncio.gather` 制造这个交错：gather 不保证后到者的写入真的落在先到者的
    未提交行上（那取决于两次 await 的调度时序）。本用例先让先到者的 INSERT 真的发出
    （未提交），再用金丝雀确认后到者卡在它上面，交错因此是确定的。

    只落一次写入的判据是 `updated_at`：后到者带的参照时间更晚，若它的条件更新真的落在
    已终结的行上，这个时间戳会变——它没变，说明后到者一个字节都没写。
    """
    settings = get_settings()
    factory = get_session_factory(settings)

    async with factory() as holder, factory() as racer:
        holder_state = await complete_onboarding(holder, account_id=_ACCOUNT, now=_NOW)

        task = asyncio.create_task(complete_onboarding(racer, account_id=_ACCOUNT, now=_NOW_RACER))
        blocked = await _wait_until_blocked_on_the_key(settings)
        await holder.commit()  # 无论金丝雀结果如何都先解锁，不把行锁留到用例之外
        racer_state = await task
        await racer.commit()

    assert blocked, "后到者的写入没有卡在先到者的未提交行上——本次交错不构成冲突分支的证据"
    assert holder_state == racer_state == ONBOARDING_COMPLETED
    assert await _state() == ONBOARDING_COMPLETED
    assert await _updated_at() == _NOW, "后到者的条件更新不该落在已终结的行上"


# ---------------------------------------------------------------------------
# 冲突后的重读（不可达分支也必须显式失败）
# ---------------------------------------------------------------------------

_ALL_WRITES: tuple[WriteCall, ...] = (start_onboarding, complete_onboarding, skip_onboarding)


@pytest.mark.parametrize("write", _ALL_WRITES, ids=("start", "complete", "skip"))
async def test_a_conflict_that_cannot_be_reread_fails_explicitly(write: WriteCall) -> None:
    """冲突后重读不到状态行时显式失败：不编造一个状态（`CORE-07` 无静默兜底）。

    这一分支理论上不可达（未写入意味着冲突行存在），因此用桩会话给出两次 `execute`
    的返回值（未写入 + 重读为空）——验的是用例函数的判据，不是数据库能否造出这种状态。
    """
    not_written = MagicMock()
    not_written.scalar_one_or_none = MagicMock(return_value=None)
    vanished = MagicMock()
    vanished.scalar_one_or_none = MagicMock(return_value=None)
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[not_written, vanished])

    with pytest.raises(OnboardingWriteError, match="重读不到"):
        await write(session, account_id=_ACCOUNT, now=_NOW)
