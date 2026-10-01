"""集成测试：Worker 侧 `profile_item` 消费分支（T12）。

对应 `docs/技术设计/technical-details/写入路径.md` 第 4、5、6 节。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_profile_worker_task_integration.py

与 `test_profile_consumer_integration.py` 的分工：那一个测的是用例
（`write_from_pending` 本身）；本文件测的是 Worker 侧接线——任务函数、
失败分档（哪一类转 `dead`、哪一类回 `pending`）与重复执行的幂等。
分档只在任务函数里，用例层看不见它。

本文件守住的判据

1. 主链路：任务跑一次 → 条目出现、记录置 `done`。
2. 幂等（实测两次）：同一 `pending_id` 跑两次 → 只有一条条目，第二次拿到 `skipped`。
3. 授权在领取时重新判定：对象在排队期间被归档 → 转 `dead` 且不写入。
4. 载荷不合法 → 转 `dead`。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from campfire import worker as worker_module
from campfire.core.authz import set_authorizer
from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.core.pending_write import (
    KIND_MEMORY_EPISODE,
    KIND_PROFILE_ITEM,
    STATE_DEAD,
    STATE_DONE,
    STATE_PENDING,
    PendingWrite,
    PendingWriteNotFoundError,
    enqueue,
    mark_done,
    take_for_processing,
)
from campfire.modules.profile import ProfileWriteResult, service
from campfire.modules.profile import repository as repo
from campfire.modules.profile.authz import OwnerAuthorizer
from campfire.modules.profile.models import ProfileItem, SupportObject

pytestmark = pytest.mark.integration

_ACCOUNT = "it_profile_worker_task_account"


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——不假装通过。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _authorizer() -> AsyncIterator[None]:
    """注入授权实现。

    为什么不依赖 `worker` 模块导入时的注入：测试进程 import `campfire.worker` 时会执行
    模块级 `set_authorizer(...)`，但那条依赖 import 顺序，显式注入才是不靠巧合的做法。
    夹具结束时清空，避免泄漏给下一个测试文件。
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


async def _new_object(name: str = "小宝") -> str:
    async with session_scope(get_settings()) as session:
        record = await service.create_object(session, account_id=_ACCOUNT, display_name=name)
    return str(record.id)


async def _enqueue(object_id: str, *, origin: str = "user_statement", payload: dict | None = None) -> str:
    body = (
        payload
        if payload is not None
        else {"domain": "communication", "topic": "表达方式", "description": "用图片卡表达需求"}
    )
    async with session_scope(get_settings()) as session:
        record = await enqueue(
            session,
            kind=KIND_PROFILE_ITEM,
            account_id=_ACCOUNT,
            origin=origin,
            payload=body,
            source={"session_id": "s1", "tool": "propose_profile_item"},
            support_object_id=object_id,
        )
    return str(record.id)


async def _pending_row(pending_id: str) -> PendingWrite:
    async with session_scope(get_settings()) as session:
        return (
            await session.execute(select(PendingWrite).where(PendingWrite.id == repo.to_item_uuid(pending_id)))
        ).scalar_one()


async def _item_count(object_id: str) -> int:
    async with session_scope(get_settings()) as session:
        return (
            await session.execute(
                select(func.count())
                .select_from(ProfileItem)
                .where(ProfileItem.support_object_id == repo.to_object_uuid(object_id))
            )
        ).scalar_one()


# ---------------------------------------------------------------------------
# 1. 主链路
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_task_writes_the_item_and_marks_done() -> None:
    """任务跑一次 → 条目出现、记录置 `done` 并清租约。"""
    object_id = await _new_object()
    pending_id = await _enqueue(object_id)

    assert (await _pending_row(pending_id)).state == STATE_PENDING
    assert await _item_count(object_id) == 0, "消费前不得有条目"

    outcome = await worker_module.consume_profile_item_task(pending_id, lease_owner="w1")

    assert outcome == "written"
    row = await _pending_row(pending_id)
    assert row.state == STATE_DONE
    assert row.finished_at is not None
    assert row.lease_owner is None, "置 done 必须同事务清租约"
    assert await _item_count(object_id) == 1


