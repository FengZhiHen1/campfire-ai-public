"""集成测试：待处理写入记录的状态机与租约（真实 PostgreSQL）。

对应 `docs/技术设计/technical-details/写入路径.md` 第 3、4、5、6 节。这些事实是
数据库行为（条件更新、行锁、CHECK 约束），因此带 `integration` marker。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_pending_write_integration.py

锁住的是状态机的不变量，逐条对应设计：

1. 不变量：只有 `state = done` 算写入成功——新记录是 `pending`。
2. 领取是原子的（第 4 节「不使用先查后改的无锁流程」）：并发两次领取只有一个成功。
3. 租约过期可重领，且不消耗 `attempts`（Worker 崩溃不是「尝试失败」）。
4. 可重试失败按退避后移、`attempts + 1`（第 6 节）。
5. 超过上限转 `dead`（第 6 节：不得静默丢弃）。
6. 归属字段按 kind（第 3 节）：`memory_episode` 带对象、`profile_item` 缺对象
   都被存储层拒绝。
7. 词表落 CHECK：非法 `kind`/`origin`/`state` 被存储层拒绝。
8. 词表与库内约束一致：库内 `origin` CHECK 的取值集合必须等于模型 `ORIGINS`。
   alembic 的 autogenerate 不比对 CHECK 约束，缺了这条守护，两侧漂移只会在运行期
   表现为「契约能传、存储拒收」。
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text, update

from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.core.pending_write import (
    MAX_ATTEMPTS,
    ORIGINS,
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
    """未配置 `DATABASE_URL` 时跳过——不假装通过（仓库既有集成测试的统一做法）。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


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
    """不变量：新记录是 `pending`——「没写进去」不得被当作「写进去了」。"""
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
    """归属字段按 kind 的判据（第 3 节）在应用层入口也提前拒绝。

    真正的判据在存储层 CHECK（见下一条用例）；这里验证应用层给出可读的错误，
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
    """存储层拒绝「记忆带支持对象」——这是第 3 节要求的硬判据。

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
    """`kind` / `origin` / `state` 的词表判据落在 CHECK 约束上。"""
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
# 词表与库内约束的一致性（alembic 不比对 CHECK，这类漂移只能靠测试守）
# ---------------------------------------------------------------------------


async def _origin_check_definition() -> str:
    """读库内 `origin` CHECK 的定义原文。

    用裸 SQL 而不是 ORM：被测的是存储层事实，经 ORM 读到的只会是模型自己的声明。
    """
    async with session_scope(get_settings()) as session:
        return (
            await session.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = 'campfire_pending_write'::regclass "
                    "AND conname = 'ck_campfire_pending_write_origin'"
                )
            )
        ).scalar_one()


@pytest.mark.asyncio
async def test_database_origin_check_matches_the_model_vocabulary() -> None:
    """库内 `origin` CHECK 的取值集合 `==` 模型 `ORIGINS`（集合相等，不是子集）。

    为什么必须显式守：alembic 的 autogenerate 不比对 CHECK 约束（给既有表改约束时
    它产出空操作，见 `760b797c8bab` 与 `711fc22a40fd` 的说明），因此「模型加了取值、
    库内 CHECK 不认」这类漂移在 `alembic check` 里是隐形的，只在运行期表现为写入被拒。

    判别性：往 `ORIGINS` 增删一个取值而不同步迁移，本用例失败；把库内 CHECK 退回四值，
    同样失败——集合相等会同时暴露「多值」与「少值」两个方向。
    """
    stored = set(re.findall(r"'([^']*)'", await _origin_check_definition()))
    assert stored == set(ORIGINS), (
        f"库内 origin CHECK 与模型 ORIGINS 不一致：库内={sorted(stored)}，模型={sorted(ORIGINS)}"
        "；不一致会让契约能传的取值被存储层拒收（现象是工具失败，调用方读不到原因）"
    )


