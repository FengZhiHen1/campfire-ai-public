"""集成测试：每一次 `dead` 转移都必须发出专属告警（写入路径第 6、8、11 节）。

对应 `docs/技术设计/technical-details/写入路径.md`：

- 第 6 节「超过重试上限 → 转 `dead` 并告警；不得静默丢弃」；
- 第 8 节「`dead` 数量必须告警，并且要用人为制造的失败验证告警真的会响」——
  否则它就是一个『坏了没人知道』的指标」；
- 第 11 节验收「超限转死信：持续失败，验证转 `dead` 且告警触发」。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_pending_write_dead_alert_integration.py

告警的判据是日志行里的 `[alert]` 前缀——那是 `worker.py` 的告警约定，
供日志告警规则单独匹配（第 8 节）。本文件不测「告警规则怎么配」，
测的是「每一次 `dead` 都真的产出了那一行」。

穷尽枚举（2026-09-30，用 `grep` 在 `apps/api/src` 全量搜 `mark_dead`、`STATE_DEAD`、
`"dead"`）：全仓写 `state = dead` 的只有 `core/pending_write/repository.mark_dead`
一处，它的调用点共三条，展开成五条路径——

1. `repository.mark_retryable_failure`（重试耗尽）→ 告警在
   `worker._register_retryable_failure` 里依返回值 `state == STATE_DEAD` 发出；
   两个消费者各走一次，即记忆侧与档案侧两条路径。
2. `worker.consume_memory_episode_task` 的 `MemoryDataError` 分支（记忆侧载荷不合法）
   → 2026-09-30 之前这里只有 `logger.warning`、没有 `[alert]`，
   这条 `dead` 对告警规则不可见，本文件的第一条用例就是它的守门。
3. `worker._mark_dead_and_alert` → 档案侧两条不可重试路径
   （载荷不合法、授权在领取时已不成立）。

五条路径各有用例，每条都人为制造一次失败、断言「记录真的进了 `dead`」
且「日志里出现了带 `[alert]` 且指名这条记录的那一行」。

为什么断言必须同时含 `pending_id`：只断言「日志里有 `[alert]`」会被同一次 pytest
会话里其它用例的告警满足——那样即使本路径没有告警也会变绿。

负证据的可采信性由 `test_canary_alert_channel_is_captured` 兜底：
它证明「没采到告警」不可能是采集通道没接上。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update

from campfire import worker as worker_module
from campfire.core.authz import AuthorizationError, set_authorizer
from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.core.pending_write import (
    KIND_MEMORY_EPISODE,
    KIND_PROFILE_ITEM,
    MAX_ATTEMPTS,
    STATE_DEAD,
    PendingWrite,
    enqueue,
)
from campfire.modules.memory.errors import MemoryDataError, MemoryUnavailableError
from campfire.modules.profile import repository as repo
from campfire.modules.profile import service
from campfire.modules.profile.authz import OwnerAuthorizer
from campfire.modules.profile.errors import ProfileDataError
from campfire.modules.profile.models import ProfileItem, SupportObject

pytestmark = pytest.mark.integration

#: 本文件所有记录的归属账号。与其它集成测试文件的账号刻意不同，
#: 让清理只作用于本文件造的数据。
_ACCOUNT = "it_dead_alert_account"

_WORKER_LOGGER = "campfire.worker"


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——不假装通过。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _authorizer() -> AsyncIterator[None]:
    """注入授权实现。

    与 `test_profile_worker_task_integration.py` 同一理由：不依赖 `worker` 模块导入时
    的模块级注入（那依赖 import 顺序）。夹具结束时清空，避免泄漏给下一个测试文件。
    """
    set_authorizer(OwnerAuthorizer(get_settings()))
    yield
    set_authorizer(None)


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    await _clear()
    yield
    await _clear()


async def _clear() -> None:
    async with session_scope(get_settings()) as session:
        await session.execute(delete(PendingWrite).where(PendingWrite.account_id == _ACCOUNT))
        owned = select(SupportObject.id).where(SupportObject.account_id == _ACCOUNT)
        await session.execute(delete(ProfileItem).where(ProfileItem.support_object_id.in_(owned)))
        await session.execute(delete(SupportObject).where(SupportObject.account_id == _ACCOUNT))


# ---------------------------------------------------------------------------
# 造数据与观测
# ---------------------------------------------------------------------------


def _valid_memory_payload() -> dict:
    """一条形状合法的记忆载荷（消费替身会先于载荷校验失败，故只为让记录可入队）。"""
    return {"content": "他喜欢早上跑步", "occurred_at": datetime.now(timezone.utc).isoformat()}


async def _enqueue_memory(payload: dict) -> str:
    """入队一条 `memory_episode`，返回其 id 字符串。"""
    async with session_scope(get_settings()) as session:
        record = await enqueue(
            session,
            kind=KIND_MEMORY_EPISODE,
            account_id=_ACCOUNT,
            origin="user_statement",
            payload=payload,
            source={"session_id": "s1"},
        )
    return str(record.id)


async def _new_object(name: str = "小宝") -> str:
    """造一个支持对象，返回其 id 字符串。"""
    async with session_scope(get_settings()) as session:
        record = await service.create_object(session, account_id=_ACCOUNT, display_name=name)
    return str(record.id)


async def _enqueue_profile(object_id: str, payload: dict) -> str:
    """入队一条 `profile_item`，返回其 id 字符串（消费侧会经 `repo.to_item_uuid` 映射）。"""
    async with session_scope(get_settings()) as session:
        record = await enqueue(
            session,
            kind=KIND_PROFILE_ITEM,
            account_id=_ACCOUNT,
            origin="user_statement",
            payload=payload,
            source={"session_id": "s1", "tool": "propose_profile_item"},
            support_object_id=object_id,
        )
    return str(record.id)


async def _pending_row(row_id: object) -> PendingWrite:
    """按行 id 读待处理记录（记忆侧直接用 pending_id，档案侧要先过 `to_item_uuid`）。"""
    async with session_scope(get_settings()) as session:
        return (await session.execute(select(PendingWrite).where(PendingWrite.id == row_id))).scalar_one()


async def _expire_backoff(row_id: object) -> None:
    """把退避时刻挪到过去，等价于「退避已到期」。

    为什么必须有这一步：退避曲线是 1→2→4→8 分钟（第 10 节），五次失败串行要等
    15 分钟，测试里不可等待。`take_for_processing` 的可领取判据是
    `next_attempt_at <= now`，把时刻挪到过去与「真的等到期」在被测代码看来完全一致；
    改的是时间参照，不是状态机——`attempts` 仍由真状态机逐次累加（用例逐轮核对）。

    只在记录还没进终态时调用：`dead` 的 `next_attempt_at` 由 `mark_dead` 清空
    （清掉是为了让排查不误判「这条还会重试」），用例不得把它重新填回去。
    """
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    async with session_scope(get_settings()) as session:
        # 用 ORM 的 `update(PendingWrite)` 而不是 `PendingWrite.__table__.update()`：
        # 后者在类型上是 `FromClause`（不声明 update），且 ORM 形态让会话知道
        # 这条 UPDATE 打在哪个映射实体上（与 `select(PendingWrite)` 同一层级）。
        await session.execute(update(PendingWrite).where(PendingWrite.id == row_id).values(next_attempt_at=past))


def _alert_lines(caplog: pytest.LogCaptureFixture, pending_id: str) -> list[str]:
    """捕获到的、带 `[alert]` 且指名该记录的日志行。"""
    return [r.getMessage() for r in caplog.records if "[alert]" in r.getMessage() and pending_id in r.getMessage()]


def _worker_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    """捕获到的 `campfire.worker` 全部日志行。

    失败信息里原样附上它：断言失败时能一眼分开「代码没告警」与「日志没采到」。
    """
    return [r.getMessage() for r in caplog.records if r.name == _WORKER_LOGGER]


def _assert_alerted(caplog: pytest.LogCaptureFixture, pending_id: str, subject: str) -> None:
    """断言日志里出现了「指名这条记录」的 `[alert]` 行，且主语说得清是哪一类 `dead`。

    `pending_id` 与 `subject` 必须在同一行：分开断言会被其它记录的行满足。
    """
    matched = _alert_lines(caplog, pending_id)
    assert matched, (
        f"这条 dead 必须带 [alert] 告警（第 6、8 节），实际捕获的 campfire.worker 日志行={_worker_lines(caplog)!r}"
    )
    assert subject in matched[0], f"告警主语应指明是哪一类 dead，实际告警行={matched[0]!r}"


# ---------------------------------------------------------------------------
# 采集通道 canary（负证据的可采信性）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_canary_alert_channel_is_captured(caplog: pytest.LogCaptureFixture) -> None:
    """采集通道 canary：`campfire.worker` 的 error 级日志确实会被 caplog 读到。

    为什么需要：本文件所有断言的形状都是「捕获到的日志行里有某一条」。若日志通道
    本身没接上（例如某处把 `propagate` 关掉），断言照样会失败——那是正确的红，
    但失败原因会被误读成「代码没告警」。这条 canary 把两种原因分开：
    它绿 = 通道可用，那么其它用例的红只能是被测代码的问题。
    """
    marker = "canary-dead-alert"
    with caplog.at_level(logging.WARNING, logger=_WORKER_LOGGER):
        worker_module.logger.error("[alert] 采集通道 canary pending_id=%s", marker)

    assert _alert_lines(caplog, marker), f"caplog 未捕获到 worker 的日志（通道不可用）={caplog.records!r}"


# ---------------------------------------------------------------------------
# 路径 1/5：记忆侧载荷不合法（2026-09-30 前缺 [alert] 的那一条）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_bad_payload_alerts(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """记忆侧载荷不合法 → 转 `dead` 且发出 `[alert]`（第 6、8 节）。

    人为制造的失败是真实判据判出来的：载荷缺 `content`，由
    `modules/memory/consumer._write_record_to_graph` 抛 `MemoryDataError`（不是替身抛的），
    记录因此真的走 `consume_memory_episode_task` 的 `MemoryDataError` 分支进 `dead`。
    只把图库句柄换成占位对象——该分支在碰图库之前就判完了载荷。

    消融（必须能红）：去掉 `_mark_dead_and_alert` 里的 `[alert]` 前缀，本用例的告警断言失败；
    去掉整个 `_mark_dead_and_alert` 调用，则 `state == dead` 的断言也失败。
    """
    payload = {"occurred_at": datetime.now(timezone.utc).isoformat()}
    pending_id = await _enqueue_memory(payload)
    monkeypatch.setattr(worker_module, "_get_memory_graph", lambda: object())

    with caplog.at_level(logging.WARNING, logger=_WORKER_LOGGER):
        with pytest.raises(MemoryDataError):
            await worker_module.consume_memory_episode_task(pending_id, lease_owner="w1")

    row = await _pending_row(pending_id)
    assert row.state == STATE_DEAD, "载荷不合法必须转 dead（第 6 节）"
    assert row.attempts == 0, "不可重试的终结不消耗重试预算"
    assert row.finished_at is not None, "转 dead 必须记 finished_at"
    _assert_alerted(caplog, pending_id, "记忆写入的载荷不合法")


# ---------------------------------------------------------------------------
# 路径 2/5：记忆侧重试耗尽
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_retry_exhaustion_alerts(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """记忆侧可重试失败耗尽 `MAX_ATTEMPTS` 次 → 转 `dead` 且发出 `[alert]`。

    对应第 11 节验收「超限转死信：持续失败，验证转 `dead` 且告警触发」。

    人为制造的失败：把 `consume_memory_episode` 换成抛 `MemoryUnavailableError`
    （图库瞬时不可用，第 6 节明列的可重试失败）的替身，走
    `_register_retryable_failure` → `mark_retryable_failure` 这条真状态机；
    本用例不替换状态机，只替换「写入动作」。

    消融（必须能红）：去掉 `_register_retryable_failure` 里那条 `[alert]` 的 error 日志，
    本用例的告警断言失败。
    """
    pending_id = await _enqueue_memory(_valid_memory_payload())
    monkeypatch.setattr(worker_module, "_get_memory_graph", lambda: object())

    async def _unavailable(*args: object, **kwargs: object) -> object:
        raise MemoryUnavailableError(
            "图库不可用（测试替身）",
            operation="consume_memory_episode",
            cause="ConnectionError",
        )

    monkeypatch.setattr(worker_module, "consume_memory_episode", _unavailable)

    attempts: list[int] = []
    with caplog.at_level(logging.WARNING, logger=_WORKER_LOGGER):
        for _ in range(MAX_ATTEMPTS):
            with pytest.raises(MemoryUnavailableError):
                await worker_module.consume_memory_episode_task(pending_id, lease_owner="w1")
            row = await _pending_row(pending_id)
            attempts.append(row.attempts)
            if row.state != STATE_DEAD:
                await _expire_backoff(pending_id)

    assert attempts == [1, 2, 3, 4, 5], f"重试计数必须逐轮累加，实际={attempts}"
    row = await _pending_row(pending_id)
    assert row.state == STATE_DEAD, f"第 {MAX_ATTEMPTS} 次失败必须转 dead"
    assert row.finished_at is not None, "转 dead 必须记 finished_at"
    _assert_alerted(caplog, pending_id, "记忆写入重试耗尽")


# ---------------------------------------------------------------------------
# 路径 3/5：档案侧载荷不合法
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_bad_payload_alerts(caplog: pytest.LogCaptureFixture) -> None:
    """档案侧载荷不合法（`ProfileDataError`）→ 转 `dead` 且发出 `[alert]`。

    人为制造的失败：载荷缺 `description`，由真实的 `write_from_pending` 判出来。

    消融（必须能红）：去掉 `_mark_dead_and_alert` 里的 `[alert]` 前缀，告警断言失败。
    """
    object_id = await _new_object()
    pending_id = await _enqueue_profile(object_id, {"domain": "communication", "topic": "表达方式"})

    with caplog.at_level(logging.WARNING, logger=_WORKER_LOGGER):
        with pytest.raises(ProfileDataError):
            await worker_module.consume_profile_item_task(pending_id, lease_owner="w1")

    row = await _pending_row(repo.to_item_uuid(pending_id))
    assert row.state == STATE_DEAD, "载荷不合法必须转 dead（第 6 节）"
    assert row.attempts == 0, "不可重试的终结不消耗重试预算"
    _assert_alerted(caplog, pending_id, "档案写入的载荷不合法")


# ---------------------------------------------------------------------------
# 路径 4/5：档案侧授权在领取时已不成立
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_authorization_failure_alerts(caplog: pytest.LogCaptureFixture) -> None:
    """对象在排队期间被归档 → 领取时授权不成立 → 转 `dead` 且发出 `[alert]`（第 6 节末段）。

    人为制造的失败：entry 入队后把对象归档。抛的是 `ObjectArchivedError`，
    它是 `AuthorizationError` 的子类（`core/authz/errors.py`），因此这里断言基类——
    与 `consume_profile_item_task` 的 `except AuthorizationError` 收口同一条边界。

    消融（必须能红）：去掉 `_mark_dead_and_alert` 里的 `[alert]` 前缀，告警断言失败。
    """
    object_id = await _new_object()
    pending_id = await _enqueue_profile(
        object_id, {"domain": "communication", "topic": "表达方式", "description": "用图片卡表达需求"}
    )

    async with session_scope(get_settings()) as session:
        await service.archive_object(session, account_id=_ACCOUNT, support_object_id=object_id)

    with caplog.at_level(logging.WARNING, logger=_WORKER_LOGGER):
        with pytest.raises(AuthorizationError):
            await worker_module.consume_profile_item_task(pending_id, lease_owner="w1")

    row = await _pending_row(repo.to_item_uuid(pending_id))
    assert row.state == STATE_DEAD, "授权在领取时不成立应转 dead，而不是留在 pending 反复重试"
    assert row.attempts == 0, "不可重试的终结不消耗重试预算"
    _assert_alerted(caplog, pending_id, "档案写入的授权在领取时已不成立")


# ---------------------------------------------------------------------------
# 路径 5/5：档案侧重试耗尽
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_retry_exhaustion_alerts(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """档案侧可重试失败耗尽 `MAX_ATTEMPTS` 次 → 转 `dead` 且发出 `[alert]`。

    人为制造的失败：把 `write_from_pending` 换成抛 `RuntimeError` 的替身。
    用 `RuntimeError` 是因为档案模块没有「存储不可用」的专属类型，`worker` 的
    失败分档把「数据库、未知异常」统一按可重试处理（见 `consume_profile_item_task`
    的 docstring）——替身抛的正是这一类。

    退避处理与记忆侧那条同理由（1→2→4→8 分钟不可等待，把 `next_attempt_at`
    挪到过去等价于到期）。

    消融（必须能红）：去掉 `_register_retryable_failure` 里那条 `[alert]` 的 error 日志，
    本用例的告警断言失败。
    """
    object_id = await _new_object()
    pending_id = await _enqueue_profile(
        object_id, {"domain": "communication", "topic": "表达方式", "description": "用图片卡表达需求"}
    )
    row_id = repo.to_item_uuid(pending_id)

    async def _storage_down(*args: object, **kwargs: object) -> object:
        raise RuntimeError("存储不可用（测试替身）")

    monkeypatch.setattr(worker_module, "write_from_pending", _storage_down)

    attempts: list[int] = []
    with caplog.at_level(logging.WARNING, logger=_WORKER_LOGGER):
        for _ in range(MAX_ATTEMPTS):
            with pytest.raises(RuntimeError):
                await worker_module.consume_profile_item_task(pending_id, lease_owner="w1")
            row = await _pending_row(row_id)
            attempts.append(row.attempts)
            if row.state != STATE_DEAD:
                await _expire_backoff(row_id)

    assert attempts == [1, 2, 3, 4, 5], f"重试计数必须逐轮累加，实际={attempts}"
    row = await _pending_row(row_id)
    assert row.state == STATE_DEAD, f"第 {MAX_ATTEMPTS} 次失败必须转 dead"
    _assert_alerted(caplog, pending_id, "档案写入重试耗尽")
