"""集成测试：记忆的写入链路（``pending_write`` → Worker 消费，端到端）。

对应 ``docs/技术设计/technical-details/写入路径.md`` 第 3、4、5、6 节与
``write_memory`` 契约（`docs/技术设计/面/consult/tools/write_memory.md`）。

这是**跨两个存储**的测试：PostgreSQL（待处理记录的状态机）与 FalkorDB（episode）。
因此需要两个容器：

    docker compose up -d postgres falkordb
    uv run pytest -m integration apps/api/tests/test_memory_write_path_integration.py

**图库侧用假模型客户端**（抽取要调 TokenHub，当前凭据是占位符——见 `TECH-02`），
因此本文件验证的是**链路与状态推进**，不验证抽取质量（那是 `TECH-18`）。

锁住的行为：
1. 入队一条记忆记录 → 消费 → 图库里出现 episode，且**派生的 uuid 与 pending_id 对应**
   （幂等依据是派生的确定性 uuid，不是 `name`）。
2. **只有 `done` 算写入成功**：消费前是 `pending`，消费后是 `done` 且 `finished_at` 有值。
3. **重复消费不产生第二条 episode**（第 5 节幂等）。
4. **来源会话标识经 `source_description` 往返**（`episode_metadata` 不落库，第 3 节实测）。
5. **载荷缺必填键时显式失败**，且**不产生** episode（不猜时间、不猜来源）。
6. 非 `memory_episode` 的 kind 被本消费者拒绝。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from campfire.core.config import EMBEDDING_DIM, get_settings
from campfire.core.db import session_scope
from campfire.core.pending_write import (
    KIND_PROFILE_ITEM,
    STATE_DEAD,
    STATE_DONE,
    STATE_PENDING,
    PendingWrite,
    enqueue,
)
from campfire.modules.memory.consumer import consume_memory_episode
from campfire.modules.memory.derived import read_emergency_facts
from campfire.modules.memory.errors import MemoryDataError, MemoryUnavailableError
from campfire.modules.memory.graph import MemoryGraph, OrderedCrossEncoder
from campfire.modules.memory.identity import PendingId, derive_episode_uuid, to_account_id
from campfire.modules.memory.ledger import deleted_episode_keys
from campfire.modules.memory.models import MemoryDeletionLedger
from campfire.modules.memory.store import EPISODE_WRITE_STATE_PENDING, read_timeline

from .conftest import connect_falkordb_or_skip

pytestmark = pytest.mark.integration

_ACCOUNT = "it_mem_write_account"


async def _read_timeline(graph, account, **kwargs):  # noqa: ANN001, ANN003, ANN201
    """调**公开**读入口（自动开会话取删除账本）。

    2026-09-30 起读入口只收 `session`——「已删清单」由函数内部取，调用方无法漏传或
    传空列表（此前那样会静默返回已删记忆）。本助手只替测试开会话，不绕过过滤。
    """
    async with session_scope(get_settings()) as session:
        return await read_timeline(session, graph, to_account_id(account), **kwargs)


async def _read_emergency_facts(graph, account, **kwargs):  # noqa: ANN001, ANN003, ANN201
    """调**公开**应急读入口（同上）。"""
    async with session_scope(get_settings()) as session:
        return await read_emergency_facts(session, graph, to_account_id(account), **kwargs)


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——不假装通过。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture
async def memory_graph() -> AsyncIterator[MemoryGraph]:
    """使用假模型客户端的记忆图库句柄（不调真实供应商）。"""
    from graphiti_core.embedder.client import EmbedderClient
    from graphiti_core.graphiti import Graphiti
    from graphiti_core.llm_client.client import LLMClient
    from graphiti_core.llm_client.config import LLMConfig

    class _FakeEmbedder(EmbedderClient):
        async def create(self, input_data) -> list[float]:  # noqa: ANN001
            return [0.001] * EMBEDDING_DIM

        async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
            return [[0.001] * EMBEDDING_DIM for _ in input_data_list]

    class _FakeLLM(LLMClient):
        def __init__(self) -> None:
            super().__init__(config=LLMConfig(api_key="test", model="fake"))

        async def _generate_response(
            self,
            messages=None,
            response_model=None,
            max_tokens=None,
            model_size=None,
            group_id=None,
            prompt_name=None,
            **kwargs,
        ):  # noqa: ANN001
            if response_model is not None:
                return {name: [] for name in response_model.model_fields}
            return {}

    # 连容器：`FalkorDB(...)` **构造函数本身发网络 I/O**，且它抛的是
    # `redis.exceptions.ConnectionError`（**不是**内建类型）——两者都由
    # `conftest.connect_falkordb_or_skip` 统一处理，避免每个文件各踩一次。
    driver, client = connect_falkordb_or_skip()

    graph = MemoryGraph(
        graphiti=Graphiti(
            graph_driver=driver,
            llm_client=_FakeLLM(),
            embedder=_FakeEmbedder(),
            cross_encoder=OrderedCrossEncoder(),
            store_raw_episode_content=True,
        ),
        driver=driver,
    )
    try:
        yield graph
    finally:
        scoped = graph.driver_for(_ACCOUNT)
        await scoped.execute_query("MATCH (n) DETACH DELETE n")
        await graph.aclose()


async def _clear() -> None:
    """清掉本文件账号的待处理记录**与删除账本行**。

    为什么账本也要清（2026-09-30 评审实测发现）：本文件的删除协同用例
    （`test_deleted_memory_is_not_returned_after_write_path_completes`）每跑一次就记
    一行账本；而 `episode_key` 有**全局唯一约束**、账本是**多测试文件共用**的表——
    残留会让别的文件（或下一次运行）在同 key 上撞 `UniqueViolationError`、或让读
    断言莫名少条。实测该缺陷曾累积 68 行残留。与
    `test_memory_timeline_integration._clear_ledger` 的既有做法对齐。
    """
    async with session_scope(get_settings()) as session:
        await session.execute(delete(PendingWrite).where(PendingWrite.account_id == _ACCOUNT))
        await session.execute(delete(MemoryDeletionLedger).where(MemoryDeletionLedger.account_id == _ACCOUNT))


async def _enqueue(
    *,
    content: str = "他喜欢早上跑步",
    occurred_at: str | None = None,
    session_id: str | None = "s1",
    kind: str = "memory_episode",
) -> str:
    """入队一条记忆记录，返回其 id 字符串。"""
    payload: dict[str, object] = {"content": content}
    if occurred_at is not None:
        payload["occurred_at"] = occurred_at
    source: dict[str, object] = {}
    if session_id is not None:
        source["session_id"] = session_id

    async with session_scope(get_settings()) as session:
        record = await enqueue(
            session,
            kind=kind,
            account_id=_ACCOUNT,
            origin="user_statement",
            payload=payload,
            source=source,
            support_object_id="obj-1" if kind == KIND_PROFILE_ITEM else None,
        )
        return str(record.id)


# ---------------------------------------------------------------------------
# 端到端链路
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_record_becomes_an_episode_with_the_derived_uuid(
    memory_graph: MemoryGraph,
) -> None:
    """**主链路**：入队 → 消费 → 图库出现 episode，uuid 由 `pending_id` 派生。

    幂等依据必须是**派生的确定性 uuid**（`write_memory` 契约第 4 节），不是 `name`。
    这条同时验证「消费前的记录是 pending（未写入）」与「消费后是 done」。
    """
    await _clear()
    occurred = datetime.now(timezone.utc) - timedelta(days=1)
    try:
        pending_id = await _enqueue(occurred_at=occurred.isoformat())

        # 消费前：记录是 pending，图库里没有 episode。
        async with session_scope(get_settings()) as session:
            before = (await session.execute(select(PendingWrite).where(PendingWrite.id == pending_id))).scalar_one()
        assert before.state == STATE_PENDING
        assert await _read_timeline(memory_graph, _ACCOUNT) == []

        async with session_scope(get_settings()) as session:
            result = await consume_memory_episode(session, memory_graph, pending_id=pending_id, lease_owner="worker-1")

        assert result.written is True
        expected_uuid = derive_episode_uuid(PendingId(pending_id))
        assert result.episode_uuid == expected_uuid, "幂等依据必须是派生 uuid"

        # 消费后：记录是 done，图库里有那条 episode，且内容是载荷里的正文。
        async with session_scope(get_settings()) as session:
            after = (await session.execute(select(PendingWrite).where(PendingWrite.id == pending_id))).scalar_one()
        assert after.state == STATE_DONE
        assert after.finished_at is not None
        assert after.lease_owner is None, "完成后必须清租约"

        episodes = await _read_timeline(memory_graph, _ACCOUNT)
        assert [e.content for e in episodes] == ["他喜欢早上跑步"]
        assert episodes[0].episode_uuid == expected_uuid
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_source_session_id_round_trips_via_source_description(memory_graph: MemoryGraph) -> None:
    """来源会话标识经 `source_description` 往返。

    为什么必须断言：`episode_metadata` **不落库**（通用记忆第 3 节实测），所以来源只能
    走 `source_description`。若哪天改成依赖 `episode_metadata`，来源会静默丢失。
    """
    await _clear()
    occurred = datetime.now(timezone.utc)
    try:
        pending_id = await _enqueue(occurred_at=occurred.isoformat(), session_id="session-42")
        async with session_scope(get_settings()) as session:
            await consume_memory_episode(session, memory_graph, pending_id=pending_id, lease_owner="w")

        episodes = await _read_timeline(memory_graph, _ACCOUNT)
        assert len(episodes) == 1
        assert "session=session-42" in episodes[0].source
        # pending 标识也在来源里，便于从图库反查是哪条待处理记录写的。
        assert pending_id in episodes[0].source
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_repeated_consumption_does_not_create_a_second_episode(memory_graph: MemoryGraph) -> None:
    """**重复消费不产生第二条 episode**（第 5 节幂等 / 契约的「重复提交」一行）。

    第二次消费会因租约仍有效而**领取失败**（`written=False`）——这本身就是幂等的一道
    防线。为排除「只是租约挡住了」，这里额外验证：即使绕过租约直接重写同一 uuid，
    图库里的 episode 数仍是 1（`MERGE` 按 uuid，通用记忆第 3 节实测）。
    """
    await _clear()
    occurred = datetime.now(timezone.utc)
    try:
        pending_id = await _enqueue(occurred_at=occurred.isoformat())
        async with session_scope(get_settings()) as session:
            first = await consume_memory_episode(session, memory_graph, pending_id=pending_id, lease_owner="w1")
        assert first.written is True

        # 第二次消费：记录已 done，领取不到（不是错误）。
        async with session_scope(get_settings()) as session:
            second = await consume_memory_episode(session, memory_graph, pending_id=pending_id, lease_owner="w2")
        assert second.written is False, "已完成的记录不得被再次领取"

        scoped = memory_graph.driver_for(_ACCOUNT)
        rows, _, _ = await scoped.execute_query("MATCH (e:Episodic) RETURN count(e) AS c")
        assert rows[0]["c"] == 1, "重复消费不得产生第二条 episode"
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# 载荷形状的边界（第 3 节：Worker 只凭自足载荷工作，缺键必须显式失败）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_occurred_at_fails_without_writing(memory_graph: MemoryGraph) -> None:
    """载荷缺 `occurred_at` **显式失败且不写图库**——不猜「就是现在」。

    猜时间会污染时间线（记忆回看的唯一载体），因此宁可失败。
    """
    await _clear()
    try:
        pending_id = await _enqueue(occurred_at=None)
        async with session_scope(get_settings()) as session:
            with pytest.raises(MemoryDataError, match="occurred_at"):
                await consume_memory_episode(session, memory_graph, pending_id=pending_id, lease_owner="w")

        scoped = memory_graph.driver_for(_ACCOUNT)
        rows, _, _ = await scoped.execute_query("MATCH (e:Episodic) RETURN count(e) AS c")
        assert rows[0]["c"] == 0, "载荷不合法时不得写图库"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_naive_occurred_at_is_rejected(memory_graph: MemoryGraph) -> None:
    """缺时区的 `occurred_at` 被拒绝——朴素时间会被解释成不同瞬间，破坏时间顺序。"""
    await _clear()
    try:
        pending_id = await _enqueue(occurred_at="2026-09-29T08:00:00")
        async with session_scope(get_settings()) as session:
            with pytest.raises(MemoryDataError, match="时区"):
                await consume_memory_episode(session, memory_graph, pending_id=pending_id, lease_owner="w")
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_missing_session_id_fails_without_writing(memory_graph: MemoryGraph) -> None:
    """来源缺 `session_id` 显式失败——没有来源的记忆无法核对（契约硬约束）。"""
    await _clear()
    occurred = datetime.now(timezone.utc)
    try:
        pending_id = await _enqueue(occurred_at=occurred.isoformat(), session_id=None)
        async with session_scope(get_settings()) as session:
            with pytest.raises(MemoryDataError, match="session_id"):
                await consume_memory_episode(session, memory_graph, pending_id=pending_id, lease_owner="w")
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_profile_item_kind_is_rejected_by_the_memory_consumer(memory_graph: MemoryGraph) -> None:
    """非 `memory_episode` 的 kind 被本消费者拒绝——按 kind 分派不得串台。"""
    await _clear()
    occurred = datetime.now(timezone.utc)
    try:
        pending_id = await _enqueue(kind=KIND_PROFILE_ITEM, occurred_at=occurred.isoformat())
        async with session_scope(get_settings()) as session:
            with pytest.raises(MemoryDataError, match="profile_item"):
                await consume_memory_episode(session, memory_graph, pending_id=pending_id, lease_owner="w")
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_consuming_an_unknown_pending_id_is_skipped_not_an_error(
    memory_graph: MemoryGraph,
) -> None:
    """消费一个不存在的 `pending_id` 返回 `written=False`，**不抛异常**。

    「没领到」是并发下的正常结果（已被他人领取、已终结、或记录不存在）；把它当异常会让
    兜底扫描把每次竞争都记成失败。
    """
    await _clear()
    try:
        async with session_scope(get_settings()) as session:
            result = await consume_memory_episode(
                session, memory_graph, pending_id="00000000-0000-4000-8000-000000000000", lease_owner="w"
            )
        assert result.written is False
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_deleted_memory_is_not_returned_after_write_path_completes(
    memory_graph: MemoryGraph,
) -> None:
    """写入链路与删除账本协同：写完再删，读路径不再返回它。

    这条把步骤 6（删除）与步骤 7（写入）接起来——两者分别可测，但**串起来**才是
    `AC-08` 在真实时序下的形态（先写入，后删除）。
    """
    from campfire.modules.memory.deletion import delete_episode

    await _clear()
    occurred = datetime.now(timezone.utc)
    try:
        pending_id = await _enqueue(occurred_at=occurred.isoformat())
        async with session_scope(get_settings()) as session:
            await consume_memory_episode(session, memory_graph, pending_id=pending_id, lease_owner="w")

        episode_uuid = derive_episode_uuid(PendingId(pending_id))
        episodes = await _read_timeline(memory_graph, _ACCOUNT)
        assert len(episodes) == 1

        async with session_scope(get_settings()) as session:
            await delete_episode(session, account_id=to_account_id(_ACCOUNT), episode_key=episode_uuid)
        async with session_scope(get_settings()) as session:
            keys = await deleted_episode_keys(session, _ACCOUNT)
        assert keys, "删除后账本应有记录（否则下面的断言不成立）"

        after = await _read_timeline(memory_graph, _ACCOUNT)
        assert after == [], "写入后删除的记忆不得再出现在时间线"
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# 半写节点的补偿（写入失败后不得留下「看起来已写入」的节点）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_write_leaves_no_readable_episode(memory_graph: MemoryGraph) -> None:
    """**抽取失败后，不得留下能被读路径返回的 episode**。

    为什么必须有这条（2026-09-29 实测发现的缺陷）：写入分两步——先预建节点（正文落库），
    再 `add_episode` 抽取派生事实。**第二步失败时节点已经存在**，而读路径把「图库里存在
    episode 节点」当作已写入（`MemoryEpisode.write_state` 就是靠这一点成立的），
    于是**一条从未成功写入的记忆会被当成已写入返回**——直接违反 `read_memory` 契约
    第 3 节（非 `done` 不得返回）与写入路径第 2 节的不变量。

    实测复现（修复前）：抽取抛错后 `read_timeline` 仍返回该条、`write_state='done'`、
    图库里 1 个节点。修复后：节点数 0、时间线空。

    判别性：去掉 `write_episode` 的**完成标记**（第三步的 `SET e.write_state`）与读路径的
    标记过滤，本用例会失败——即不变量落在数据与查询上，而不是「补偿一定跑得到」。
    """
    from campfire.modules.memory.errors import MemoryUnavailableError
    from campfire.modules.memory.identity import PendingId, derive_episode_uuid
    from campfire.modules.memory.store import write_episode

    await _clear()
    now = datetime.now(timezone.utc)
    key = derive_episode_uuid(PendingId("halfwrite-regression"))
    try:
        # 让抽取阶段抛错：替换 graphiti 的 add_episode 为一个必定失败的替身。
        async def _boom(**_kwargs):  # noqa: ANN202
            raise RuntimeError("模拟抽取失败")

        original = memory_graph.graphiti.add_episode
        memory_graph.graphiti.add_episode = _boom  # type: ignore[method-assign]
        try:
            with pytest.raises(MemoryUnavailableError):
                await write_episode(
                    memory_graph,
                    to_account_id(_ACCOUNT),
                    key,
                    content="这条从未成功写入",
                    occurred_at=now,
                    source_description="session=s1",
                )
        finally:
            memory_graph.graphiti.add_episode = original  # type: ignore[method-assign]

        # 图库里不得残留该节点（补偿删除仍应尽力清理）。
        scoped = memory_graph.driver_for(_ACCOUNT)
        rows, _, _ = await scoped.execute_query("MATCH (e:Episodic {uuid: $uuid}) RETURN count(e) AS c", uuid=key)
        assert rows[0]["c"] == 0, "抽取失败后不得留下半写节点"

        # 读路径也不得返回它（这才是契约的可观察面）。
        timeline = await _read_timeline(memory_graph, _ACCOUNT)
        assert timeline == [], "从未成功写入的记忆不得出现在时间线里"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_hard_kill_leftover_is_unreadable_by_both_paths(memory_graph: MemoryGraph) -> None:
    """**硬杀（无任何清理机会）遗留的半写数据，两条读路径都不得返回**。

    这是 C-1 修复的核心判别（2026-09-29 评审阻断级，独立复现）：此前「已写入」的判据是
    「图库里存在 episode 节点」，靠失败时的补偿删除维持。**进程被 SIGKILL / 部署重启时
    补偿代码根本不执行**，节点永久残留并被当成已写入返回。

    本用例不模拟异常，而是**真的制造「预建完成、抽取未完成」的持久状态**（把
    `add_episode` 换成「写入派生物后抛错」，再手动清掉 episode 节点以模拟硬杀后
    无人清理的现场），然后断言：
    - 时间线不返回它；
    - **引用它的派生事实也不被注入**（`add_episode` 可能已写入实体与边，
      `DETACH DELETE e` 删不掉它们——实测残留实体 2 个/边 1 条）。

    判别性：去掉读路径的 `write_state` 过滤，本用例失败。
    """
    from campfire.modules.memory.identity import PendingId, derive_episode_uuid
    from campfire.modules.memory.store import write_episode

    await _clear()
    now = datetime.now(timezone.utc)
    key = derive_episode_uuid(PendingId("hardkill-regression"))
    scoped = memory_graph.driver_for(to_account_id(_ACCOUNT))
    try:

        async def _partial(**_kwargs):  # noqa: ANN202
            # 模拟「派生物已落库，随后进程消失」：边引用本 episode。
            await scoped.execute_query(
                """
                MERGE (a:Entity {uuid: 'hk-a'}) SET a.name = '小明', a.group_id = $g
                MERGE (b:Entity {uuid: 'hk-b'}) SET b.name = '跑步', b.group_id = $g
                MERGE (a)-[e:RELATES_TO {uuid: 'hk-e'}]->(b)
                SET e.group_id = $g, e.name = 'REL', e.fact = '小明喜欢跑步',
                    e.valid_at = $t, e.created_at = $t, e.episodes = [$ep]
                """,
                g=_ACCOUNT,
                t=now.isoformat(),
                ep=key,
            )
            raise RuntimeError("进程在此刻消失（后续清理永不执行）")

        original = memory_graph.graphiti.add_episode
        memory_graph.graphiti.add_episode = _partial  # type: ignore[method-assign]
        try:
            with pytest.raises(MemoryUnavailableError):
                await write_episode(
                    memory_graph,
                    to_account_id(_ACCOUNT),
                    key,
                    content="硬杀遗留的那条",
                    occurred_at=now,
                    source_description="session=hk",
                )
        finally:
            memory_graph.graphiti.add_episode = original  # type: ignore[method-assign]

        # 先把 episode 节点恢复成「未完成」以忠实模拟硬杀现场（补偿删除已把它清掉，
        # 但真实硬杀时它仍在且无完成标记）。这里直接重建一个**无完成标记**的节点，
        # 正是硬杀后会留下的形状。
        await scoped.execute_query(
            """
            MERGE (e:Episodic {uuid: $u})
            SET e.name = 'memory', e.group_id = $g, e.content = '硬杀遗留的那条',
                e.valid_at = $t, e.created_at = $t, e.write_state = $pending
            """,
            u=key,
            g=_ACCOUNT,
            t=now.isoformat(),
            pending=EPISODE_WRITE_STATE_PENDING,
        )

        # 两条读路径都必须看不见它。
        timeline = await _read_timeline(memory_graph, _ACCOUNT)
        assert timeline == [], "硬杀遗留的半写 episode 不得出现在时间线"

        facts = await _read_emergency_facts(memory_graph, _ACCOUNT)
        assert facts.facts == [], f"引用未完成 episode 的派生事实不得被注入，实际注入 {[f.fact for f in facts.facts]}"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_retry_of_a_written_episode_does_not_downgrade_the_marker(memory_graph: MemoryGraph) -> None:
    """重试**已成功写入**的 episode 不得把完成标记降级（2026-09-29 自查，实测发现）。

    场景：第一次 `write_episode` 的 `add_episode` 成功、标记已写 `done`，但随后
    `mark_done` 因数据库抖动失败 → 记录仍是 `processing` → 租约过期 → 回收 → 重试。
    重试第一步是 `MERGE ... SET e = {...}`（**整节点替换**），实测会把 `write_state`
    从 `done` 覆盖成 `pending`；若这次 `add_episode` 又失败，**一条原本可读的记忆会
    变成不可读**（方向是 fail-closed，但属数据可见性缺陷）。

    修法：预建时若该节点已带完成标记，则**保持** `done`，不降级。

    判别性：把预建的 `write_state` 无条件写成 `pending`，本用例失败。
    """
    from campfire.modules.memory.identity import PendingId, derive_episode_uuid
    from campfire.modules.memory.store import EPISODE_WRITE_STATE_DONE, write_episode

    await _clear()
    now = datetime.now(timezone.utc)
    key = derive_episode_uuid(PendingId("downgrade-regression"))
    scoped = memory_graph.driver_for(to_account_id(_ACCOUNT))
    try:
        # 第一次写入：走真实路径（假 LLM 返回空实体，等价于「抽取成功」）。
        await write_episode(
            memory_graph,
            to_account_id(_ACCOUNT),
            key,
            content="第一次成功写入",
            occurred_at=now,
            source_description="session=1",
        )
        rows, _, _ = await scoped.execute_query("MATCH (e:Episodic {uuid: $u}) RETURN e.write_state AS ws", u=key)
        assert rows[0]["ws"] == EPISODE_WRITE_STATE_DONE, "首次写入后应带完成标记"

        # 第二次：同 uuid 重跑，但这次抽取失败（模拟重试且失败）。
        async def _boom(**_kwargs):  # noqa: ANN202
            raise RuntimeError("重试时抽取失败")

        original = memory_graph.graphiti.add_episode
        memory_graph.graphiti.add_episode = _boom  # type: ignore[method-assign]
        try:
            with pytest.raises(MemoryUnavailableError):
                await write_episode(
                    memory_graph,
                    to_account_id(_ACCOUNT),
                    key,
                    content="重试的正文",
                    occurred_at=now,
                    source_description="session=1",
                )
        finally:
            memory_graph.graphiti.add_episode = original  # type: ignore[method-assign]

        # 关键断言：原本可读的记忆必须仍然可读。
        rows, _, _ = await scoped.execute_query("MATCH (e:Episodic {uuid: $u}) RETURN e.write_state AS ws", u=key)
        assert rows[0]["ws"] == EPISODE_WRITE_STATE_DONE, (
            f"重试把已成功的标记降级成了 {rows[0]['ws']!r}——原本可读的记忆变得不可读"
        )
        timeline = await _read_timeline(memory_graph, _ACCOUNT)
        assert [e.episode_uuid for e in timeline] == [key], "已成功写入的记忆必须仍可读"
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# Worker 的错误分档（可重试 vs 不可重试）
# ---------------------------------------------------------------------------


def test_error_classes_are_disjoint_for_the_worker_classification() -> None:
    """**可重试与不可重试的两类错误必须分得开**（第 6 节的失败语义）。

    为什么必须有这条（2026-09-29 自查发现，实测确认）：`worker.py` 按类型分档——
    `MemoryUnavailableError` → 可重试（图库瞬时故障），`MemoryDataError` → 转 `dead`
    （载荷不合法，重试无用）。而 `MemoryUnavailableError` **是** `MemoryModuleError`
    的子类，所以若只按基类分档、或把两个分支的顺序写反，**图库一次瞬时故障就会把一条
    本来健康的记录永久判死**。

    这条断言把「两类可分」写进测试：`MemoryUnavailableError` **不是** `MemoryDataError`，
    反之亦然。若将来有人把 `MemoryUnavailableError` 改成继承 `MemoryDataError`
    （例如为了复用诊断字段），本用例会失败并提醒分档逻辑失效。
    """
    from campfire.modules.memory.errors import MemoryDataError, MemoryUnavailableError

    assert not issubclass(MemoryUnavailableError, MemoryDataError)
    assert not issubclass(MemoryDataError, MemoryUnavailableError)

    # 两者共同的上位是基类——这正是「不能只按基类分档」的原因。
    from campfire.modules.memory.errors import MemoryModuleError

    assert issubclass(MemoryUnavailableError, MemoryModuleError)
    assert issubclass(MemoryDataError, MemoryModuleError)


@pytest.mark.asyncio
async def test_worker_classifies_graph_failure_as_retryable_not_dead(memory_graph: MemoryGraph) -> None:
    """图库故障必须被记成**可重试失败**（`attempts+1`、回 `pending`），不能转 `dead`。

    这是上一条的端到端版本：直接调 `worker` 里那个任务函数，让图库调用抛
    `MemoryUnavailableError`（用一个「写入即失败」的图库替身），然后断言记录
    **仍是 `pending` 且 `attempts == 1`**，而不是 `dead`。
    """
    from campfire import worker as worker_module
    from campfire.modules.memory.errors import MemoryUnavailableError

    await _clear()
    occurred = datetime.now(timezone.utc)
    try:
        pending_id = await _enqueue(occurred_at=occurred.isoformat())

        class _BrokenGraph:
            """图库替身：任何写入都失败（模拟 FalkorDB 瞬时不可用）。"""

            def driver_for(self, _account):  # noqa: ANN001, ANN202
                raise MemoryUnavailableError("图库不可用", operation="probe", cause="ConnectionError")

        # 让任务用这个替身，而不是真实图库。
        original = worker_module._get_memory_graph
        worker_module._get_memory_graph = lambda: _BrokenGraph()  # type: ignore[assignment]
        try:
            with pytest.raises(MemoryUnavailableError):
                await worker_module.consume_memory_episode_task(pending_id, lease_owner="w")
        finally:
            worker_module._get_memory_graph = original  # type: ignore[assignment]

        async with session_scope(get_settings()) as session:
            row = (await session.execute(select(PendingWrite).where(PendingWrite.id == pending_id))).scalar_one()
        assert row.state == STATE_PENDING, "图库瞬时故障不得把记录判成 dead"
        assert row.attempts == 1, "可重试失败应记一次 attempts"
        assert row.next_attempt_at is not None, "应设退避时间"
        assert row.last_error is not None
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_worker_classifies_bad_payload_as_dead(memory_graph: MemoryGraph) -> None:
    """载荷不合法（`MemoryDataError`）→ **转 `dead`**：重试不会变好，不得无声重试。

    与上一条配对：两条一起把 Worker 的分档钉死（一类可重试、一类终结）。
    """
    await _clear()
    try:
        # 缺 occurred_at ⇒ consume 会抛 MemoryDataError。
        pending_id = await _enqueue(occurred_at=None)

        from campfire import worker as worker_module

        with pytest.raises(MemoryDataError):
            await worker_module.consume_memory_episode_task(pending_id, lease_owner="w")

        async with session_scope(get_settings()) as session:
            row = (await session.execute(select(PendingWrite).where(PendingWrite.id == pending_id))).scalar_one()
        assert row.state == STATE_DEAD, "载荷不合法应转 dead"
        assert row.finished_at is not None
        assert row.last_error is not None
    finally:
        await _clear()