@pytest.mark.parametrize("origin", ["document", "third_party_report"])
@pytest.mark.asyncio
async def test_origins_added_by_the_contract_actually_land(origin: str) -> None:
    """`document` / `third_party_report` 真的能落库（六值里的后两个）。

    单独测这两个的原因：库内 CHECK 只接受四值时被拒的正是它们，而拒绝表现为
    `propose_profile_item` 的 `tool_failed`（`tools/profile.py` 的 `except Exception`
    分支，那是有意的：写入失败不得回执 submitted）——调用方读不到「是约束不接受」。
    断言到回读 `origin` 相等而不是「没抛异常」：只有真读回来才证明它进了库。
    """
    await _clear()
    try:
        async with session_scope(get_settings()) as session:
            record = await enqueue(
                session,
                kind="memory_episode",
                account_id=_ACCOUNT,
                origin=origin,
                payload={"content": f"{origin} 的探针内容"},
                source={"session_id": "s-origin-vocab", "message_seq": 1},
            )
            pending_id = record.id

        async with session_scope(get_settings()) as session:
            row = (await session.execute(select(PendingWrite).where(PendingWrite.id == pending_id))).scalar_one()
        assert row.origin == origin
        assert row.state == STATE_PENDING
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# 领取（原子性）与租约
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_claim_only_succeeds_once() -> None:
    """并发领取只有一个成功（第 4 节：不使用先查后改的无锁流程）。

    判别性：若实现是「先查 state 再改」，两个并发事务都会查到自己可领、都去改，
    于是两个都返回记录，本用例的「恰好一个成功」断言会失败。
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
    """租约过期可重领，且不消耗 `attempts`（Worker 崩溃不是「尝试失败」）。

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
    """成功：置 `done`、记 `finished_at`、清理租约（第 4 节要求同一事务内清理）。"""
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
    """重复标记终结显式失败——静默成功会让「刚才的 done 是谁标的」无从查起。"""
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
async def test_concurrent_retryable_failures_each_increment_attempts() -> None:
    """并发两次失败各记一次：最终 `attempts == 2`，不是 1（读-改-写会互相覆盖）。

    为什么必须有这条（2026-09-30 评审补矩阵空格）：`mark_retryable_failure` 的自增
    用 SQL 表达式（`attempts = attempts + 1`）而不是先读再写——后者在两个独立事务
    并发失败时会都读到旧值、各写回 +1，最终丢一次计数。丢计数会让「是否超过
    重试上限」的判定提前或延后成立，dead 的语义随之漂移。

    判别性：把自增改成「SELECT 后在 Python 侧 +1 再 UPDATE」，两个并发事务提交后
    的终值是 1（或 2，取决于时序）——本用例的 `== 2` 断言会失败。
    """
    await _clear()
    try:
        pending_id = await _enqueue_memory()

        async def fail_once() -> None:
            async with session_scope(get_settings()) as session:
                await mark_retryable_failure(session, pending_id=pending_id, error="并发失败")

        await asyncio.gather(fail_once(), fail_once())

        async with session_scope(get_settings()) as session:
            row = (await session.execute(select(PendingWrite).where(PendingWrite.id == pending_id))).scalar_one()
        assert row.attempts == 2, f"并发两次失败应各记一次（attempts==2），实际 {row.attempts}"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_backoff_pushes_retry_further_out_each_time() -> None:
    """退避递增（第 10 节曲线 1→2→4→8→16 分钟）。

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
    """超过重试上限转 `dead`（第 6 节：不得静默丢弃）。"""
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
    """回收有界（CORE-11）：一次扫描不得无界更新。"""
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
    """超长错误摘要截断而不是报错：因摘要过长写入失败会连失败记录一起丢。"""
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
    """只有 `done` 算写入成功：`pending` / `processing` / `failed` 都不算。

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
async def test_reclaim_does_not_revive_a_terminated_record() -> None:
    """回收不得把已终结的记录改回 `pending`（2026-09-29 评审 C-2，实测复现）。

    缺陷：`reclaim_expired_leases` 的 `SELECT`（选候选）与 `UPDATE`（改状态）之间是真实
    窗口，而 `UPDATE` 此前没有 state 守卫。若另一事务在窗口内把记录置成 `done`，
    回收会把它改回 `pending`（且 `finished_at` 仍保留，形成 `pending` + `finished_at`
    非空的自相矛盾行），随后被再次领取——同一条记忆抽取两次。

    怎么做到确定性复现：这是一个多语句窗口，单纯「先置 done 再回收」是测不出的
    （`SELECT` 本来就只选 `processing`，压根不会把 done 选进来——我第一版就是这么写的，
    消融验证它不判别）。因此这里用 SQL 事件钩子在回收的 UPDATE 语句执行前把该行改成
    `done`，精确模拟「另一个事务在窗口内提交了终结」这一时序，从而真正走到那条 UPDATE。

    判别性：去掉 `UPDATE` 的 `PendingWrite.state == STATE_PROCESSING` 守卫，本用例失败
    （记录被改回 `pending`）。
    """
    from sqlalchemy import event

    from campfire.core.db import get_engine

    await _clear()
    try:
        base = datetime.now(timezone.utc)
        pending_id = await _enqueue_memory()
        # 制造「租约已过期」的 processing 行——它会进入回收的候选集。
        async with session_scope(get_settings()) as session:
            await take_for_processing(session, pending_id=pending_id, lease_owner="A", now=base)

        later = base + timedelta(seconds=LEASE_SECONDS_FOR_TEST + 1)
        engine = get_engine(get_settings())
        fired = {"count": 0}

        def _terminate_right_before_reclaim(conn, _cursor, statement, _params, _ctx, _many):  # noqa: ANN001
            """在本用例那条回收 UPDATE 执行前，模拟另一事务把它终结。

            必须按 id 过滤：`before_cursor_execute` 是引擎级钩子，同文件内其它测试
            的 UPDATE 也会触发它（第一版没过滤，全量跑时误命中别的语句而失败，
            单跑却通过——典型的「只在自己那条语句上成立」的陷阱）。
            """
            normalized = " ".join(str(statement).split()).upper()
            if (
                fired["count"] == 0
                and normalized.startswith("UPDATE CAMPFIRE_PENDING_WRITE")
                and "SET STATE" in normalized
            ):
                fired["count"] += 1
                # asyncpg 的占位符是 `$1`（不是 `%s`）。
                conn.exec_driver_sql(
                    "UPDATE campfire_pending_write SET state = 'done', finished_at = now() WHERE id = $1",
                    (str(pending_id),),
                )

        event.listen(engine.sync_engine, "before_cursor_execute", _terminate_right_before_reclaim)
        try:
            async with session_scope(get_settings()) as session:
                reclaimed = await reclaim_expired_leases(session, now=later)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", _terminate_right_before_reclaim)

        assert fired["count"] == 1, "钩子未触发——本用例没有真的走到回收的 UPDATE（断言会失去判别力）"

        async with session_scope(get_settings()) as session:
            row = (await session.execute(select(PendingWrite).where(PendingWrite.id == pending_id))).scalar_one()
        assert row.state == STATE_DONE, f"已 done 的记录被回收改成了 {row.state!r}——它会被再次领取，同一记忆抽取两次"
        assert pending_id not in reclaimed, "被终结的记录不得出现在回收结果里"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_lease_fence_rejects_a_late_writer() -> None:
    """迟到响应不得改变状态（CORE-03；2026-09-29 评审 C-3，实测复现）。

    序列：A 领取 → 租约过期 → B 重领 → A 迟到调 `mark_done`。
    缺陷：`mark_done` 此前不比对 `lease_owner`，A 会抢先成功，而真正写入者 B 的终结
    反而抛 `PendingWriteNotFoundError`——制造一个假失败。

    判别性：去掉 `mark_done` 的 `lease_owner` 栅栏，本用例的第一段断言失败。
    """
    await _clear()
    try:
        base = datetime.now(timezone.utc)
        pending_id = await _enqueue_memory()

        async with session_scope(get_settings()) as session:
            await take_for_processing(session, pending_id=pending_id, lease_owner="A", now=base)

        later = base + timedelta(seconds=LEASE_SECONDS_FOR_TEST + 1)
        async with session_scope(get_settings()) as session:
            await reclaim_expired_leases(session, now=later)
        async with session_scope(get_settings()) as session:
            claimed = await take_for_processing(session, pending_id=pending_id, lease_owner="B", now=later)
        assert claimed is not None and claimed.lease_owner == "B"

        # A 迟到终结 → 必须被拒。
        async with session_scope(get_settings()) as session:
            with pytest.raises(PendingWriteNotFoundError):
                await mark_done(session, pending_id=pending_id, lease_owner="A")

        # B 的终结仍必须成功（真写入者不被迟到者挤掉）。
        async with session_scope(get_settings()) as session:
            done = await mark_done(session, pending_id=pending_id, lease_owner="B")
        assert done.state == STATE_DONE

        # 不带栅栏时不校验持有者（兼容既有调用方）。
        async with session_scope(get_settings()) as session:
            with pytest.raises(PendingWriteNotFoundError):
                await mark_done(session, pending_id=pending_id)
    finally:
        await _clear()


