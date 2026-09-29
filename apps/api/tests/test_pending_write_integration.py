"""集成测试：待处理写入记录的状态机与租约（真实 PostgreSQL）。

对应 ``docs/技术设计/technical-details/写入路径.md`` 第 3、4、5、6 节。这些事实是
**数据库行为**（条件更新、行锁、CHECK 约束），因此带 ``integration`` marker。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_pending_write_integration.py

锁住的是状态机的不变量，逐条对应设计：

1. **不变量**：只有 ``state = done`` 算写入成功——新记录是 ``pending``。
2. **领取是原子的**（第 4 节「不使用先查后改的无锁流程」）：并发两次领取只有一个成功。
3. **租约过期可重领**，且**不消耗 `attempts`**（Worker 崩溃不是「尝试失败」）。
4. **可重试失败按退避后移**、`attempts + 1`（第 6 节）。
5. **超过上限转 `dead`**（第 6 节：不得静默丢弃）。
6. **归属字段按 kind**（第 3 节）：`memory_episode` 带对象、`profile_item` 缺对象
   都被**存储层**拒绝。
7. **词表落 CHECK**：非法 `kind`/`origin`/`state` 被存储层拒绝。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from campfire.core.config import get_settings
from campfire.core.db import dispose_engine, session_scope
from campfire.core.pending_write import (
    MAX_ATTEMPTS,
    STATE_DEAD,
    STATE_DONE,
    STATE_PENDING,
    STATE_PROCESSING,
    InsufficientPayloadError,
    PendingWrite,
    PendingWriteNotFoundError,
    enqueue,
    mark_dead,
    mark_done,
    mark_retryable_failure,
    reclaim_expired_leases,
    take_for_processing,
)

pytestmark = pytest.mark.integration

#: 本文件的账号前缀，用于清理自己的行（不按 id 清，避免漏掉中途失败留下的记录）。
_ACCOUNT = "it_pending_write_account"


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——**不假装通过**（仓库既有集成测试的统一做法）。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _dispose_shared_engine() -> AsyncIterator[None]:
    """每个用例前后释放共享引擎（跨事件循环复用会 ``Event loop is closed``）。"""
    await dispose_engine()
    yield
    await dispose_engine()


async def _clear() -> None:
    """清掉本文件写入的行。"""
    async with session_scope(get_settings()) as session:
        await session.execute(delete(PendingWrite).where(PendingWrite.account_id == _ACCOUNT))


async def _enqueue_memory(pending_id: uuid.UUID | None = None) -> uuid.UUID:
    """入队一条记忆记录，返回其 id。"""
    async with session_scope(get_settings()) as session:
        record = await enqueue(
            session,
            kind="memory_episode",
            account_id=_ACCOUNT,
            origin="user_statement",
            payload={"content": "他喜欢早上跑步", "occurred_at": "2026-09-29T08:00:00+00:00"},
            source={"session_id": "s1", "message_seq": 3},
            pending_id=pending_id,
        )
        return record.id


# ---------------------------------------------------------------------------
# 入队与形状
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_record_is_pending_not_done() -> None:
    """**不变量**：新记录是 `pending`——「没写进去」不得被当作「写进去了」。"""
    await _clear()
    try:
        pending_id = await _enqueue_memory()
        async with session_scope(get_settings()) as session:
            row = (await session.execute(select(PendingWrite).where(PendingWrite.id == pending_id))).scalar_one()
        assert row.state == STATE_PENDING
        assert row.attempts == 0
        assert row.finished_at is None, "未终结的记录不得有 finished_at"
        assert row.lease_owner is None
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_enqueue_rejects_object_on_memory_and_missing_object_on_profile() -> None:
    """归属字段按 kind 的判据（第 3 节）在**应用层入口**也提前拒绝。

    真正的判据在存储层 CHECK（见下一条用例）；这里验证应用层给出**可读的错误**，
    而不是让调用方读到数据库约束名。
    """
    await _clear()
    try:
        async with session_scope(get_settings()) as session:
            with pytest.raises(InsufficientPayloadError, match="不得带 support_object_id"):
                await enqueue(
                    session,
                    kind="memory_episode",
                    account_id=_ACCOUNT,
                    origin="user_statement",
                    payload={},
                    source={},
                    support_object_id="obj-1",
                )
            with pytest.raises(InsufficientPayloadError, match="必须有 support_object_id"):
                await enqueue(
                    session,
                    kind="profile_item",
                    account_id=_ACCOUNT,
                    origin="user_statement",
                    payload={},
                    source={},
                )
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_database_rejects_object_on_memory_record() -> None:
    """**存储层**拒绝「记忆带支持对象」——这是第 3 节要求的硬判据。

    为什么必须落在存储层：只在应用层校验的话，一旦有代码绕过 `enqueue` 写库，
    「记忆被误设了对象」就会落库，而后续所有按账号取记忆的查询都会漏掉它（静默）。
    """
    from sqlalchemy.exc import IntegrityError

    await _clear()
    try:
        # `session_scope` 在退出时提交——约束在 flush/commit 时触发，故用外层
        # `pytest.raises` 包住整个 with（与 `test_memory_ledger_integration.py`
        # 的既有做法一致）。
        with pytest.raises(IntegrityError, match="support_object_by_kind"):
            async with session_scope(get_settings()) as session:
                session.add(
                    PendingWrite(
                        kind="memory_episode",
                        account_id=_ACCOUNT,
                        support_object_id="obj-1",  # 记忆不得带对象
                        payload={},
                        origin="user_statement",
                        source={},
                    )
                )
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_database_rejects_values_outside_the_vocabularies() -> None:
    """`kind` / `origin` / `state` 的词表判据落在 **CHECK 约束**上。"""
    from sqlalchemy.exc import IntegrityError

    await _clear()
    try:
        for field, bad_value, constraint in (
            ("kind", "not_a_kind", "ck_campfire_pending_write_kind"),
            ("origin", "not_an_origin", "ck_campfire_pending_write_origin"),
            ("state", "not_a_state", "ck_campfire_pending_write_state"),
        ):
            kwargs: dict[str, object] = {
                "kind": "memory_episode",
                "account_id": _ACCOUNT,
                "payload": {},
                "origin": "user_statement",
                "source": {},
            }
            kwargs[field] = bad_value
            with pytest.raises(IntegrityError, match=constraint):
                async with session_scope(get_settings()) as session:
                    session.add(PendingWrite(**kwargs))
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# 领取（原子性）与租约
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_claim_only_succeeds_once() -> None:
    """**并发领取只有一个成功**（第 4 节：不使用先查后改的无锁流程）。

    判别性：若实现是「先查 state 再改」，两个并发事务都会查到自己可领、都去改，
    于是**两个都返回记录**，本用例的「恰好一个成功」断言会失败。
    这里用两个独立会话（各自事务）模拟两个 Worker。
    """
    await _clear()
    try:
        pending_id = await _enqueue_memory()

        async def claim(owner: str) -> PendingWrite | None:
            async with session_scope(get_settings()) as session:
                return await take_for_processing(session, pending_id=pending_id, lease_owner=owner)

        results = await asyncio.gather(claim("worker-1"), claim("worker-2"))
        winners = [r for r in results if r is not None]
        assert len(winners) == 1, f"并发领取应恰好一个成功，实际 {len(winners)} 个"

        async with session_scope(get_settings()) as session:
            row = (await session.execute(select(PendingWrite).where(PendingWrite.id == pending_id))).scalar_one()
        assert row.state == STATE_PROCESSING
        assert row.lease_owner in {"worker-1", "worker-2"}
        assert row.lease_expires_at is not None
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_second_claim_fails_while_lease_is_live() -> None:
    """租约未过期时不能再领（否则同一条记忆会被抽取两次）。"""
    await _clear()
    try:
        pending_id = await _enqueue_memory()
        async with session_scope(get_settings()) as session:
            first = await take_for_processing(session, pending_id=pending_id, lease_owner="worker-1")
        assert first is not None

        async with session_scope(get_settings()) as session:
            second = await take_for_processing(session, pending_id=pending_id, lease_owner="worker-2")
        assert second is None, "租约有效期内不得重复领取"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_expired_lease_can_be_reclaimed_without_consuming_attempts() -> None:
    """**租约过期可重领，且不消耗 `attempts`**（Worker 崩溃不是「尝试失败」）。

    判别性：若回收时也 `attempts + 1`，反复崩溃会把一条健康记录耗成 `dead`。
    """
    await _clear()
    try:
        pending_id = await _enqueue_memory()
        base = datetime.now(timezone.utc)

        async with session_scope(get_settings()) as session:
            claimed = await take_for_processing(session, pending_id=pending_id, lease_owner="worker-1", now=base)
        assert claimed is not None

        # 租约到期后回收（显式传时间，保证确定性）。
        later = base + timedelta(seconds=LEASE_SECONDS_FOR_TEST + 1)
        async with session_scope(get_settings()) as session:
            reclaimed = await reclaim_expired_leases(session, now=later)
        assert pending_id in reclaimed

        async with session_scope(get_settings()) as session:
            row = (await session.execute(select(PendingWrite).where(PendingWrite.id == pending_id))).scalar_one()
        assert row.state == STATE_PENDING
        assert row.attempts == 0, "崩溃回收不得消耗重试预算"
        assert row.lease_owner is None

        # 回收后可立即领取（不设退避）。
        async with session_scope(get_settings()) as session:
            again = await take_for_processing(session, pending_id=pending_id, lease_owner="worker-2", now=later)
        assert again is not None
    finally:
        await _clear()


#: 与 `repository.LEASE_SECONDS` 同值；这里显式重述，避免测试直接依赖实现常量
#: （若实现改了租约时长，本用例仍按设计意图构造「已过期」的场景）。
LEASE_SECONDS_FOR_TEST = 300


# ---------------------------------------------------------------------------
# 完成与失败
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_done_clears_the_lease_and_sets_finished_at() -> None:
    """成功：置 `done`、记 `finished_at`、**清理租约**（第 4 节要求同一事务内清理）。"""
    await _clear()
    try:
        pending_id = await _enqueue_memory()
        async with session_scope(get_settings()) as session:
            await take_for_processing(session, pending_id=pending_id, lease_owner="worker-1")

        async with session_scope(get_settings()) as session:
            done = await mark_done(session, pending_id=pending_id)
        assert done.state == STATE_DONE
        assert done.finished_at is not None
        assert done.lease_owner is None, "完成后必须清租约，否则排查看不出归属"
        assert done.lease_expires_at is None
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_mark_done_twice_is_reported_not_silently_ignored() -> None:
    """重复标记终结**显式失败**——静默成功会让「刚才的 done 是谁标的」无从查起。"""
    await _clear()
    try:
        pending_id = await _enqueue_memory()
        async with session_scope(get_settings()) as session:
            await mark_done(session, pending_id=pending_id)
        async with session_scope(get_settings()) as session:
            with pytest.raises(PendingWriteNotFoundError, match="不可重复终结"):
                await mark_done(session, pending_id=pending_id)
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_retryable_failure_backs_off_and_increments_attempts() -> None:
    """可重试失败：`attempts + 1`、回 `pending`、按退避后移 `next_attempt_at`（第 6 节）。"""
    await _clear()
    try:
        pending_id = await _enqueue_memory()
        now = datetime.now(timezone.utc)

        async with session_scope(get_settings()) as session:
            failed = await mark_retryable_failure(session, pending_id=pending_id, error="模型超时", now=now)
        assert failed.state == STATE_PENDING
        assert failed.attempts == 1
        assert failed.last_error == "模型超时"
        assert failed.next_attempt_at is not None
        assert failed.next_attempt_at > now, "退避必须把重试时间推到将来"
        assert failed.lease_owner is None
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_backoff_pushes_retry_further_out_each_time() -> None:
    """退避**递增**（第 10 节曲线 1→2→4→8→16 分钟）。

    判别性：若实现把退避写死成常数，本用例的单调递增断言会失败。
    """
    await _clear()
    try:
        pending_id = await _enqueue_memory()
        now = datetime.now(timezone.utc)
        delays: list[float] = []
        for _ in range(3):
            async with session_scope(get_settings()) as session:
                row = await mark_retryable_failure(session, pending_id=pending_id, error="再试", now=now)
            assert row.next_attempt_at is not None
            delays.append((row.next_attempt_at - now).total_seconds())
        assert delays == sorted(delays) and len(set(delays)) == len(delays), f"退避应逐次递增，实际 {delays}"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_failure_beyond_max_attempts_becomes_dead() -> None:
    """**超过重试上限转 `dead`**（第 6 节：不得静默丢弃）。"""
    await _clear()
    try:
        pending_id = await _enqueue_memory()
        now = datetime.now(timezone.utc)
        row = None
        for _ in range(MAX_ATTEMPTS):
            async with session_scope(get_settings()) as session:
                row = await mark_retryable_failure(session, pending_id=pending_id, error="一直失败", now=now)
        assert row is not None
        assert row.state == STATE_DEAD, f"第 {MAX_ATTEMPTS} 次失败后应转 dead"
        assert row.attempts >= MAX_ATTEMPTS
        assert row.finished_at is not None
        assert row.last_error is not None

        # `dead` 是终结态：不能再被领取（否则会无限重试，违背上限的意义）。
        async with session_scope(get_settings()) as session:
            claimed = await take_for_processing(session, pending_id=pending_id, lease_owner="worker-1")
        assert claimed is None, "dead 记录不得再被领取"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_mark_dead_is_terminating_and_idempotent_is_reported() -> None:
    """`mark_dead` 也是终结态；重复终结显式失败。"""
    await _clear()
    try:
        pending_id = await _enqueue_memory()
        async with session_scope(get_settings()) as session:
            dead = await mark_dead(session, pending_id=pending_id, error="不可重试")
        assert dead.state == STATE_DEAD
        async with session_scope(get_settings()) as session:
            with pytest.raises(PendingWriteNotFoundError):
                await mark_dead(session, pending_id=pending_id, error="再来")
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_reclaim_is_bounded() -> None:
    """回收**有界**（CORE-11）：一次扫描不得无界更新。"""
    await _clear()
    try:
        base = datetime.now(timezone.utc)
        ids = [await _enqueue_memory() for _ in range(5)]
        # 全部领取，让租约生效。
        for index, pending_id in enumerate(ids):
            async with session_scope(get_settings()) as session:
                await take_for_processing(session, pending_id=pending_id, lease_owner=f"w{index}", now=base)

        later = base + timedelta(seconds=LEASE_SECONDS_FOR_TEST + 1)
        async with session_scope(get_settings()) as session:
            reclaimed = await reclaim_expired_leases(session, now=later, limit=2)
        assert len(reclaimed) == 2, f"limit=2 时应只回收 2 条，实际 {len(reclaimed)}"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_last_error_is_truncated_not_rejected() -> None:
    """超长错误摘要**截断**而不是报错：因摘要过长写入失败会连失败记录一起丢。"""
    await _clear()
    try:
        pending_id = await _enqueue_memory()
        async with session_scope(get_settings()) as session:
            row = await mark_retryable_failure(session, pending_id=pending_id, error="x" * 5000)
        assert row.last_error is not None
        assert len(row.last_error) <= 512
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_unfinished_states_are_not_treated_as_written() -> None:
    """**只有 `done` 算写入成功**：`pending` / `processing` / `failed` 都不算。

    这条把第 2 节的不变量写成可执行断言——它是整条异步写入链最容易被违反的一条
    （「已经排队了」很容易被当成「已经写好了」）。
    """
    await _clear()
    try:
        pending_id = await _enqueue_memory()
        async with session_scope(get_settings()) as session:
            row = (await session.execute(select(PendingWrite).where(PendingWrite.id == pending_id))).scalar_one()
        assert row.state != STATE_DONE

        async with session_scope(get_settings()) as session:
            await take_for_processing(session, pending_id=pending_id, lease_owner="w1")
            row = (await session.execute(select(PendingWrite).where(PendingWrite.id == pending_id))).scalar_one()
        assert row.state == STATE_PROCESSING
        assert row.finished_at is None

        async with session_scope(get_settings()) as session:
            failed = await mark_retryable_failure(session, pending_id=pending_id, error="失败")
        assert failed.state != STATE_DONE
        assert failed.finished_at is None
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_cleanup_leaves_no_rows() -> None:
    """自检：清理后本账号无残留（避免给其它测试留下脏数据）。"""
    await _clear()
    async with session_scope(get_settings()) as session:
        remaining = (
            await session.execute(
                select(func.count()).select_from(PendingWrite).where(PendingWrite.account_id == _ACCOUNT)
            )
        ).scalar_one()
    assert remaining == 0
