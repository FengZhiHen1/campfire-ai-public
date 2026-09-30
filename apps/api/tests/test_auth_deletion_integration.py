"""账号注销编排的行为（真实 PostgreSQL）。

对应 ``docs/技术设计/technical-challenges/认证与账号.md`` 第 8 节与
``docs/技术设计/decisions/账号注销与墓碑.md``。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_auth_deletion_integration.py

## 逐条对应设计

1. **五步顺序不可调换**：墓碑必须先写——否则中间窗口内的消费会把数据写回已注销账号。
2. **必须先确认**（``confirmed=True``）：注销不可逆，默认 ``False`` 意味着
   「忘了传就拒绝执行」，方向安全。
3. **任一步失败即整体失败**，且异常携带**已完成到哪一步**——注销不可逆，
   操作者需要知道当前状态才能决定重试还是人工介入。
4. **重试安全**：墓碑幂等，重跑会看到「已存在」并继续完成后续步骤。
5. **只删未领取的待处理记录**：``processing`` 的放过（可能正被 Worker 持有），
   由 Worker 按墓碑丢弃。
6. **执行顺序**：用假实现记录调用序，断言墓碑确实先于身份删除与领域清除。

本文件用**假的** ``revoke_all_sessions`` / ``delete_identity_user`` / purger
——编排只关心顺序与失败语义，不需要真实 core（那需要 supertokens 容器，
而这里要钉的是编排本身的契约）。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from campfire.core.auth import (
    AccountDeletionError,
    AccountDeletionTombstone,
    PurgeOutcome,
    delete_account,
)
from campfire.core.auth.tombstone_repository import get_tombstone
from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.core.pending_write import STATE_PENDING, STATE_PROCESSING, PendingWrite, enqueue

pytestmark = pytest.mark.integration

#: 本文件的账号前缀。
_ACCOUNT = "it_deletion_account"


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——**不假装通过**。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


async def _clear() -> None:
    """清掉本文件写入的行（按前缀收窄，避免删到别的测试文件的码）。"""
    async with session_scope(get_settings()) as session:
        await session.execute(
            delete(AccountDeletionTombstone).where(AccountDeletionTombstone.account_id.like(f"{_ACCOUNT}%"))
        )
        await session.execute(delete(PendingWrite).where(PendingWrite.account_id.like(f"{_ACCOUNT}%")))


def _account(suffix: str = "") -> str:
    """生成唯一的账号标识（**必须唯一**：墓碑是主键，复用会让「首次写入」变成「已存在」）。"""
    return f"{_ACCOUNT}_{suffix}{uuid.uuid4().hex[:8]}"


class _Recorder:
    """记录调用顺序的假实现（会话撤销、身份删除、领域清除）。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def revoke_all_sessions(self, account_id: str) -> None:
        self.calls.append(f"revoke_sessions:{account_id}")

    async def delete_identity_user(self, account_id: str) -> None:
        self.calls.append(f"delete_user:{account_id}")


class _FakePurger:
    """假的领域清除者。

    ``name`` 用于多清除者用例里区分「哪一个」：同类两个实例须能分辨，
    步骤名带该名（见 :func:`test_partial_purger_failure_reports_completed_purger`）。
    """

    def __init__(self, recorder: _Recorder, fail: bool = False, name: str | None = None) -> None:
        self._recorder = recorder
        self._fail = fail
        #: 公开属性 ``name``：编排从它取步骤名（缺省回退类名），与
        #: ``PurgeOutcome.name`` 同源。
        self.name = name or type(self).__name__

    async def purge_account(self, account_id: str) -> PurgeOutcome:
        """记录一次清除；`fail=True` 时抛错（用于验证失败语义）。"""
        self._recorder.calls.append(f"purge:{self.name}:{account_id}")
        if self._fail:
            raise RuntimeError("模拟领域清除失败")
        return PurgeOutcome(name=self.name, detail="已清除")


