"""集成测试：Worker 侧 `memory_episode` 消费分支的接线与租约栅栏。

对应 `docs/技术设计/technical-details/写入路径.md` 第 4、5、6 节。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_memory_worker_task_integration.py

与 `test_memory_write_path_integration.py` 的分工：那一个测的是链路本身
（入队 → 消费 → 图库里有 episode）；本文件测的是接线——投递点带不带身份、
消费者领取时盖谁的章，以及「租约过期后被重领」这条序列上迟到响应会不会得逞。

这条序列在生产路径上目前不可达（2026-09-30 实测）：消费把「领取 → 写图库 → 置 done」
放在同一个事务里，异常回滚；提取期间另一个事务看到的是上一次提交的 `pending`
（实测 `state=pending lease_owner=None`），它自己的领取 UPDATE 被行锁挡住
（实测 3 秒 statement_timeout 到期）。本文件钉的是栅栏本身的判别力——它在
「领取被单独提交」的形态下才拦人；修它的理由是这条 owner 比对是 CORE-03 的
迟到响应守卫，此前在记忆侧恒真（等于没接），将来任何把领取单独提交的改动都会
直接把「先领取者的迟到终结抢先成功」暴露出来。

本文件守住的判据

1. 投递点不带租约身份常量（D-31）。
2. 同进程两次领取得到互不相同的身份——一期只有一个 Worker 进程
   （兜底扫描与消费任务同进程，第 4.1 节），这是栅栏可判别的前提。
3. 租约过期重领后：先领取者的迟到 `mark_done` 被拒，真领取者的终结仍成功。
4. 不传 `lease_owner` 时，领取写库用的是本进程本次领取的身份。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from campfire import worker as worker_module
from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.core.pending_write import (
    KIND_MEMORY_EPISODE,
    LEASE_SECONDS,
    STATE_DONE,
    STATE_PENDING,
    PendingWrite,
    PendingWriteNotFoundError,
    enqueue,
    mark_done,
    take_for_processing,
)
from campfire.modules.memory.consumer import ConsumeResult

pytestmark = pytest.mark.integration

_ACCOUNT = "it_memory_worker_task_account"


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——不假装通过。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    await _clear()
    yield
    await _clear()


async def _clear() -> None:
    async with session_scope(get_settings()) as session:
        await session.execute(delete(PendingWrite).where(PendingWrite.account_id == _ACCOUNT))


async def _enqueue() -> str:
    """入队一条记忆记录，返回其 id 字符串。"""
    async with session_scope(get_settings()) as session:
        record = await enqueue(
            session,
            kind=KIND_MEMORY_EPISODE,
            account_id=_ACCOUNT,
            origin="user_statement",
            payload={"content": "他喜欢早上跑步", "occurred_at": datetime.now(timezone.utc).isoformat()},
            source={"session_id": "s1"},
        )
        return str(record.id)


async def _row(pending_id: str) -> PendingWrite:
    async with session_scope(get_settings()) as session:
        return (await session.execute(select(PendingWrite).where(PendingWrite.id == pending_id))).scalar_one()


# ---------------------------------------------------------------------------
# 1. 投递点与身份本身
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_does_not_pass_a_constant_lease_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """投递点不带租约身份常量；领取者在自己进程里盖自己的章（D-31 记忆侧）。

    判别性（这是本条用例的全部意义）：把 `_enqueue_memory_episode` 改回
    `kiq(pending_id, lease_owner="api")`，第一条断言立刻失败。

    为什么这条必须存在：能判别租约栅栏的仓库用例用的是两个互不相同的 owner
    （`test_pending_write_integration.py`），它们只覆盖 `repository`，覆盖不到接线——
    而缺陷恰恰在接线上（生产唯一投递点传常量，栅栏恒真；修改前实测见本文件说明）。
    """
    seen: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class _StubTask:
        """替代 broker 任务：只记录 `kiq` 的实参。"""

        async def kiq(self, *args: object, **kwargs: object) -> None:
            """记下本次投递的实参与关键字实参，不做别的。"""
            seen.append((args, kwargs))

    monkeypatch.setattr(worker_module, "consume_memory_episode_task", _StubTask())

    await worker_module._enqueue_memory_episode("00000000-0000-4000-8000-0000000000aa")

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


# ---------------------------------------------------------------------------
# 2. 租约栅栏在「同进程重领」这条序列上必须可判别
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lease_fence_holds_when_the_same_process_reclaims() -> None:
    """同进程内租约过期重领 → 先领取者的迟到 `mark_done` 被拒（D-31 记忆侧）。

    一期只有一个 Worker 进程（兜底扫描与消费任务同进程，写入路径第 4.1 节），
    因此「两次领取拿到互不相同的身份」是这条栅栏在生产形态下可用的前提。
    审查者的探针正是拿两次 `_lease_identity()` 当 owner 复现记忆侧缺陷的：
    身份相同 → 迟到者抢先成功，栅栏未判别。

    判别性：把身份改回常量（`主机名:进程号` 或 `"api"`），
    「身份不同」与「迟到 `mark_done` 被拒」两处同时失败。
    """
    pending_id = await _enqueue()
    owner_first = worker_module._lease_identity()
    owner_second = worker_module._lease_identity()
    assert owner_first != owner_second, "同进程两次领取必须得到不同身份——否则栅栏在同进程重领时恒真"

    base = datetime.now(timezone.utc)
    async with session_scope(get_settings()) as session:
        claimed = await take_for_processing(session, pending_id=pending_id, lease_owner=owner_first, now=base)
    assert claimed is not None and claimed.lease_owner == owner_first

    # 租约过期后由第二个领取者接管（模拟慢抽取超过 5 分钟租约）。
    after_lease = base + timedelta(seconds=LEASE_SECONDS + 1)
    async with session_scope(get_settings()) as session:
        reclaimed = await take_for_processing(session, pending_id=pending_id, lease_owner=owner_second, now=after_lease)
    assert reclaimed is not None and reclaimed.lease_owner == owner_second

    # 先领取者的迟到终结 → 必须被拒（CORE-03）。
    async with session_scope(get_settings()) as session:
        with pytest.raises(PendingWriteNotFoundError):
            await mark_done(session, pending_id=pending_id, lease_owner=owner_first, now=after_lease)

    # 真领取者的终结仍必须成功（迟到者不得挤掉它）。
    async with session_scope(get_settings()) as session:
        done = await mark_done(session, pending_id=pending_id, lease_owner=owner_second, now=after_lease)
    assert done.state == STATE_DONE
    assert done.lease_owner is None, "置 done 必须同事务清租约"


@pytest.mark.asyncio
async def test_the_consumed_lease_owner_is_the_consumers_own_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端：不传 `lease_owner` 时，领取写库用的是本进程本次领取的身份。

    与上一条配对——上一条钉「两次领取的身份不同」，这一条钉「任务确实用了自己的身份」
    而不是把调用方传来的值原样透传（透传 `None` 时栅栏条件会退化成「不比对」）。

    `mark_done` 在消费成功时会清空租约，因此消费后再读记录读不到它；这里用一个
    记录型的包装器截获交给 `consume_memory_episode` 的实参。

    比的是前缀（主机名:进程号）而不是整体：身份带每次领取唯一的后缀，
    再取一次 `_lease_identity()` 必然不同（那正是栅栏可判别的前提）。
    """
    captured: list[str] = []

    async def _spy(session: object, graph: object, *, pending_id: str, lease_owner: str) -> ConsumeResult:  # noqa: ANN401
        captured.append(str(lease_owner))
        # 不回写库：本用例只钉「交给用例的身份是什么」，状态推进由上面那条用例覆盖。
        return ConsumeResult(pending_id=str(pending_id), written=False)

    pending_id = await _enqueue()
    monkeypatch.setattr(worker_module, "consume_memory_episode", _spy)
    monkeypatch.setattr(worker_module, "_get_memory_graph", lambda: object())

    assert await worker_module.consume_memory_episode_task(pending_id) == "skipped"
    assert len(captured) == 1, f"领取恰好一次，实际={captured}"
    own_prefix = worker_module._lease_identity().rsplit(":", 1)[0]
    assert captured[0].rsplit(":", 1)[0] == own_prefix, f"领取时应盖本进程的章，实际={captured}"

    # 记录未被本次消费推进（消费替身没写库），留在 pending 等下一次投递。
    assert (await _row(pending_id)).state == STATE_PENDING
