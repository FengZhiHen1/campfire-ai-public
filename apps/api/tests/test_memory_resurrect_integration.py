"""Worker 侧：**账号注销后在途写入不得复活**（真实 PostgreSQL，图库可选）。

对应 ``docs/技术设计/decisions/账号注销与墓碑.md`` 的不变量 2
（「Worker 领取时必须重新判定账号是否已注销」）与
``docs/技术设计/technical-details/认证与账号.md`` 第 13 节的验证方式
（「注销的在途写入不复活」）。

    docker compose up -d postgres          # 最小要求
    docker compose up -d falkordb          # 图库那部分需要它（缺则跳过）

## 这个文件守的是什么

注销时可能已有 ``pending_write`` 在排队、甚至已被 Worker 领取。若 Worker 不复查
账号状态，数据会被写回一个**已不存在**的账号的图——即**「删后复活」**，
而墓碑正是为阻止它而存在。所以：

1. **墓碑存在 → 丢弃且不写图**（本文件的主用例）；
2. **墓碑不存在 → 照常写入**（对照，证明上一条不是因为「写入坏了」而通过）。

## 消融验证（设计文档明确要求的证据形式）

第 13 节写明：「**消融：去掉墓碑后该记录会写入，用此证明墓碑真的在起作用**」。
本文件的对照用例就是这个消融——它证明「丢弃」是墓碑造成的，而不是别的原因。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from campfire.core.auth import AccountDeletionTombstone, record_deletion
from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.core.pending_write import PendingWrite, enqueue
from campfire.modules.memory.consumer import consume_memory_episode

pytestmark = pytest.mark.integration

#: 本文件的账号前缀（与其它测试文件隔离）。
_ACCOUNT = "it_resurrect_account"


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——**不假装通过**。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture
async def graph_or_skip() -> AsyncIterator[object]:
    """连上 FalkorDB 并返回图库句柄；**容器不可用则跳过**。

    用仓库既有的 ``conftest.connect_falkordb_or_skip``：它把一个真实踩坑固化了
    ——``FalkorDB(...)`` 的**构造函数本身就发网络 I/O**，因此构造必须在 ``try`` 内；
    且 ``redis.exceptions.ConnectionError`` **不是**内建 ``ConnectionError`` 的子类。

    该辅助返回 ``(driver, client)``，这里只把它当**可用性探针**用，随即关闭客户端；
    实际写入经 ``build_memory_graph`` 自己的连接（避免把探针的驱动塞进生产路径）。
    """
    from campfire.modules.memory.graph import build_memory_graph

    from .conftest import connect_falkordb_or_skip

    driver, client = connect_falkordb_or_skip()
    del driver  # 只作可用性探针
    await client.aclose()

    graph = build_memory_graph(get_settings())
    try:
        yield graph
    finally:
        await graph.aclose()


async def _clear() -> None:
    """清掉本文件写入的行（按前缀收窄）。"""
    async with session_scope(get_settings()) as session:
        await session.execute(
            delete(AccountDeletionTombstone).where(AccountDeletionTombstone.account_id.like(f"{_ACCOUNT}%"))
        )
        await session.execute(delete(PendingWrite).where(PendingWrite.account_id.like(f"{_ACCOUNT}%")))


def _account(suffix: str = "") -> str:
    """唯一的账号标识（必须唯一：墓碑是主键）。"""
    return f"{_ACCOUNT}_{suffix}{uuid.uuid4().hex[:8]}"


async def _enqueue(account_id: str) -> uuid.UUID:
    """入队一条记忆记录（状态机要求 `payload` 自带 content 与 occurred_at）。"""
    async with session_scope(get_settings()) as session:
        record = await enqueue(
            session,
            kind="memory_episode",
            account_id=account_id,
            origin="user_statement",
            payload={
                "content": "他今天在公园里玩得很开心",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            },
            source={"session_id": "s-resurrect", "message_seq": 1},
        )
        return record.id


async def _pending_state(pending_id: uuid.UUID) -> str | None:
    """取该记录的当前状态；已被删除则返回 ``None``。"""
    async with session_scope(get_settings()) as session:
        return (
            await session.execute(select(PendingWrite.state).where(PendingWrite.id == pending_id))
        ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_deleted_account_write_is_discarded_not_written(graph_or_skip: object) -> None:
    """**账号已注销 → 在途写入被丢弃**，且记录被删除（不留 ``done`` 谎言）。

    ## 构造的时序正是设计关心的那一个

    1. 先入队（模拟「注销时已有记录在排队」）；
    2. 写墓碑（注销的第 1 步）；
    3. 再让 Worker 消费它——**这正是「领取时重新判定」要拦住的时刻**。

    判别性：去掉 `consumer` 里的 `is_account_deleted` 复查，本用例失败
    （记录会被写成 `done` 并真的写进图库）。
    """
    await _clear()
    account = _account("discard")
    try:
        pending_id = await _enqueue(account)

        # 注销的第 1 步：写墓碑（Worker 用到的就是它）。
        async with session_scope(get_settings()) as session:
            await record_deletion(session, account_id=account)

        async with session_scope(get_settings()) as session:
            result = await consume_memory_episode(
                session, graph_or_skip, pending_id=str(pending_id), lease_owner="w-test"
            )

        assert result.written is False, "账号已注销，不得写入图库"
        assert result.discarded is True, "必须明确报告「因注销而丢弃」，而不是含糊的「没领到」"
        assert result.episode_uuid is None

        # 记录必须被删除（它属于一个已不存在的账号）。
        assert await _pending_state(pending_id) is None, "该记录应被删除，而不是留在某个状态"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_control_group_without_tombstone_the_write_proceeds(graph_or_skip: object) -> None:
    """**对照（即设计要求的消融）**：没有墓碑时，同一条记录**照常写入**。

    ## 为什么必须有这一条

    没有它，上面那条「被丢弃」可能是**任何原因**造成的（记录形状不对、图库坏了、
    领取失败…），那就证明不了**墓碑**在起作用。设计文档第 13 节明确要求这个消融：
    「去掉墓碑后该记录会写入，用此证明墓碑真的在起作用」。

    本用例与上一条**只差一件事**：有没有写墓碑。因此两者结果的差异
    只能归因于墓碑。

    判别性：若 `consumer` 无视墓碑（把复查删掉），两条用例都会写入；
    若 `consumer` 无条件丢弃（复查写成恒真），本用例失败。
    """
    await _clear()
    account = _account("control")
    try:
        pending_id = await _enqueue(account)
        # **刻意不写墓碑**——这就是「去掉墓碑」的消融。

        async with session_scope(get_settings()) as session:
            result = await consume_memory_episode(
                session, graph_or_skip, pending_id=str(pending_id), lease_owner="w-test"
            )

        assert result.written is True, "没有墓碑时写入应当正常进行（否则上面那条的「丢弃」无法归因于墓碑）"
        assert result.discarded is False
        assert result.episode_uuid is not None
        assert await _pending_state(pending_id) == "done", "成功写入应置 done"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_non_deleted_account_is_unaffected(graph_or_skip: object) -> None:
    """**别的账号已注销不影响本账号**：墓碑按账号过滤。

    判别性：若复查写成了「只要存在任何墓碑就丢弃」，本用例失败——
    那会让一个账号注销后**全站写入停摆**，是比原缺陷更严重的问题。
    """
    await _clear()
    deleted = _account("other")
    healthy = _account("healthy")
    try:
        # 先把**另一个**账号注销掉。
        async with session_scope(get_settings()) as session:
            await record_deletion(session, account_id=deleted)

        pending_id = await _enqueue(healthy)
        async with session_scope(get_settings()) as session:
            result = await consume_memory_episode(
                session, graph_or_skip, pending_id=str(pending_id), lease_owner="w-test"
            )

        assert result.written is True, "本账号未注销，写入必须照常"
        assert result.discarded is False
    finally:
        await _clear()