async def _enqueue(account_id: str, *, state: str = STATE_PENDING) -> uuid.UUID:
    """入队一条待处理记录，可指定状态。"""
    async with session_scope(get_settings()) as session:
        record = await enqueue(
            session,
            kind="memory_episode",
            account_id=account_id,
            origin="user_statement",
            payload={"content": "x", "occurred_at": datetime.now(timezone.utc).isoformat()},
            source={"session_id": "s1"},
        )
        if state != STATE_PENDING:
            record.state = state
        return record.id


# ---------------------------------------------------------------------------
# 确认与顺序
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deletion_requires_explicit_confirmation() -> None:
    """**未确认即拒绝**，且**什么也没做**（墓碑都没写）。

    判别性：默认 ``confirmed=False`` 让「忘了传」变成拒绝而不是执行——
    注销不可逆，方向必须安全。
    """
    await _clear()
    account = _account("noconfirm")
    recorder = _Recorder()
    try:
        async with session_scope(get_settings()) as session:
            with pytest.raises(AccountDeletionError, match="未确认"):
                await delete_account(
                    session,
                    account_id=account,
                    revoke_all_sessions=recorder.revoke_all_sessions,
                    delete_identity_user=recorder.delete_identity_user,
                )

        # 关键：拒绝时不得留下任何副作用。
        assert recorder.calls == [], "未确认的注销不得触碰会话或身份服务"
        async with session_scope(get_settings()) as session:
            assert await get_tombstone(session, account_id=account) is None, "未确认的注销连墓碑都不该写"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_tombstone_is_written_before_any_other_step() -> None:
    """**墓碑先于一切**（第 8 节「顺序不可调换」）。

    判据是**读库时序**而不是调用顺序：在撤销会话的那一刻，墓碑必须**已经落库**。
    做法是让假的 ``revoke_all_sessions`` 在**被调用时**去查墓碑——那一刻查得到，
    就证明它先写了。

    判别性：把第 1 步与第 3 步对调，本用例失败。
    """
    await _clear()
    account = _account("order")
    observed: dict[str, bool] = {}

    async def revoke_and_probe(account_id: str) -> None:
        """撤销会话时顺手查墓碑——它必须已存在。"""
        async with session_scope(get_settings()) as session:
            observed["tombstone_present"] = await get_tombstone(session, account_id=account_id) is not None

    try:
        async with session_scope(get_settings()) as session:
            report = await delete_account(
                session,
                account_id=account,
                revoke_all_sessions=revoke_and_probe,
                delete_identity_user=_Recorder().delete_identity_user,
                confirmed=True,
            )

        assert observed.get("tombstone_present") is True, (
            "撤销会话时墓碑还不存在——顺序被调换了；中间窗口内的 Worker 消费会把数据写回已注销账号的图（删后复活）"
        )
        assert report.completed_steps[0] == "写墓碑", f"第一步必须是写墓碑，实际 {report.completed_steps}"
        assert report.tombstone_created is True
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# 待处理记录：只删未领取的
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deletes_unclaimed_pending_writes_but_keeps_in_flight() -> None:
    """**只删未领取的**：``pending`` 删、``processing`` 留（可能正被 Worker 持有）。

    留下的那条由 Worker 按墓碑丢弃（`modules/memory/consumer` 已实现）——
    这就是「墓碑先写」与「只删未领取」两条设计共同构成的完整处置。
    """
    await _clear()
    account = _account("pending")
    pending_id = await _enqueue(account, state=STATE_PENDING)
    in_flight_id = await _enqueue(account, state=STATE_PROCESSING)
    recorder = _Recorder()
    try:
        async with session_scope(get_settings()) as session:
            report = await delete_account(
                session,
                account_id=account,
                revoke_all_sessions=recorder.revoke_all_sessions,
                delete_identity_user=recorder.delete_identity_user,
                confirmed=True,
            )

        assert report.pending_writes_deleted == 1, f"应只删 1 条未领取记录，实际 {report.pending_writes_deleted}"

        async with session_scope(get_settings()) as session:
            remaining = list(
                (await session.execute(select(PendingWrite.id).where(PendingWrite.account_id == account))).scalars()
            )
        assert remaining == [in_flight_id], "被领取中的记录必须留下，由 Worker 按墓碑丢弃"
        assert pending_id not in remaining, "未领取的记录必须被删掉"
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# 失败语义：整体失败 + 报告已完成到哪一步
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failure_reports_completed_steps() -> None:
    """任一步失败即整体失败，且异常**携带已完成步骤**（不可逆操作需要这个信息）。

    判别性：没有这个信息，操作者面对「注销失败了」无法判断该重试还是人工介入。
    """
    await _clear()
    account = _account("failstep")
    recorder = _Recorder()

    async def failing_delete_user(account_id: str) -> None:
        raise RuntimeError("模拟身份服务故障")

    try:
        async with session_scope(get_settings()) as session:
            with pytest.raises(AccountDeletionError) as excinfo:
                await delete_account(
                    session,
                    account_id=account,
                    revoke_all_sessions=recorder.revoke_all_sessions,
                    delete_identity_user=failing_delete_user,
                    confirmed=True,
                )

        error = excinfo.value
        assert error.step == "删除身份用户"
        assert "写墓碑" in error.completed, f"应报告墓碑已完成，实际 {error.completed}"
        assert "撤销全部会话" in error.completed
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_purger_failure_fails_the_whole_deletion() -> None:
    """**领域清除失败 → 整体失败**（不得静默通过）。

    判别性：若吞掉 purger 的异常，注销会报告成功，而「内容真删」并未达成——
    那正是 `RQ-MEM-03` 的删除语义被违反的方式。
    """
    await _clear()
    account = _account("purgefail")
    recorder = _Recorder()
    try:
        async with session_scope(get_settings()) as session:
            with pytest.raises(AccountDeletionError, match="清除"):
                await delete_account(
                    session,
                    account_id=account,
                    revoke_all_sessions=recorder.revoke_all_sessions,
                    delete_identity_user=recorder.delete_identity_user,
                    purgers=[_FakePurger(recorder, fail=True)],
                    confirmed=True,
                )
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_partial_purger_failure_reports_completed_purger() -> None:
    """**多个清除者中第 2 个失败时，第 1 个的完成必须出现在报告里**。

    ## 背景（2026-10-01 审查修正的回归测试）

    修复前第 5 步只在**全部** purger 成功后追加一条「领域清除」——第 2 个失败时，
    第 1 个已真实执行却不出现在 ``completed``。操作者据「重试安全」重跑时无法从
    报告区分哪个领域已清过；purger 幂等让重跑无害，但报告必须与事实一致。

    判别性：把 ``completed.append`` 改回循环外（旧实现），本用例失败——
    ``error.completed`` 里没有任何「领域清除」条目。
    """
    await _clear()
    account = _account("partial")
    recorder = _Recorder()
    first = _FakePurger(recorder, name="first")
    second = _FakePurger(recorder, name="second", fail=True)
    try:
        async with session_scope(get_settings()) as session:
            with pytest.raises(AccountDeletionError) as excinfo:
                await delete_account(
                    session,
                    account_id=account,
                    revoke_all_sessions=recorder.revoke_all_sessions,
                    delete_identity_user=recorder.delete_identity_user,
                    purgers=[first, second],
                    confirmed=True,
                )

        error = excinfo.value
        # 失败步骤点名第 2 个清除者；第 1 个的完成被如实记录。
        assert "second" in error.step, f"失败步骤应点名失败的清除者，实际 {error.step!r}"
        assert any("first" in step for step in error.completed), (
            f"第 1 个清除者已完成，必须出现在 completed 里，实际 {error.completed}"
        )
        assert not any("second" in step for step in error.completed), "失败的清除者不得出现在 completed 里"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_retry_is_safe_and_reports_existing_tombstone() -> None:
    """**重试安全**：墓碑幂等，重跑报告「已存在」并继续完成后续步骤。

    这是必要的：任一步失败后，操作者唯一合理的动作就是修好原因再重试。
    判别性：若第二次调用因主键冲突抛错，重试路径会把「其实已经写好了」当作失败，
    操作者会去排查一个不存在的问题。
    """
    await _clear()
    account = _account("retry")
    recorder = _Recorder()
    first_deleted_at: list[object] = []
    try:
        async with session_scope(get_settings()) as session:
            first = await delete_account(
                session,
                account_id=account,
                revoke_all_sessions=recorder.revoke_all_sessions,
                delete_identity_user=recorder.delete_identity_user,
                confirmed=True,
            )
        # 记下首次的注销时间，用于验证重跑不改写它。
        async with session_scope(get_settings()) as session:
            row = await get_tombstone(session, account_id=account)
            assert row is not None
            first_deleted_at.append(row.deleted_at)

        async with session_scope(get_settings()) as session:
            second = await delete_account(
                session,
                account_id=account,
                revoke_all_sessions=recorder.revoke_all_sessions,
                delete_identity_user=recorder.delete_identity_user,
                confirmed=True,
            )

        assert first.tombstone_created is True
        assert second.tombstone_created is False, "重试必须报告「墓碑此前已存在」"
        assert "删除身份用户" in second.completed_steps

        # 墓碑仍只有一行（主键保证），且**注销时间未被改写**——它是一次不可变事实。
        async with session_scope(get_settings()) as session:
            rows = list(
                (
                    await session.execute(
                        select(AccountDeletionTombstone).where(AccountDeletionTombstone.account_id == account)
                    )
                ).scalars()
            )
        assert len(rows) == 1, f"同一账号不得有第二行墓碑（实际 {len(rows)}）"
        assert rows[0].deleted_at == first_deleted_at[0], "重跑改写了注销时间——它是不可变事实"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_purge_outcomes_are_reported() -> None:
    """领域清除的结果被**如实汇总**进报告（运维需要知道实际删了什么）。"""
    await _clear()
    account = _account("purgeok")
    recorder = _Recorder()
    try:
        async with session_scope(get_settings()) as session:
            report = await delete_account(
                session,
                account_id=account,
                revoke_all_sessions=recorder.revoke_all_sessions,
                delete_identity_user=recorder.delete_identity_user,
                purgers=[_FakePurger(recorder)],
                confirmed=True,
            )

        assert len(report.purges) == 1
        assert report.purges[0].name == "_FakePurger", "展示名缺省取类名（与编排的失败点名同源）"
        assert any("领域清除" in step for step in report.completed_steps)
        # 调用顺序：墓碑 → （删记录）→ 撤会话 → 删用户 → 清除
        assert recorder.calls == [
            f"revoke_sessions:{account}",
            f"delete_user:{account}",
            f"purge:_FakePurger:{account}",
        ]
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_tombstone_makes_the_account_visible_as_deleted() -> None:
    """注销后 `is_account_deleted` 为真——这是 Worker 判定「已注销」的入口。"""
    await _clear()
    account = _account("visible")
    recorder = _Recorder()
    try:
        from campfire.core.auth import is_account_deleted

        async with session_scope(get_settings()) as session:
            await delete_account(
                session,
                account_id=account,
                revoke_all_sessions=recorder.revoke_all_sessions,
                delete_identity_user=recorder.delete_identity_user,
                confirmed=True,
            )

        async with session_scope(get_settings()) as session:
            assert await is_account_deleted(session, account_id=account) is True
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_deletion_does_not_touch_other_accounts() -> None:
    """注销**只影响目标账号**：别的账号的墓碑与待处理记录原样保留。

    判别性：这是「删除范围」最容易出错的地方（一条漏了 `WHERE account_id` 的
    `DELETE` 会清空全表）。本文件的其他用例都用唯一账号，因此这一条显式对照。
    """
    await _clear()
    target = _account("target")
    bystander = _account("bystander")
    recorder = _Recorder()
    try:
        bystander_pending = await _enqueue(bystander)

        async with session_scope(get_settings()) as session:
            await delete_account(
                session,
                account_id=target,
                revoke_all_sessions=recorder.revoke_all_sessions,
                delete_identity_user=recorder.delete_identity_user,
                confirmed=True,
            )

        async with session_scope(get_settings()) as session:
            assert await get_tombstone(session, account_id=bystander) is None, "不得给别的账号写墓碑"
            survivor = list(
                (await session.execute(select(PendingWrite.id).where(PendingWrite.account_id == bystander))).scalars()
            )
        assert survivor == [bystander_pending], "不得删掉别的账号的待处理记录"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_pending_write_state_is_untouched_for_bystanders() -> None:
    """补充对照：确认上一条的「保留」不是巧合（状态与租约字段都没被动）。"""
    await _clear()
    target = _account("t2")
    bystander = _account("b2")
    recorder = _Recorder()
    try:
        await _enqueue(bystander, state=STATE_PROCESSING)
        async with session_scope(get_settings()) as session:
            await delete_account(
                session,
                account_id=target,
                revoke_all_sessions=recorder.revoke_all_sessions,
                delete_identity_user=recorder.delete_identity_user,
                confirmed=True,
            )

        async with session_scope(get_settings()) as session:
            row = (await session.execute(select(PendingWrite).where(PendingWrite.account_id == bystander))).scalar_one()
        assert row.state == STATE_PROCESSING
        assert row.finished_at is None
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# 真实 purger 的账本清除（不需要图库）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_purger_deletes_ledger_rows() -> None:
    """记忆清除者**删除该账号的删除账本行**（第 8 节「内容真删」的一部分）。

    本用例只验证**账本**这一半——图库那一半需要 FalkorDB 容器，
    由 ``test_memory_purge_integration.py`` 覆盖（那里能连上就测、连不上就跳过）。
    """
    from campfire.modules.memory.models import MemoryDeletionLedger
    from campfire.modules.memory.purge import delete_ledger_rows

    await _clear()
    account = _account("ledger")
    try:
        async with session_scope(get_settings()) as session:
            session.add(
                MemoryDeletionLedger(
                    episode_key=str(uuid.uuid4()),
                    account_id=account,
                    reason="user_request",
                )
            )
        async with session_scope(get_settings()) as session:
            removed = await delete_ledger_rows(session, account_id=account)
        assert removed == 1, f"应删除 1 行账本，实际 {removed}"

        async with session_scope(get_settings()) as session:
            left = list(
                (
                    await session.execute(
                        select(MemoryDeletionLedger.id).where(MemoryDeletionLedger.account_id == account)
                    )
                ).scalars()
            )
        assert left == []
    finally:
        async with session_scope(get_settings()) as session:
            await session.execute(
                delete(MemoryDeletionLedger).where(MemoryDeletionLedger.account_id.like(f"{_ACCOUNT}%"))
            )
        await _clear()