async def _claim_by_two_workers(pending_id: uuid.UUID) -> datetime:
    """A 领取（已提交）→ 租约过期 → B 重领（已提交），返回 B 的参照时间。"""
    base = datetime.now(timezone.utc)
    async with session_scope(get_settings()) as session:
        assert await take_for_processing(session, pending_id=pending_id, lease_owner="A", now=base) is not None
    later = base + timedelta(seconds=LEASE_SECONDS_FOR_TEST + 1)
    async with session_scope(get_settings()) as session:
        assert await take_for_processing(session, pending_id=pending_id, lease_owner="B", now=later) is not None
    return later


@pytest.mark.asyncio
async def test_late_failure_cannot_steal_another_workers_lease() -> None:
    """A 的迟到失败登记不得把 B 正在处理的记录改回 `pending`。

    判别性：旧的（无栅栏）实现会把状态改回 `pending`、清掉 B 的租约、`attempts + 1`
    ——本用例的「状态/租约/attempts/退避全部不变」断言随之失败。
    """
    await _clear()
    try:
        pending_id = await _enqueue_memory()
        later = await _claim_by_two_workers(pending_id)

        async with session_scope(get_settings()) as session:
            with pytest.raises(PendingWriteNotFoundError):
                await mark_retryable_failure(
                    session, pending_id=pending_id, error="A 的迟到失败", lease_owner="A", now=later
                )

        async with session_scope(get_settings()) as session:
            row = (await session.execute(select(PendingWrite).where(PendingWrite.id == pending_id))).scalar_one()
        assert row.state == STATE_PROCESSING
        assert row.lease_owner == "B", "迟到失败不得清掉别人的租约"
        assert row.attempts == 0, "迟到失败不得消耗别人的重试预算"
        assert row.next_attempt_at is None
        assert row.last_error is None

        # 真写入者 B 的终结仍然成立。
        async with session_scope(get_settings()) as session:
            assert (await mark_done(session, pending_id=pending_id, lease_owner="B")).state == STATE_DONE
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_retry_exhaustion_keeps_the_lease_fence() -> None:
    """重试耗尽的分支也必须守同一栅栏：迟到失败不得把 B 的记录直接置 `dead`。

    判别性：若耗尽分支调 `mark_dead` 时不带 `lease_owner`，A 会终结 B 的记录
    （B 的写入从此没有记录可对账），`state == processing` 的断言失败。
    """
    await _clear()
    try:
        pending_id = await _enqueue_memory()
        later = await _claim_by_two_workers(pending_id)
        # 让「下一次失败」正好触顶（B 的租约仍在，归属 B）。
        async with session_scope(get_settings()) as session:
            await session.execute(
                update(PendingWrite).where(PendingWrite.id == pending_id).values(attempts=MAX_ATTEMPTS - 1)
            )

        async with session_scope(get_settings()) as session:
            with pytest.raises(PendingWriteNotFoundError):
                await mark_retryable_failure(
                    session, pending_id=pending_id, error="A 的迟到失败", lease_owner="A", now=later
                )
        async with session_scope(get_settings()) as session:
            row = (await session.execute(select(PendingWrite).where(PendingWrite.id == pending_id))).scalar_one()
        assert row.state == STATE_PROCESSING, "迟到失败不得把别人的记录转 dead"
        assert row.lease_owner == "B"
        assert row.attempts == MAX_ATTEMPTS - 1

        # 真正的持有者 B 的第 MAX 次失败 → 转 dead。
        async with session_scope(get_settings()) as session:
            dead = await mark_retryable_failure(
                session, pending_id=pending_id, error="真失败", lease_owner="B", now=later
            )
        assert dead.state == STATE_DEAD
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_late_dead_cannot_terminate_another_workers_record() -> None:
    """迟到的不可重试判定（`mark_dead`）同样不得终结别人持有的记录。"""
    await _clear()
    try:
        pending_id = await _enqueue_memory()
        later = await _claim_by_two_workers(pending_id)

        async with session_scope(get_settings()) as session:
            with pytest.raises(PendingWriteNotFoundError):
                await mark_dead(session, pending_id=pending_id, error="A 的迟到终结", lease_owner="A", now=later)

        async with session_scope(get_settings()) as session:
            row = (await session.execute(select(PendingWrite).where(PendingWrite.id == pending_id))).scalar_one()
        assert row.state == STATE_PROCESSING
        assert row.lease_owner == "B"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_failure_registration_survives_a_rolled_back_consume_transaction() -> None:
    """消费事务回滚后的失败登记必须照常生效（真实 worker 的调用形状）。

    领取与写入同在一个事务里，失败即整笔回滚 ⇒ 库里是回滚前的 `pending`、
    `lease_owner IS NULL`；失败登记随后在**新事务**里带自己的 `lease_owner` 调用。
    判别性：若栅栏写成「必须 `processing` 且属主相符」，本用例抛
    `PendingWriteNotFoundError`——真实重试链路会永久卡在 `pending`：不增
    `attempts`、永不进 `dead`、也不告警。
    """
    await _clear()
    try:
        pending_id = await _enqueue_memory()
        with pytest.raises(RuntimeError):
            async with session_scope(get_settings()) as session:
                assert await take_for_processing(session, pending_id=pending_id, lease_owner="A") is not None
                raise RuntimeError("模拟写入阶段失败（整笔回滚）")

        async with session_scope(get_settings()) as session:
            row = (await session.execute(select(PendingWrite).where(PendingWrite.id == pending_id))).scalar_one()
        assert row.state == STATE_PENDING and row.lease_owner is None, "回滚后应回到回滚前的 pending"

        async with session_scope(get_settings()) as session:
            failed = await mark_retryable_failure(session, pending_id=pending_id, error="模型超时", lease_owner="A")
        assert failed.state == STATE_PENDING
        assert failed.attempts == 1
        assert failed.next_attempt_at is not None
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_terminal_states_clear_next_attempt_at() -> None:
    """终态必须清掉 `next_attempt_at`（2026-09-29 评审 C-6）。

    留着过期的退避时刻会让排查误判「这条还会重试」。覆盖 `done` 与 `dead` 两条路径。
    """
    await _clear()
    try:
        # done 路径：先失败一次（设了退避），再把时间推到退避之后重新领取并成功。
        # 两个要点：① `mark_retryable_failure` 会清掉租约（回 pending 等退避），
        # 所以必须重新领取；② `next_attempt_at` 在退避期内会正确地挡住领取，
        # 因此 `now` 要越过退避（1 分钟）。
        first = await _enqueue_memory()
        base = datetime.now(timezone.utc)
        async with session_scope(get_settings()) as session:
            await take_for_processing(session, pending_id=first, lease_owner="w", now=base)
        async with session_scope(get_settings()) as session:
            await mark_retryable_failure(session, pending_id=first, error="临时失败", now=base)
        after_backoff = base + timedelta(minutes=5)
        async with session_scope(get_settings()) as session:
            await take_for_processing(session, pending_id=first, lease_owner="w", now=after_backoff)
        async with session_scope(get_settings()) as session:
            done = await mark_done(session, pending_id=first, lease_owner="w", now=after_backoff)
        assert done.next_attempt_at is None, "done 是终态，不得留下退避时刻"

        # dead 路径：先失败一次（设了退避），再转 dead。
        second = await _enqueue_memory()
        async with session_scope(get_settings()) as session:
            await take_for_processing(session, pending_id=second, lease_owner="w2", now=base)
        async with session_scope(get_settings()) as session:
            await mark_retryable_failure(session, pending_id=second, error="临时失败", now=base)
        async with session_scope(get_settings()) as session:
            dead = await mark_dead(session, pending_id=second, error="放弃", now=base)
        assert dead.next_attempt_at is None, "dead 是终态，不得留下退避时刻"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_enqueue_rejects_an_overlong_account_id() -> None:
    """超长 `account_id` 必须给出领域异常，而不是裸 `DBAPIError`（C-4）。

    缺陷（2026-09-29 评审 C-4 实测）：`enqueue` 此前只判空，129 字符会一路走到 INSERT
    才由 PostgreSQL 抛 `DBAPIError`——调用方拿到驱动异常，也看不出哪个字段超宽。
    """
    await _clear()
    try:
        async with session_scope(get_settings()) as session:
            with pytest.raises(InsufficientPayloadError, match="字符上界"):
                await enqueue(
                    session,
                    kind="memory_episode",
                    account_id="a" * 129,
                    origin="user_statement",
                    payload={"content": "x", "occurred_at": datetime.now(timezone.utc).isoformat()},
                    source={"session_id": "s"},
                )
        # 恰好 128 应被接受（边界闭区间）。用独立会话，且直接清理该行。
        exact = "a" * 128
        async with session_scope(get_settings()) as session:
            await enqueue(
                session,
                kind="memory_episode",
                account_id=exact,
                origin="user_statement",
                payload={"content": "x", "occurred_at": datetime.now(timezone.utc).isoformat()},
                source={"session_id": "s"},
            )
        async with session_scope(get_settings()) as session:
            count = (
                await session.execute(
                    select(func.count()).select_from(PendingWrite).where(PendingWrite.account_id == exact)
                )
            ).scalar_one()
        assert count == 1, "恰好 128 字符的 account_id 应能落库"
        async with session_scope(get_settings()) as session:
            await session.execute(delete(PendingWrite).where(PendingWrite.account_id == exact))
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_reclaim_limit_is_converged_to_a_server_cap() -> None:
    """回收的 `limit` 必须收敛到服务端上界（CORE-11；2026-09-29 评审 R-3）。

    缺陷：此前只做 `max(1, limit)`，没有上界——实测 `limit=10**9` 被原样放进 SQL。
    同仓 `store.read_timeline` 与 `derived.read_emergency_facts` 都已收敛，回收漏了。

    判别性：去掉 `min(limit, RECLAIM_MAX_LIMIT)`，本用例的 SQL 参数断言失败。
    """
    from campfire.core.pending_write.repository import RECLAIM_MAX_LIMIT

    await _clear()
    try:
        base = datetime.now(timezone.utc)
        pending_id = await _enqueue_memory()
        async with session_scope(get_settings()) as session:
            await take_for_processing(session, pending_id=pending_id, lease_owner="w", now=base)

        later = base + timedelta(seconds=LEASE_SECONDS_FOR_TEST + 1)

        # 拦截实际发给数据库的 LIMIT。逐条记下 (语句, 参数)：语句用来筛出回收那条
        # SELECT，参数用来断言 LIMIT 真的被收敛。参数类型收窄到「映射或序列」——
        # SQLAlchemy 两种形态都可能传，`object` 则连索引都不允许。
        captured: list[tuple[str, Mapping[str, object] | Sequence[object]]] = []
        from sqlalchemy import event

        from campfire.core.db import get_engine

        engine = get_engine(get_settings())

        def _before_execute(_conn, _cursor, statement, parameters, _context, _many):  # noqa: ANN001
            captured.append((statement, parameters))

        event.listen(engine.sync_engine, "before_cursor_execute", _before_execute)
        try:
            async with session_scope(get_settings()) as session:
                await reclaim_expired_leases(session, now=later, limit=10**9)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", _before_execute)

        select_params = [p for s, p in captured if "campfire_pending_write" in str(s) and "LIMIT" in str(s).upper()]
        assert select_params, "未捕获到回收的 SELECT"
        supplied = select_params[0]
        # 字典形态按参数名取，元组形态取末位（编译后的 SQL 里 LIMIT 是最后一个占位符）。
        limit_value = supplied.get("param_1") if isinstance(supplied, Mapping) else supplied[-1]
        assert limit_value == RECLAIM_MAX_LIMIT, f"limit=10**9 应被收敛为 {RECLAIM_MAX_LIMIT}，实际传入 {limit_value!r}"
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