@pytest.mark.asyncio
async def test_inferred_item_lands_in_the_candidate_layer() -> None:
    """推断来源经 Worker 消费后只进候选层——确认状态由 `origin` 推导，不取载荷。"""
    object_id = await _new_object()
    pending_id = await _enqueue(object_id, origin="ai_inference")

    assert await worker_module.consume_profile_item_task(pending_id, lease_owner="w1") == "written"

    async with session_scope(get_settings()) as session:
        grouped = await service.read_items(
            session, account_id=_ACCOUNT, support_object_id=object_id, include_candidates=True
        )
    assert grouped.items == [], "推断不得进稳定层"
    assert len(grouped.candidates) == 1


# ---------------------------------------------------------------------------
# 2. 幂等：同一 pending 跑两次（要求「实测两次」）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_running_the_task_twice_does_not_duplicate_the_item() -> None:
    """幂等实测两次：同一 `pending_id` 连跑两次 → 只有一条条目。

    第二次的期望是 `skipped`（未领取到：记录已 `done`，不再是可领取状态），
    且条目不增加。唯一约束是兜底，正常路径由「已终结不可领取 + 显式查重」先行挡住。

    这条不能靠代码审查代替：重复执行是运行期行为，
    「第二次真的什么都没写进去」只能跑出来看。
    """
    object_id = await _new_object()
    pending_id = await _enqueue(object_id)

    first = await worker_module.consume_profile_item_task(pending_id, lease_owner="w1")
    second = await worker_module.consume_profile_item_task(pending_id, lease_owner="w2")

    assert first == "written"
    assert second == "skipped", "第二次不得再写一遍"
    assert await _item_count(object_id) == 1, "幂等：条目数必须仍是 1"
    assert (await _pending_row(pending_id)).state == STATE_DONE


@pytest.mark.asyncio
async def test_replay_after_lease_is_reclaimed_is_still_idempotent() -> None:
    """租约过期后被重领（另一 Worker）→ 条目仍只有一条。

    与上一条的区别：记录已被 `mark_done` 终结时重跑走的是「不可领取」；
    这里让记录回到可领取态（模拟「写入成功但 mark_done 丢失」的崩溃窗口），
    走的是领取成功 + 显式查重命中那条路——两条路都要幂等。
    """
    object_id = await _new_object()
    pending_id = await _enqueue(object_id)

    assert await worker_module.consume_profile_item_task(pending_id, lease_owner="w1") == "written"

    # 人为把记录放回 pending（模拟 mark_done 丢失），租约清空。
    async with session_scope(get_settings()) as session:
        # 用 `update(模型)` 而不是 `PendingWrite.__table__.update()`：后者在静态上是
        # `FromClause`（`__table__` 的声明类型），没有 `update`。与 `repository.py` 同法。
        await session.execute(
            update(PendingWrite)
            .where(PendingWrite.id == repo.to_item_uuid(pending_id))
            .values(state=STATE_PENDING, finished_at=None, lease_owner=None, lease_expires_at=None)
        )

    second = await worker_module.consume_profile_item_task(pending_id, lease_owner="w2")

    assert second == "skipped", "已写成条目的待处理记录重放时不得再写一条"
    assert await _item_count(object_id) == 1
    assert (await _pending_row(pending_id)).state == STATE_DONE, "重放要把记录重新收口成 done"


# ---------------------------------------------------------------------------
# 3. 授权在领取时重新判定（写入路径第 6 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archived_object_is_dead_not_written() -> None:
    """对象在排队期间被归档 → 领取时判定不成立 → 转 `dead`、不写入（第 6 节）。

    消融：把 `consume_profile_item_task` 里的 `except AuthorizationError` 分支删掉，
    记录会落到可重试分支、变成 `pending` + `attempts=1`，本用例失败。
    """
    from campfire.core.authz import ObjectArchivedError

    object_id = await _new_object()
    pending_id = await _enqueue(object_id)

    async with session_scope(get_settings()) as session:
        await service.archive_object(session, account_id=_ACCOUNT, support_object_id=object_id)

    with pytest.raises(ObjectArchivedError):
        await worker_module.consume_profile_item_task(pending_id, lease_owner="w1")

    row = await _pending_row(pending_id)
    assert row.state == STATE_DEAD, "授权在领取时不成立应转 dead，而不是留在 pending 反复重试"
    assert row.last_error is not None
    assert row.attempts == 0, "不可重试的终结不消耗重试预算"
    assert await _item_count(object_id) == 0, "归档对象不得写入条目"