@pytest.mark.asyncio
async def test_expired_pending_is_also_deleted() -> None:
    """未领取的记录**不论是否到期**都删（判据是「未领取」，不是「到期」）。

    判别性：若实现误按 `expires_at`/`next_attempt_at` 过滤，退避中的记录会留下，
    而它属于一个已不存在的账号——正是「删干净」要避免的遗漏。
    """
    await _clear()
    account = _account("backoff")
    try:
        async with session_scope(get_settings()) as session:
            record = await enqueue(
                session,
                kind="memory_episode",
                account_id=account,
                origin="user_statement",
                payload={"content": "x", "occurred_at": datetime.now(timezone.utc).isoformat()},
                source={"session_id": "s1"},
            )
            # 正在退避等待重试的记录。
            record.next_attempt_at = datetime.now(timezone.utc) + timedelta(minutes=10)
            record_id = record.id

        recorder = _Recorder()
        async with session_scope(get_settings()) as session:
            report = await delete_account(
                session,
                account_id=account,
                revoke_all_sessions=recorder.revoke_all_sessions,
                delete_identity_user=recorder.delete_identity_user,
                confirmed=True,
            )
        assert report.pending_writes_deleted == 1

        async with session_scope(get_settings()) as session:
            left = (
                await session.execute(select(PendingWrite.id).where(PendingWrite.id == record_id))
            ).scalar_one_or_none()
        assert left is None, "退避中的记录属于已注销账号，也必须删掉"
    finally:
        await _clear()
