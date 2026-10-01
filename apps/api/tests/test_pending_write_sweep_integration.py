"""兜底扫描的集成测试（docs/技术设计/technical-details/写入路径.md 第 4.1 节）。

这组用例钉住的是那次选型例外的兼底控制：docs/技术栈设计.md
第 2 节把 Taskiq 列为准则 1 的例外（该库自报 `Development Status :: 3 - Alpha`），
可接受理由原文是「丢的任务可被检测与补救」。在兜底扫描落地之前该控制不存在，
因此「扫描真的能把丢掉的记录救回来」必须有可执行证据，不能只靠设计文档。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete

from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.core.jobs import set_dispatch_hook
from campfire.core.pending_write import (
    KIND_MEMORY_EPISODE,
    KIND_PROFILE_ITEM,
    STATE_PENDING,
    SWEEP_MAX_LIMIT,
    PendingWrite,
    enqueue,
    find_undelivered,
    take_for_processing,
)

pytestmark = pytest.mark.integration

#: 本文件专用账号（与其它测试文件隔离）。
_ACCOUNT = "it_sweep_account"
#: `profile_item` 用例专用账号（同文件内再隔离一层，便于单独清理）。
_ACCOUNT_PROFILE = "it_sweep_account_profile"


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——不假装通过（仓库统一做法）。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _isolate() -> AsyncIterator[None]:
    """每个用例前后：清掉本账号的记录与投递钩子。

    清钩子是必须的：本文件会替换投递钩子，泄漏会让别的文件静默走假投递。
    数据清理同样是必须的：`_ACCOUNT` 的记录会被跨用例读到。
    """
    await _clear()
    yield
    set_dispatch_hook(None)
    await _clear()


async def _clear() -> None:
    async with session_scope(get_settings()) as session:
        await session.execute(delete(PendingWrite).where(PendingWrite.account_id.in_((_ACCOUNT, _ACCOUNT_PROFILE))))


async def _enqueue(*, occurred_at: str | None = None) -> str:
    """入队一条记忆记录；返回 id 字符串。"""
    async with session_scope(get_settings()) as session:
        record = await enqueue(
            session,
            kind="memory_episode",
            account_id=_ACCOUNT,
            origin="user_statement",
            payload={
                "content": "扫描用例的记忆",
                "occurred_at": occurred_at or datetime.now(timezone.utc).isoformat(),
            },
            source={"session_id": "s1"},
        )
        return str(record.id)


async def _enqueue_profile_item() -> str:
    """入队一条 `profile_item` 记录；返回 id 字符串。

    形状照 `tools/profile.py` 的 `propose_profile_item`（`support_object_id` 必填，
    见写入路径第 3 节）。这里不建真实支持对象：本文件的用例只看分派与状态，
    不消费它——消费 `profile_item` 是 T12 的范围。
    """
    async with session_scope(get_settings()) as session:
        record = await enqueue(
            session,
            kind=KIND_PROFILE_ITEM,
            account_id=_ACCOUNT_PROFILE,
            origin="user_statement",
            payload={"domain": "communication", "topic": "扫描用例", "description": "扫描用例的档案条目"},
            source={"session_id": "s1", "tool": "propose_profile_item"},
            support_object_id="00000000-0000-4000-8000-000000000009",
        )
        return str(record.id)


def _ids(found: list[tuple[object, str]]) -> list[str]:
    """取出 `find_undelivered` 结果里的 id（返回的是 `(id, kind)`）。"""
    return [str(pending_id) for pending_id, _kind in found]


# ---------------------------------------------------------------------------
# 候选集判据
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_fresh_pending_record_is_found() -> None:
    """刚入队、从未投递的记录必须被扫到——这是扫描存在的唯一理由。

    同时钉住返回形状是 `(id, kind)`：投递要按 kind 分派（写入路径第 4 节第 3 条），
    只给 id 时投递方只能一律投给同一个消费者。
    """
    pending_id = await _enqueue()
    async with session_scope(get_settings()) as session:
        found = await find_undelivered(session)
    assert str(pending_id) in _ids(found), "从未投递的记录没被扫到——兜底形同虚设"
    assert "memory_episode" in [kind for _id, kind in found], "候选集必须带上 kind"


@pytest.mark.asyncio
async def test_a_record_waiting_for_backoff_is_not_found() -> None:
    """退避未到期的不扫：否则等于把退避曲线抹平，失败记录会被立刻重投。

    判别性：去掉 `next_attempt_at <= reference` 条件，本用例失败。
    """
    from campfire.core.pending_write import mark_retryable_failure

    pending_id = await _enqueue()
    async with session_scope(get_settings()) as session:
        await take_for_processing(session, pending_id=pending_id, lease_owner="w")
    async with session_scope(get_settings()) as session:
        await mark_retryable_failure(session, pending_id=pending_id, error="临时失败")

    async with session_scope(get_settings()) as session:
        found = await find_undelivered(session)
    assert str(pending_id) not in _ids(found), "退避期内的记录不得被重投"

    # 退避到期后（1 分钟）就该被扫到。
    async with session_scope(get_settings()) as session:
        later = await find_undelivered(session, now=datetime.now(timezone.utc) + timedelta(minutes=5))
    assert str(pending_id) in _ids(later), "退避到期后应重新进入扫描范围"


@pytest.mark.asyncio
async def test_terminal_and_leased_records_are_not_swept() -> None:
    """终态不得被复活；`processing` 不归扫描（归租约回收，那条路径不消耗 attempts）。

    判别性：把状态条件放宽成「非终态」，`processing` 那条会被扫到，本用例失败。
    """
    from campfire.core.pending_write import mark_done

    done_id = await _enqueue()
    async with session_scope(get_settings()) as session:
        await take_for_processing(session, pending_id=done_id, lease_owner="w")
    async with session_scope(get_settings()) as session:
        await mark_done(session, pending_id=done_id, lease_owner="w")

    leased_id = await _enqueue()
    async with session_scope(get_settings()) as session:
        await take_for_processing(session, pending_id=leased_id, lease_owner="w2")

    async with session_scope(get_settings()) as session:
        found = _ids(await find_undelivered(session))
    assert str(done_id) not in found, "已 done 的记录不得被扫描复活"
    assert str(leased_id) not in found, "租约未过期的 processing 不归扫描管（归租约回收）"


@pytest.mark.asyncio
async def test_sweep_limit_is_converged_to_the_server_cap() -> None:
    """`limit` 收敛到 `SWEEP_MAX_LIMIT`（CORE-11）：周期任务不得单次无界。

    判别性：去掉 `min(limit, SWEEP_MAX_LIMIT)`，超限值会被原样接受，本用例失败。
    """
    pending_id = await _enqueue()
    async with session_scope(get_settings()) as session:
        # 数量不足以区分上界，因此直接断言「给一个天文数字也不会报错且仍能找到」，
        # 并用 SQL 参数级别的检查（下面的 event 钩子）确认收敛。
        import sqlalchemy

        captured: list[object] = []

        from campfire.core.db import get_engine

        engine = get_engine(get_settings())

        def _capture(_conn, _cursor, statement, parameters, _ctx, _many):  # noqa: ANN001
            if "LIMIT" in str(statement).upper() and "campfire_pending_write" in str(statement):
                captured.append(parameters)

        sqlalchemy.event.listen(engine.sync_engine, "before_cursor_execute", _capture)
        try:
            found = await find_undelivered(session, limit=10**9)
        finally:
            sqlalchemy.event.remove(engine.sync_engine, "before_cursor_execute", _capture)

    assert str(pending_id) in _ids(found)
    assert captured, "未捕获到扫描的 SELECT"
    params = captured[0]
    limit_value = params.get("param_1") if isinstance(params, dict) else params[-1]
    assert limit_value == SWEEP_MAX_LIMIT, f"limit=10**9 应收敛为 {SWEEP_MAX_LIMIT}，实际 {limit_value!r}"


# ---------------------------------------------------------------------------
# 端到端：扫描真的把丢掉的记录救回来
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_once_dispatches_the_undelivered_record() -> None:
    """扫描把从未投递的记录重新投出去——本文件的核心用例。

    这条直接对应 Taskiq 选型例外的可接受理由（「丢的任务可被检测与补救」）：
    入队后故意不投递（模拟投递失败），跑一轮扫描，断言投递被调用且带的是这条 id。
    """
    from campfire.worker import sweep_once

    dispatched: list[tuple[str, str]] = []

    async def _record(pending_id: str, kind: str) -> None:
        dispatched.append((pending_id, kind))

    set_dispatch_hook(_record)

    pending_id = await _enqueue()
    async with session_scope(get_settings()) as session:
        count = await sweep_once(session)

    # 断言成员而不是相等：扫描是全局的（它按状态挑记录，不做账号过滤——
    # 那正是「谁都没投递的记录都要被救回」的要求）。同表可能有别的测试/运维留下的
    # 待处理记录，因此列表里出现别的 id 是正常的。
    # 「哪些不该被扫」由 `test_terminal_and_leased_records_are_not_swept` 与
    # `test_a_record_waiting_for_backoff_is_not_found` 分别钉住。
    assert (str(pending_id), "memory_episode") in dispatched, f"扫描没有按 kind 重投这条记录（实际投递={dispatched}）"
    assert count >= 1


@pytest.mark.asyncio
async def test_sweep_once_reclaims_expired_leases_before_dispatching() -> None:
    """扫描先回收过期租约、再重投：崩溃留下的记录应在同一轮被救回，不等下一轮。

    判别性：把 `reclaim_expired_leases` 从 `sweep_once` 里去掉，本用例失败
    （记录仍是 `processing`，不在扫描候选集里，于是既没回收也没重投）。
    """
    from campfire.worker import sweep_once

    dispatched: list[tuple[str, str]] = []

    async def _record(pending_id: str, kind: str) -> None:
        dispatched.append((pending_id, kind))

    set_dispatch_hook(_record)

    base = datetime.now(timezone.utc)
    pending_id = await _enqueue()
    # 领取，租约按 `base` 计算（此时未过期）。
    async with session_scope(get_settings()) as session:
        await take_for_processing(session, pending_id=pending_id, lease_owner="crashed", now=base)

    # 把参照时间推到租约之后（模拟 Worker 崩溃、租约过期）。
    later = base + timedelta(seconds=600)
    async with session_scope(get_settings()) as session:
        await sweep_once(session, now=later)

    assert str(pending_id) in [pid for pid, _kind in dispatched], "崩溃留下的记录未被同一轮扫描救回（应先回收再重投）"


# ---------------------------------------------------------------------------
# 按 kind 分派（写入路径第 4 节第 3 条；2026-09-30 修复）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_dispatches_every_consumed_kind() -> None:
    """有消费者的 kind 都会被重投——T12 接上 `profile_item` 后两类都在候选集里。

    这条是 2026-09-30 修复的正面覆写：修复前投递钩子硬编码只投记忆任务，
    `profile_item` 要么被误投给记忆消费者判 `dead`，要么因为不在候选集里永不重投。
    T12 收口后，分派表两个键都在，兜底扫描按 `CONSUMED_KINDS` 过滤即等价于「全部」。

    判别性：把 `sweep_once` 里的 `kinds=CONSUMED_KINDS` 去掉，两类仍会被投
    ——本用例只断言语义（谁该被投），过滤器本身的判据在下一条。
    """
    from campfire.worker import sweep_once

    dispatched: list[tuple[str, str]] = []

    async def _record(pending_id: str, kind: str) -> None:
        dispatched.append((pending_id, kind))

    set_dispatch_hook(_record)

    profile_id = await _enqueue_profile_item()
    memory_id = await _enqueue()
    async with session_scope(get_settings()) as session:
        await sweep_once(session)

    dispatched_ids = [pending_id for pending_id, _kind in dispatched]
    assert (str(profile_id), KIND_PROFILE_ITEM) in dispatched, f"profile_item 有消费者，必须被重投（实际={dispatched}）"
    assert (str(memory_id), KIND_MEMORY_EPISODE) in dispatched, f"memory_episode 必须被重投（实际={dispatched}）"
    assert len(dispatched_ids) == len(set(dispatched_ids)), f"同一条记录不得在一轮里被投两次（实际={dispatched}）"


@pytest.mark.asyncio
async def test_sweep_skips_kinds_outside_the_consumed_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """没有消费者的 kind 不进候选集——按 `CONSUMED_KINDS` 过滤这一条判据的可执行形式。

    为什么这样做而不是插一条「未注册 kind」的记录：存储层有
    `CHECK (kind IN ('memory_episode','profile_item'))`（`core/pending_write/models.py`），
    未注册的 kind 根本插不进去；而 `KINDS` 是闭集、两个取值现在都有消费者，
    于是「没有消费者的 kind」在当前词表下只能由消费集合被收窄来表达
    （这正是将来新增第三种 kind 却忘了注册时的状态）。

    判别性：把 `sweep_once` 的 `kinds=CONSUMED_KINDS` 去掉，两条记录都会被投，本用例失败。
    """
    from campfire import worker as worker_module
    from campfire.worker import sweep_once

    dispatched: list[tuple[str, str]] = []

    async def _record(pending_id: str, kind: str) -> None:
        dispatched.append((pending_id, kind))

    set_dispatch_hook(_record)
    monkeypatch.setattr(worker_module, "CONSUMED_KINDS", frozenset())

    await _enqueue_profile_item()
    await _enqueue()
    async with session_scope(get_settings()) as session:
        await sweep_once(session)

    assert dispatched == [], f"没有消费者的 kind 不得被投给任何消费者（实际投递={dispatched}）"


@pytest.mark.asyncio
async def test_a_profile_item_stays_pending_after_a_sweep() -> None:
    """跑过一轮扫描后，`profile_item` 仍是 `pending`（不是 `dead`、不是 `done`）。

    扫描只负责投递，不终结任何记录：`dead` 与 `done` 都只发生在消费者手里。
    这里装了记录用的投递钩子（不真的消费），因此记录必须原样留在 `pending`
    且不被记成失败——「投出去了」与「处理完了」是两件事。

    判别性：让 `sweep_once` 顺手改记录状态（或让钩子直连消费者），本用例失败。
    """
    from sqlalchemy import select

    from campfire.worker import sweep_once

    profile_id = await _enqueue_profile_item()
    async with session_scope(get_settings()) as session:
        await sweep_once(session)

    async with session_scope(get_settings()) as session:
        row = (await session.execute(select(PendingWrite).where(PendingWrite.id == profile_id))).scalar_one()
    assert row.state == STATE_PENDING, f"扫描不终结记录，应仍是 pending，实际 {row.state!r}"
    assert row.last_error is None, "不得被记成「载荷不合法」的失败"


@pytest.mark.asyncio
async def test_a_failing_round_does_not_stop_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """单轮失败不得终止循环（第 4.1 节的失败语义）：否则一次数据库抖动就让
    「丢的任务可被检测」这条兼底控制静默关掉。

    失败注入点必须在 `sweep_once` 自身（让它抛错），而不是投递钩子——投递失败由
    `dispatch_pending_write` 内部吞掉并降级（那是有意的：记录留给下一轮，不改变
    回执），因此钩子抛错到不了循环的守卫。这一点是我第一版用例的真实错误：
    那时消融掉循环的 `except`，用例仍然通过——因为它注入的失败根本走不到守卫。
    循环守卫防的是 `sweep_once` 整体抛错（数据库不可用、查询失败之类）。
    """
    import asyncio
    from contextlib import suppress

    from campfire import worker as worker_module

    rounds: list[int] = []

    async def _flaky_find(session: object, **_kwargs: object) -> list[object]:  # noqa: ARG001
        rounds.append(len(rounds))
        raise RuntimeError("模拟数据库抖动")

    monkeypatch.setattr(worker_module, "find_undelivered", _flaky_find)

    original_interval = worker_module.SWEEP_INTERVAL_SECONDS
    monkeypatch.setattr(worker_module, "SWEEP_INTERVAL_SECONDS", 0)
    task = asyncio.create_task(worker_module._sweep_forever())
    try:
        for _ in range(200):
            if len(rounds) >= 2:
                break
            await asyncio.sleep(0.02)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        worker_module.SWEEP_INTERVAL_SECONDS = original_interval

    assert len(rounds) >= 2, f"单轮失败后循环停了（只跑了 {len(rounds)} 轮）"