# ---------------------------------------------------------------------------
# 4. 载荷不合法
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bad_payload_is_dead() -> None:
    """载荷缺必填键（`ProfileDataError`）→ 转 `dead`：重试不会变好。"""
    from campfire.modules.profile.errors import ProfileDataError

    object_id = await _new_object()
    # 缺 description：`write_from_pending` 会抛 ProfileDataError。
    pending_id = await _enqueue(object_id, payload={"domain": "communication", "topic": "表达方式"})

    with pytest.raises(ProfileDataError):
        await worker_module.consume_profile_item_task(pending_id, lease_owner="w1")

    row = await _pending_row(pending_id)
    assert row.state == STATE_DEAD
    assert row.finished_at is not None
    assert await _item_count(object_id) == 0


@pytest.mark.asyncio
async def test_dispatch_does_not_pass_a_constant_lease_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """投递点不带租约身份常量；领取者在自己进程里盖自己的章（侦察 D-31）。

    判别性（这是本条用例的全部意义）：把 `_enqueue_profile_item` 改回
    `kiq(pending_id, lease_owner="api")`，第一条断言立刻失败。

    为什么这条必须存在：能判别租约栅栏的仓库用例用的是两个互不相同的 owner
    （`test_pending_write_integration.py`），它们只覆盖 `repository`，覆盖不到接线——
    而 D-31 的缺陷恰恰在接线上（生产唯一投递点传常量，栅栏恒真）。
    """
    import os

    seen: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class _StubTask:
        """替代 broker 任务：只记录 `kiq` 的实参。"""

        async def kiq(self, *args: object, **kwargs: object) -> None:
            seen.append((args, kwargs))

    monkeypatch.setattr(worker_module, "consume_profile_item_task", _StubTask())

    await worker_module._enqueue_profile_item("00000000-0000-4000-8000-0000000000aa")

    assert seen == [(("00000000-0000-4000-8000-0000000000aa",), {})], (
        f"投递不得带 lease_owner（栅栏要的是领取者的身份），实际投递={seen}"
    )

    # 消费者侧的身份必须可排查（主机名:进程号前缀），且每次领取都不同（唯一后缀）。
    identity = worker_module._lease_identity()
    parts = identity.split(":")
    assert len(parts) == 3 and parts[1] == str(os.getpid()), f"租约身份不可排查或缺进程号：{identity!r}"
    assert parts[2] != "", "唯一后缀不得为空——空后缀等于退回「每个进程一个身份」"
    assert len(identity) <= worker_module.LEASE_IDENTITY_MAX_CHARS, "租约身份必须有上界（与列宽一致）"
    assert worker_module._lease_identity() != identity, "同进程两次领取必须得到不同身份（D-31）"


@pytest.mark.asyncio
async def test_lease_fence_holds_when_the_same_process_reclaims() -> None:
    """同进程内租约过期重领 → 先领取者的迟到 `mark_done` 被拒（D-31 返工，2026-09-30）。

    一期只有一个 Worker 进程（兜底扫描与消费任务同进程，写入路径第 4.1 节），
    因此「两次领取拿到互不相同的身份」是这条栅栏在生产形态下可用的前提。
    审查者的探针正是拿这里两次 `_lease_identity()` 当 owner 复现的：
    身份相同 → 迟到者抢先成功，栅栏未判别。

    判别性：把 `_lease_identity` 改回 `主机名:进程号`（每个进程一个值），
    第一条断言与「迟到 `mark_done` 被拒」两处同时失败。

    对照（canary）：同一段代码在 owner 互不相同时本就拒绝迟到者
    （`test_pending_write_integration.test_lease_fence_rejects_a_late_writer`），
    因此这里的失败不可能是「栅栏机制本身没接上」。
    """
    object_id = await _new_object()
    pending_id = await _enqueue(object_id)

    owner_first = worker_module._lease_identity()
    owner_second = worker_module._lease_identity()
    assert owner_first != owner_second, "同进程两次领取必须得到不同身份——否则栅栏在同进程重领时恒真"

    async with session_scope(get_settings()) as session:
        claimed = await take_for_processing(session, pending_id=repo.to_item_uuid(pending_id), lease_owner=owner_first)
    assert claimed is not None and claimed.lease_owner == owner_first

    # 租约过期（模拟慢写入超过 5 分钟租约）。
    async with session_scope(get_settings()) as session:
        await session.execute(
            update(PendingWrite)
            .where(PendingWrite.id == repo.to_item_uuid(pending_id))
            .values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )

    async with session_scope(get_settings()) as session:
        reclaimed = await take_for_processing(
            session, pending_id=repo.to_item_uuid(pending_id), lease_owner=owner_second
        )
    assert reclaimed is not None and reclaimed.lease_owner == owner_second

    # 先领取者的迟到终结 → 必须被拒（CORE-03）。
    async with session_scope(get_settings()) as session:
        with pytest.raises(PendingWriteNotFoundError):
            await mark_done(session, pending_id=repo.to_item_uuid(pending_id), lease_owner=owner_first)

    # 真领取者的终结仍必须成功（迟到者不得挤掉它）。
    async with session_scope(get_settings()) as session:
        done = await mark_done(session, pending_id=repo.to_item_uuid(pending_id), lease_owner=owner_second)
    assert done.state == STATE_DONE
    assert done.lease_owner is None, "置 done 必须同事务清租约"


@pytest.mark.asyncio
async def test_the_consumed_lease_owner_is_the_consumers_own_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端：不传 `lease_owner` 时，领取写库用的是本进程身份。

    与上一条配对——上一条钉投递，这一条钉「领取时真的用了自己的身份」。
    `mark_done` 在消费成功时会清空租约，因此消费后再读记录读不到它；
    这里用一个记录型的包装器截获交给 `write_from_pending` 的实参。

    比的是前缀（主机名:进程号）而不是整体：身份带每次领取唯一的后缀，
    再取一次 `_lease_identity()` 必然不同（那正是栅栏可判别的前提）。
    """
    captured: list[str] = []

    # 签名与 `write_from_pending` 逐字一致：`session` 是真库会话（这里如实声明，
    # 不用 `object` 糊过去），返回值也照抄，否则这处替身无法与原函数互换。
    async def _spy(session: AsyncSession, *, pending_id: object, lease_owner: str) -> ProfileWriteResult:
        captured.append(str(lease_owner))
        return await _original(session, pending_id=pending_id, lease_owner=lease_owner)

    object_id = await _new_object()
    pending_id = await _enqueue(object_id)

    _original = worker_module.write_from_pending
    monkeypatch.setattr(worker_module, "write_from_pending", _spy)

    assert await worker_module.consume_profile_item_task(pending_id) == "written"
    assert len(captured) == 1, f"领取恰好一次，实际={captured}"
    own_prefix = worker_module._lease_identity().rsplit(":", 1)[0]
    assert captured[0].rsplit(":", 1)[0] == own_prefix, f"领取时应盖本进程的章，实际={captured}"


@pytest.mark.asyncio
async def test_dispatch_table_routes_profile_item_to_its_own_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """分派表把 `profile_item` 投给档案任务，不是记忆任务。

    这是 2026-09-30 那条缺陷的正面覆写：此前投递硬编码只投记忆任务，
    `profile_item` 被记忆消费者按「kind 不符」判 `dead`。这里把两个投递函数都换成
    探针，断言拿到 `profile_item` 的只有档案那一个，也就是断言分派表真的按 kind 分。

    用 `KIND_*` 常量而不是字面量（侦察 D-35）：kind 是闭集，散落的字面量在词表
    变更时不会报错、只会静默走空。
    """
    calls: list[tuple[str, str]] = []

    async def _probe_memory(pending_id: str) -> None:
        calls.append(("memory", pending_id))

    async def _probe_profile(pending_id: str) -> None:
        calls.append(("profile", pending_id))

    monkeypatch.setitem(worker_module._CONSUMER_DISPATCHERS, KIND_MEMORY_EPISODE, _probe_memory)
    monkeypatch.setitem(worker_module._CONSUMER_DISPATCHERS, KIND_PROFILE_ITEM, _probe_profile)

    pending_id = "00000000-0000-4000-8000-0000000000ff"
    await worker_module.dispatch_pending_write_to_queue(pending_id, KIND_PROFILE_ITEM)

    assert calls == [("profile", pending_id)], f"profile_item 必须只投给档案任务，实际={calls}"
