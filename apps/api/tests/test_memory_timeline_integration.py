"""集成测试：时间线回看的读写路径与删除过滤（真实 FalkorDB）。

对应 ``docs/技术设计/technical-details/通用记忆.md`` 第 3、4、7 节与
``read_memory`` 契约（`docs/技术设计/面/consult/tools/read_memory.md`）。

带 ``integration`` marker。显式跑法：

    docker compose up -d falkordb
    uv run pytest -m integration apps/api/tests/test_memory_timeline_integration.py

**注意（诚实声明）**：``addopts`` 里**没有** marker 过滤，因此默认 ``uv run pytest``
也会收集本文件。本文件**只依赖 FalkorDB**（不连 PostgreSQL），所以容器不可用时
「跳过」有效——但 `FalkorDB(...)` 构造本身会发网络 I/O，因此它必须在 try 内
（见夹具说明；此前放在 try 外，容器不可用时是 ERROR 而非 skip）。

**为什么用假模型客户端**：实体抽取要调 TokenHub，而当前 `.env` 的 `TOKENHUB_API_KEY`
是 `.env.example` 的占位符（实测两端点均 401，登记于 TODO `TECH-02`）。因此本文件注入
假 LLM 与假嵌入器——**只验证读写形状与删除过滤**，不验证抽取质量（那是 `TECH-18`，
需要真实凭据）。这样做的边界很明确：本文件通过**不代表**真实抽取可用。

锁住的行为：
1. 时间线按 `valid_at` **倒序**返回，且时间区间与关键词过滤真的生效（自建 Cypher，
   不是 `retrieve_episodes`）。
2. 删除过滤**下推到查询**：已删除的 episode 不返回（第 7 节：账本过滤是唯一生效点）。
3. 分区隔离：两个账号各自的图互不可见（第 1 节：group_id 在 FalkorDB 后端是图名）。
4. 写入幂等：同一确定性 uuid 重复写入只留一条 episode 节点。
5. 来源会话标识经 `source_description` 往返（`episode_metadata` 不落库，实测）。
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from campfire.core.config import EMBEDDING_DIM
from campfire.core.config import get_settings as _get_settings
from campfire.core.db import session_scope
from campfire.modules.memory.graph import MemoryGraph, OrderedCrossEncoder
from campfire.modules.memory.identity import PendingId, derive_episode_uuid, to_account_id
from campfire.modules.memory.store import (
    TIMELINE_MAX_LIMIT,
    read_timeline,
    write_episode,
)

from .conftest import connect_falkordb_or_skip

pytestmark = pytest.mark.integration


async def _read_timeline(graph, account, **kwargs):  # noqa: ANN001, ANN003, ANN201
    """调**公开**读入口（自动开一个关系库会话取删除账本）。

    2026-09-30 起 `read_timeline` 只收 `session`——「已删清单」由函数内部取，调用方
    无法漏传（此前传空列表会静默返回已删记忆）。本助手只是替测试开会话，不绕过过滤。
    """
    async with session_scope(_get_settings()) as session:
        return await read_timeline(session, graph, to_account_id(account), **kwargs)


async def _read_emergency_facts(graph, account, **kwargs):  # noqa: ANN001, ANN003, ANN201
    """调**公开**应急读入口（同上）。"""
    from campfire.modules.memory.derived import read_emergency_facts

    async with session_scope(_get_settings()) as session:
        return await read_emergency_facts(session, graph, to_account_id(account), **kwargs)


async def _clear_ledger() -> None:
    """清掉本文件两个账号的删除账本行（读入口自己取账本后必须做，见 fixture 的说明）。"""
    from sqlalchemy import delete

    from campfire.modules.memory.models import MemoryDeletionLedger

    async with session_scope(_get_settings()) as session:
        await session.execute(
            delete(MemoryDeletionLedger).where(MemoryDeletionLedger.account_id.in_([_ACCOUNT_A, _ACCOUNT_B]))
        )


#: 两个账号：用于验证分区隔离（各自的图）。
_ACCOUNT_A = "it_mem_acct_a"
_ACCOUNT_B = "it_mem_acct_b"


# ---------------------------------------------------------------------------
# 假模型客户端（不调真实供应商）
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def memory_graph() -> AsyncIterator[MemoryGraph]:
    """装配一个使用**假模型客户端**的记忆图库句柄。

    假 LLM 返回空实体/空边，因此不产生派生事实——本文件只测 episode 层。
    真实抽取质量属 `TECH-18`，需要有效凭据。
    """
    # 代理归一必须在构造 openai 客户端之前（见 graph.py 的说明与 conftest 的留档）。
    os.environ["no_proxy"] = "localhost,127.0.0.1"
    os.environ["NO_PROXY"] = "localhost,127.0.0.1"

    from graphiti_core.embedder.client import EmbedderClient
    from graphiti_core.graphiti import Graphiti
    from graphiti_core.llm_client.client import LLMClient
    from graphiti_core.llm_client.config import LLMConfig

    class _FakeEmbedder(EmbedderClient):
        async def create(self, input_data) -> list[float]:  # noqa: ANN001
            return [0.001] * EMBEDDING_DIM

    class _FakeLLM(LLMClient):
        def __init__(self) -> None:
            super().__init__(config=LLMConfig(api_key="test", model="fake"))

        async def _generate_response(
            self,
            messages=None,  # noqa: ANN001
            response_model=None,
            max_tokens=None,
            model_size=None,
            group_id=None,
            prompt_name=None,
            **kwargs,
        ):
            if response_model is not None:
                return {name: [] for name in response_model.model_fields}
            return {}

    # 连容器：构造 `FalkorDB(...)` 本身发网络 I/O，因此它必须在 try 内——
    # 细节与实测依据见 `conftest.connect_falkordb_or_skip`。
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
    # 清一次账本再开始：本文件自己会清理，但**同账号的行可能来自别的测试文件的历史
    # 运行**（账本是全局表），残留会让本文件的读断言莫名少条。
    await _clear_ledger()
    try:
        yield graph
    finally:
        # 走 driver_for 复用缓存驱动（而不是裸 clone）：裸 clone 每次新建驱动 +
        # 后台任务，清理阶段反复 clone 本身就是被测代码里那个泄漏的同一个坑。
        for account in (_ACCOUNT_A, _ACCOUNT_B):
            scoped = graph.driver_for(account)
            await scoped.execute_query("MATCH (n) DETACH DELETE n")
        # **删除账本也要清**（2026-09-30）：读入口现在自己取账本，而账本是**全局唯一**
        # 约束（`episode_key`）且与图库无关——不清就会跨用例残留，让「刚写的两条」
        # 被上个用例记的删除挡掉（实测：`assert len(before) == 2` 变成 1）。
        # 此前「已删清单」由调用方传入，测试可凭空构造，因此没有这个清理需求。
        await _clear_ledger()
        await graph.aclose()


async def _write(
    graph: MemoryGraph,
    account: str,
    pending: str,
    *,
    content: str,
    occurred_at: datetime,
    source: str = "session=s1 message=m1",
) -> str:
    """写入一条片段，返回派生出的 episode uuid。"""
    episode_uuid = derive_episode_uuid(PendingId(pending))
    await write_episode(
        graph,
        to_account_id(account),
        episode_uuid,
        content=content,
        occurred_at=occurred_at,
        source_description=source,
    )
    return episode_uuid


# ---------------------------------------------------------------------------
# 时间线读取
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeline_returns_newest_first_and_carries_source(memory_graph: MemoryGraph) -> None:
    """时间线按 `valid_at` 倒序返回，且每条带时间与来源会话标识。

    倒序是契约要求（"最近发生了什么"）；来源可核对是 `read_memory` 的硬约束。
    """
    now = datetime.now(timezone.utc)
    await _write(memory_graph, _ACCOUNT_A, "tl-1", content="最早的事", occurred_at=now - timedelta(days=2))
    await _write(memory_graph, _ACCOUNT_A, "tl-2", content="中间的事", occurred_at=now - timedelta(days=1))
    await _write(memory_graph, _ACCOUNT_A, "tl-3", content="最近的事", occurred_at=now, source="session=s9 message=m42")

    episodes = await _read_timeline(memory_graph, _ACCOUNT_A)

    assert [e.content for e in episodes] == ["最近的事", "中间的事", "最早的事"]
    assert episodes[0].source == "session=s9 message=m42"
    assert episodes[0].occurred_at > episodes[-1].occurred_at
    assert all(e.write_state == "done" for e in episodes)


@pytest.mark.asyncio
async def test_timeline_time_window_filters_both_ends(memory_graph: MemoryGraph) -> None:
    """`since`/`until` 真的过滤——这是自建 Cypher 的理由（`retrieve_episodes` 没有它）。

    两侧都测：只测一侧会让「只实现了 since 而忽略 until」的实现通过。
    """
    now = datetime.now(timezone.utc)
    await _write(memory_graph, _ACCOUNT_A, "tw-1", content="区间外-早", occurred_at=now - timedelta(days=10))
    await _write(memory_graph, _ACCOUNT_A, "tw-2", content="区间内", occurred_at=now - timedelta(days=5))
    await _write(memory_graph, _ACCOUNT_A, "tw-3", content="区间外-晚", occurred_at=now)

    episodes = await _read_timeline(
        memory_graph,
        _ACCOUNT_A,
        since=now - timedelta(days=6),
        until=now - timedelta(days=1),
    )

    assert [e.content for e in episodes] == ["区间内"]


@pytest.mark.asyncio
async def test_timeline_keyword_filter_is_case_insensitive_substring(memory_graph: MemoryGraph) -> None:
    """关键词过滤是大小写不敏感的子串匹配（契约的 `query` 参数）。"""
    now = datetime.now(timezone.utc)
    await _write(memory_graph, _ACCOUNT_A, "kw-1", content="他害怕嘈杂的超市", occurred_at=now - timedelta(days=1))
    await _write(memory_graph, _ACCOUNT_A, "kw-2", content="在家很放松", occurred_at=now)

    hit = await _read_timeline(memory_graph, _ACCOUNT_A, query="超市")
    assert [e.content for e in hit] == ["他害怕嘈杂的超市"]

    # 大小写不敏感：英文同样命中。
    await _write(memory_graph, _ACCOUNT_A, "kw-3", content="Sensory Overload", occurred_at=now)
    upper = await _read_timeline(memory_graph, _ACCOUNT_A, query="sensory")
    assert [e.content for e in upper] == ["Sensory Overload"]


@pytest.mark.asyncio
async def test_timeline_limit_is_bounded_by_server_cap(memory_graph: MemoryGraph) -> None:
    """`limit` 超上界时**收敛到服务端上界**（CORE-11：不信任调用方给的上限）。

    为什么不能像此前那样只断言 `len(episodes) <= TIMELINE_MAX_LIMIT`
    （2026-09-29 评审指出，已消融验证）：只写 3 条数据时那句断言**永远不会失败**——
    即使把 `store.py` 里的 `min(limit, TIMELINE_MAX_LIMIT)` 整段删掉，返回的仍是 3 条，
    断言照样通过。这属 AGENTS.md 明令禁止的「永远不会失败的检查」。

    现在的做法：**拦截实际发给图库的 `LIMIT` 参数**，直接断言它被收敛成上界。
    这样删掉收敛逻辑就会失败（传进去的会是 10_000）。
    """
    now = datetime.now(timezone.utc)
    await _write(memory_graph, _ACCOUNT_A, "cap-0", content="唯一一条", occurred_at=now)

    scoped = memory_graph.driver_for(_ACCOUNT_A)
    real_execute = scoped.execute_query
    seen_limits: list[object] = []

    async def spy(cypher, **params):  # noqa: ANN001, ANN202
        if "limit" in params:
            seen_limits.append(params["limit"])
        return await real_execute(cypher, **params)

    scoped.execute_query = spy  # type: ignore[method-assign]
    try:
        await _read_timeline(memory_graph, _ACCOUNT_A, limit=10_000)
    finally:
        scoped.execute_query = real_execute  # type: ignore[method-assign]

    assert seen_limits, "前置条件：查询必须带着 limit 参数发给图库"
    assert seen_limits[0] == TIMELINE_MAX_LIMIT, (
        f"传给图库的 LIMIT 应被收敛为 {TIMELINE_MAX_LIMIT}，实际 {seen_limits[0]}"
    )


@pytest.mark.asyncio
async def test_timeline_limit_is_honoured_when_below_the_cap(memory_graph: MemoryGraph) -> None:
    """小于上界的 `limit` 被**原样使用**，而不是一律抬到上界。

    与上一条互补：只测「收敛」会让「把 limit 写死成上界」的实现通过——那会让
    `read_memory(limit=5)` 实际返回 200 条。
    """
    now = datetime.now(timezone.utc)
    for index in range(3):
        await _write(
            memory_graph,
            _ACCOUNT_A,
            f"small-{index}",
            content=f"第 {index} 条",
            occurred_at=now - timedelta(days=index),
        )

    episodes = await _read_timeline(memory_graph, _ACCOUNT_A, limit=2)
    assert len(episodes) == 2, "limit=2 时必须只返回 2 条（不得抬到上界）"


@pytest.mark.asyncio
async def test_timeline_rejects_reversed_window(memory_graph: MemoryGraph) -> None:
    """非法时间区间显式失败（契约的失败语义），不静默返回全部。"""
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="since"):
        await _read_timeline(
            memory_graph,
            _ACCOUNT_A,
            since=now,
            until=now - timedelta(days=1),
        )


# ---------------------------------------------------------------------------
# 删除过滤（第 7 节：账本过滤是唯一生效点）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deleted_key_is_excluded_from_timeline(memory_graph: MemoryGraph) -> None:
    """账本里的 key 不出现在时间线里——删除生效点在读取侧。

    **2026-09-30 起走真实账本**：读函数的「已删清单」由函数内部取，调用方无法传入，
    因此这里必须用 `record_deletion` 真的记一笔（此前是直接传 `deleted_keys=[gone]`
    模拟删除——那种写法在新 API 上不可表达，正是本次加固的目的）。
    """
    from campfire.modules.memory.ledger import record_deletion

    now = datetime.now(timezone.utc)
    keep = await _write(memory_graph, _ACCOUNT_A, "del-1", content="保留的", occurred_at=now - timedelta(days=1))
    gone = await _write(memory_graph, _ACCOUNT_A, "del-2", content="要删除的", occurred_at=now)

    before = await _read_timeline(memory_graph, _ACCOUNT_A)
    assert len(before) == 2

    async with session_scope(_get_settings()) as session:
        await record_deletion(session, account_id=to_account_id(_ACCOUNT_A), episode_key=gone, reason="user_request")

    after = await _read_timeline(memory_graph, _ACCOUNT_A)
    assert [e.content for e in after] == ["保留的"]
    assert keep in [e.episode_uuid for e in after]


@pytest.mark.asyncio
async def test_deleted_filter_is_pushed_down_not_post_filtered(memory_graph: MemoryGraph) -> None:
    """删除过滤下推到查询：`limit` 的配额不被已删除项占用。

    这条是「下推 vs 读回再过滤」的判别用例：三条记录里删掉最近两条，取 `limit=1`
    时必须返回**剩下那条**。若实现是「先取 1 条再过滤」，会取到已删除的那条、
    过滤后得到空——本用例会失败。二者的差别正是第 7 节要求下推的原因。

    **2026-09-30 起走真实账本**（见上一个用例的说明）。
    """
    from campfire.modules.memory.ledger import record_deletion

    now = datetime.now(timezone.utc)
    oldest = await _write(memory_graph, _ACCOUNT_A, "pd-1", content="最老的", occurred_at=now - timedelta(days=2))
    newer = await _write(memory_graph, _ACCOUNT_A, "pd-2", content="较新", occurred_at=now - timedelta(days=1))
    newest = await _write(memory_graph, _ACCOUNT_A, "pd-3", content="最新", occurred_at=now)

    # 删掉最近两条：只有下推过滤才能让 limit=1 落到「最老的」上。
    async with session_scope(_get_settings()) as session:
        for key in (newest, newer):
            await record_deletion(session, account_id=to_account_id(_ACCOUNT_A), episode_key=key, reason="user_request")

    episodes = await _read_timeline(memory_graph, _ACCOUNT_A, limit=1)
    assert [e.episode_uuid for e in episodes] == [oldest], (
        "取 1 条时必须落在未被删除的那条上——若为空说明过滤发生在 limit 之后"
    )


# ---------------------------------------------------------------------------
# 分区隔离（第 1 节：group_id 在 FalkorDB 后端是图名）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accounts_are_isolated_in_separate_graphs(memory_graph: MemoryGraph) -> None:
    """两个账号的记忆互不可见——分区在 FalkorDB 后端是「各自一张图」。

    这是归属裁决（记忆按账号）在存储层的可执行证据。若哪天 group_id 退回
    「同图属性过滤」的语义，本用例仍会通过（属性过滤也隔离）；真正区分两种
    语义的是 `test_..._graph_is_selected_by_account`。
    """
    now = datetime.now(timezone.utc)
    await _write(memory_graph, _ACCOUNT_A, "iso-1", content="A 的记忆", occurred_at=now)
    await _write(memory_graph, _ACCOUNT_B, "iso-2", content="B 的记忆", occurred_at=now)

    a = await _read_timeline(memory_graph, _ACCOUNT_A)
    b = await _read_timeline(memory_graph, _ACCOUNT_B)

    assert [e.content for e in a] == ["A 的记忆"]
    assert [e.content for e in b] == ["B 的记忆"]


@pytest.mark.asyncio
async def test_storage_partition_is_a_separate_graph(memory_graph: MemoryGraph) -> None:
    """`group_id` 在 FalkorDB 后端就是**图名**，不是同图内的属性。

    直接在**默认图**（`campfire`）里写一条带 `group_id` 属性的节点，然后用该账号
    当图名去读——读不到。这条锁住第 1 节的实测结论：自建查询必须 clone 到同名库，
    否则会「写进去了但读不到」。
    """
    marker = f"it-mem-graphcheck-{uuid.uuid4().hex[:8]}"
    await memory_graph.driver.execute_query(
        """
        MERGE (e:Episodic {uuid: $uuid})
        SET e = {uuid: $uuid, name: 'graph-check', group_id: $group_id,
                 source: 'message', source_description: 'it',
                 content: $content, entity_edges: [],
                 created_at: $t, valid_at: $t}
        """,
        uuid=marker,
        group_id=_ACCOUNT_A,
        content="写在默认图里",
        t=datetime.now(timezone.utc).isoformat(),
    )
    try:
        # 默认图里有它。
        default_rows, _, _ = await memory_graph.driver.execute_query(
            "MATCH (e:Episodic {uuid: $uuid}) RETURN count(e) AS c", uuid=marker
        )
        assert default_rows[0]["c"] == 1

        # 但用账号当图名查不到——两处是不同的图。
        scoped = memory_graph.driver.clone(database=_ACCOUNT_A)
        scoped_rows, _, _ = await scoped.execute_query(
            "MATCH (e:Episodic {uuid: $uuid}) RETURN count(e) AS c", uuid=marker
        )
        assert scoped_rows[0]["c"] == 0, "group_id 不是同图内的属性分区：写在默认图的节点不会出现在账号图里"
    finally:
        await memory_graph.driver.execute_query("MATCH (e:Episodic {uuid: $uuid}) DETACH DELETE e", uuid=marker)


# ---------------------------------------------------------------------------
# 写入
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writing_same_deterministic_uuid_twice_keeps_one_episode(memory_graph: MemoryGraph) -> None:
    """同一 `pending_id` 派生的 uuid 写两次，只留一条 episode 节点（幂等）。"""
    now = datetime.now(timezone.utc)
    episode_uuid = await _write(memory_graph, _ACCOUNT_A, "idem-1", content="只应有一条", occurred_at=now)
    await _write(memory_graph, _ACCOUNT_A, "idem-1", content="只应有一条", occurred_at=now)

    scoped = memory_graph.driver.clone(database=_ACCOUNT_A)
    rows, _, _ = await scoped.execute_query("MATCH (e:Episodic {uuid: $uuid}) RETURN count(e) AS c", uuid=episode_uuid)
    assert rows[0]["c"] == 1, "同 uuid 重复写入必须只留一条 episode"

    episodes = await _read_timeline(memory_graph, _ACCOUNT_A)
    assert len(episodes) == 1


@pytest.mark.asyncio
async def test_write_rejects_empty_content_and_source(memory_graph: MemoryGraph) -> None:
    """空内容或空来源显式失败——没有来源的记忆无法核对（契约硬约束）。"""
    from campfire.modules.memory.errors import MemoryDataError

    now = datetime.now(timezone.utc)
    episode_uuid = derive_episode_uuid(PendingId("bad-1"))
    with pytest.raises(MemoryDataError, match="内容"):
        await write_episode(
            memory_graph,
            to_account_id(_ACCOUNT_A),
            episode_uuid,
            content="",
            occurred_at=now,
            source_description="session=s1",
        )
    with pytest.raises(MemoryDataError, match="来源"):
        await write_episode(
            memory_graph,
            to_account_id(_ACCOUNT_A),
            episode_uuid,
            content="有内容",
            occurred_at=now,
            source_description="",
        )


# ---------------------------------------------------------------------------
# 应急预注入的取数（派生事实层，第 6、7 节）
# ---------------------------------------------------------------------------


async def _write_edge(
    graph: MemoryGraph,
    account: str,
    edge_uuid: str,
    *,
    fact: str,
    valid_at: datetime,
    invalid_at: datetime | None = None,
    episodes: list[str] | None = None,
) -> None:
    """直接落一条派生事实边（不走抽取——假 LLM 不产出实体，见文件头说明）。

    **同时为每个来源 episode 建一个带完成标记的 Episodic 节点**（2026-09-29 加）：
    派生事实的注入现在要求「至少一条来源 episode **已完成**」（`write_state='done'`，
    见 `derived.read_emergency_facts` 的说明）。真实流程里这些节点由 `write_episode`
    预建并在 `add_episode` 成功后打标记；此前本夹具只写边、不写节点，是一种
    **现实中不存在的形状**——而且恰好等于「抽取中途失败、补偿删掉 episode 但残留了边」
    这一危险形状（评审 C-1b）。补上节点后夹具才代表「已成功写入的记忆」。
    """
    scoped = graph.driver.clone(database=account)
    for episode_uuid in episodes or []:
        await scoped.execute_query(
            """
            MERGE (x:Episodic {uuid: $uuid})
            SET x.name = 'ep', x.group_id = $g, x.content = '来源片段',
                x.valid_at = $t, x.created_at = $t, x.write_state = 'done'
            """,
            uuid=episode_uuid,
            g=account,
            t=valid_at.isoformat(),
        )
    await scoped.execute_query(
        """
        MERGE (a:Entity {uuid: $a_id}) SET a.name = 'A', a.group_id = $g
        MERGE (b:Entity {uuid: $b_id}) SET b.name = 'B', b.group_id = $g
        MERGE (a)-[e:RELATES_TO {uuid: $uid}]->(b)
        SET e.group_id = $g, e.name = 'REL', e.fact = $fact,
            e.valid_at = $valid, e.invalid_at = $invalid,
            e.episodes = $episodes, e.created_at = $valid
        """,
        a_id=f"A:{account}",
        b_id=f"B:{account}",
        uid=edge_uuid,
        g=account,
        fact=fact,
        valid=valid_at.isoformat(),
        invalid=(invalid_at.isoformat() if invalid_at else None),
        episodes=episodes or [],
    )


@pytest.mark.asyncio
async def test_emergency_facts_exclude_invalidated_edges(memory_graph: MemoryGraph) -> None:
    """**时效过滤**：`invalid_at` 非空的边不得注入。

    这是 `RQ-MEM-01`（过期或已被推翻的内容不得作为当前依据误导后续输出）在取数层的
    唯一落点。`EntityEdge.get_by_group_ids` **不过滤 invalid_at**（第 4 节实测），
    因此必须自建查询——若哪天改回用上游方法，本用例会失败。
    """

    now = datetime.now(timezone.utc)
    await _write_edge(
        memory_graph,
        _ACCOUNT_A,
        "ef-valid",
        fact="当前有效的事实",
        valid_at=now - timedelta(days=1),
        episodes=["ep-v"],
    )
    await _write_edge(
        memory_graph,
        _ACCOUNT_A,
        "ef-stale",
        fact="已被推翻的事实",
        valid_at=now - timedelta(days=3),
        invalid_at=now - timedelta(days=1),
        episodes=["ep-s"],
    )

    result = await _read_emergency_facts(memory_graph, _ACCOUNT_A)
    facts = [f.fact for f in result.facts]
    assert facts == ["当前有效的事实"], "失效边被当成『当前认识』注入会误导输出"
    assert not result.is_empty


@pytest.mark.asyncio
async def test_emergency_facts_empty_account_is_empty_not_error(memory_graph: MemoryGraph) -> None:
    """**没有记忆 ≠ 图库不可用**：空账号返回空结果，不抛异常。

    这是第 6 节的硬要求，也是不用 `EntityEdge.get_by_group_ids` 的原因之一——
    它对空分区抛 `GroupsEdgesNotFoundError`，会把新账号误报成故障。
    """

    result = await _read_emergency_facts(memory_graph, _ACCOUNT_B)
    assert result.is_empty
    assert result.facts == []


@pytest.mark.asyncio
async def test_emergency_facts_multi_source_deletion_uses_any_not_all(memory_graph: MemoryGraph) -> None:
    """**多来源边的删除判据是「至少一条来源被删即排除」**（第 7 节）。

    判别性说明：边 `ef-multi` 的来源是两个 episode，账本里只删了其中一个。
    - 正确判据（any）→ 该边被排除；
    - 错判据（all，要求全部来源都被删）→ 该边**仍被注入**。
    两种实现结果不同，因此本用例真的能判别实现，不是恒过断言。

    **2026-09-30 起走真实账本**：来源 key 用 `derive_episode_uuid` 派生（账本的
    `episode_key` 是 UUID 且经 `to_episode_key` 校验，此前的 `"ep-gone"` 这类字面量
    已无法记账）。
    """
    from campfire.modules.memory.ledger import record_deletion

    now = datetime.now(timezone.utc)
    keep_key = derive_episode_uuid(PendingId("ef-multi-keep"))
    gone_key = derive_episode_uuid(PendingId("ef-multi-gone"))
    await _write_edge(
        memory_graph,
        _ACCOUNT_A,
        "ef-multi",
        fact="多来源事实",
        valid_at=now - timedelta(days=1),
        episodes=[keep_key, gone_key],
    )
    await _write_edge(
        memory_graph,
        _ACCOUNT_A,
        "ef-clean",
        fact="来源未被删的事实",
        valid_at=now - timedelta(days=2),
        episodes=[keep_key],
    )

    async with session_scope(_get_settings()) as session:
        await record_deletion(
            session, account_id=to_account_id(_ACCOUNT_A), episode_key=gone_key, reason="user_request"
        )

    result = await _read_emergency_facts(memory_graph, _ACCOUNT_A)
    facts = [f.fact for f in result.facts]
    assert facts == ["来源未被删的事实"], "只删了部分来源的边仍被注入——删除判据用成了『全部来源被删』"


@pytest.mark.asyncio
async def test_edges_with_empty_episodes_are_kept_but_missing_property_is_excluded(
    memory_graph: MemoryGraph,
) -> None:
    """`episodes` 的**两种空形状行为不同**，且都必须被钉住（2026-09-29 对照实验）。

    为什么必须有这条：`derived.py` 原 docstring 写「没有 `episodes` 属性**或**该属性为空
    的边都会被保留」——**前者是错的**。实测三种形状：

    | `e.episodes` | 过滤后 |
    |---|---|
    | `[被删 uuid]` | 排除 |
    | `[]` | **保留** |
    | 属性缺失（`null`） | **排除** |

    根因：`any()` 对空列表返回 `false`（取反为 `true` ⇒ 行满足 `WHERE`），
    而对 `null` 返回 `null`（`NOT null` 不为 `true` ⇒ 行**不**满足 `WHERE`）。

    **方法学说明**：只跑「带过滤」的实验组无法区分「被 `WHERE` 排除」与
    「`MATCH` 没匹配到」——本用例因此**同时**断言对照组（不带过滤时三种形状都能匹配到），
    这样「缺失属性被排除」才是被过滤造成的、而非漏查。
    **2026-09-30 起走真实账本**：账本**必须非空**，否则「删除过滤」那段条件根本不会
    拼进查询（实现里是 `if deleted_keys:`），三种形状的对照就失去意义。因此这里真的记
    一笔删除，用它作为「被删 uuid」那一列。
    """
    from campfire.modules.memory.ledger import record_deletion

    now = datetime.now(timezone.utc)
    scoped = memory_graph.driver_for(to_account_id(_ACCOUNT_A))
    deleted_key = derive_episode_uuid(PendingId("ef-deleted-shape"))
    async with session_scope(_get_settings()) as session:
        await record_deletion(
            session, account_id=to_account_id(_ACCOUNT_A), episode_key=deleted_key, reason="user_request"
        )

    # `_write_edge` 总会写 episodes，因此缺失属性这一种形状需直接落库。
    await _write_edge(
        memory_graph,
        _ACCOUNT_A,
        "ef-empty-eps",
        fact="来源为空的边",
        valid_at=now - timedelta(days=1),
        episodes=[],
    )
    await scoped.execute_query(
        """
        MATCH (a:Entity {uuid: $a_id})
        MERGE (b:Entity {uuid: $b_id}) SET b.name = 'B', b.group_id = $g
        MERGE (a)-[e:RELATES_TO {uuid: 'ef-no-eps'}]->(b)
        SET e.group_id = $g, e.name = 'REL', e.fact = '属性缺失的边',
            e.valid_at = $valid, e.invalid_at = null, e.created_at = $valid
        """,
        a_id=f"A:{_ACCOUNT_A}",
        b_id=f"B:{_ACCOUNT_A}",
        g=_ACCOUNT_A,
        valid=(now - timedelta(days=2)).isoformat(),
    )

    # 对照组：不带删除过滤时，两种形状都必须能匹配到（否则下面的断言会误判）。
    # **注意关系用 `-[e:RELATES_TO]->` 而非 `(e:RELATES_TO)`**——派生事实是**边**，
    # 用节点语法查会静默返回空集，把「查错了」误当成「被过滤了」。
    control, _, _ = await scoped.execute_query(
        "MATCH (n:Entity)-[e:RELATES_TO]->(m:Entity) WHERE e.group_id = $g RETURN e.uuid AS uuid ORDER BY e.uuid",
        g=_ACCOUNT_A,
    )
    control_uuids = {r["uuid"] for r in control}
    assert {"ef-empty-eps", "ef-no-eps"} <= control_uuids, f"对照组应能匹配到两种形状的边，实际 {sorted(control_uuids)}"

    result = await _read_emergency_facts(memory_graph, _ACCOUNT_A)
    facts = [f.fact for f in result.facts]
    assert "来源为空的边" in facts, "episodes=[] 的边应被保留（any() 对空列表返回 false）"
    assert "属性缺失的边" not in facts, (
        "episodes 属性缺失的边应被排除（any() 返回 null，NOT null 不为 true）——原 docstring 称它会被保留，实测推翻"
    )


@pytest.mark.asyncio
async def test_emergency_facts_respects_char_budget(memory_graph: MemoryGraph) -> None:
    """**字符预算**独立于条数上限：超预算时截断并如实标注。

    第 5 节：条数上限不能代替字符上限（`fact` 长度无界）。这里给一个只放得下一条的
    预算，验证：不超预算、且 `truncated_by_chars` 如实报告被丢掉的条数
    （静默截断会让调用方以为「已注入全部记忆」）。
    """

    now = datetime.now(timezone.utc)
    for index in range(3):
        await _write_edge(
            memory_graph,
            _ACCOUNT_A,
            f"ef-budget-{index}",
            fact="X" * 40,
            valid_at=now - timedelta(days=index),
            episodes=[f"ep-{index}"],
        )

    result = await _read_emergency_facts(memory_graph, _ACCOUNT_A, char_budget=45)
    assert len(result.facts) == 1, "字符预算应只放得下一条"
    assert sum(len(f.fact) for f in result.facts) <= 45
    assert result.truncated_by_chars == 2, "被截断的条数必须如实回报"


@pytest.mark.asyncio
async def test_derived_facts_are_isolated_per_account(memory_graph: MemoryGraph) -> None:
    """派生事实同样按账号分区——另一账号的图里取不到。"""

    now = datetime.now(timezone.utc)
    await _write_edge(
        memory_graph,
        _ACCOUNT_A,
        "ef-iso-a",
        fact="A 的事实",
        valid_at=now,
        episodes=["ep-a"],
    )
    await _write_edge(
        memory_graph,
        _ACCOUNT_B,
        "ef-iso-b",
        fact="B 的事实",
        valid_at=now,
        episodes=["ep-b"],
    )

    a = await _read_emergency_facts(memory_graph, _ACCOUNT_A)
    b = await _read_emergency_facts(memory_graph, _ACCOUNT_B)

    assert [f.fact for f in a.facts] == ["A 的事实"]
    assert [f.fact for f in b.facts] == ["B 的事实"]


# ---------------------------------------------------------------------------
# 驱动缓存（防「每条查询泄漏一个驱动 + 一个后台任务」）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_driver_for_reuses_one_driver_per_account(memory_graph: MemoryGraph) -> None:
    """`driver_for` 对同一账号返回**同一个驱动对象**、且不新增后台任务。

    为什么必须有这条（2026-09-29 我自查发现的真实缺陷）：此前 `account_driver` 是
    裸 `clone`，实测同一账号连续两次调用返回**两个不同对象**、pending task 计数
    2→3→4——即每条查询泄漏一个驱动与一个建索引的后台任务（模块自己的文档还写着
    「不得在每条查询路径上 clone」，代码却没照做）。

    判别性：若实现退回裸 `clone`，`is` 断言与任务计数断言都会失败。
    """
    account = "it_mem_cache_probe"

    def own_pending_index_tasks() -> int:
        """**本图库自己的**克隆驱动里未完成的建索引任务数。

        为什么不扫 `asyncio.all_tasks()`（2026-10-01 改）：事件循环作用域已设为
        session（见 pyproject 的说明），整轮测试共用一个循环，于是 `all_tasks()`
        会把**前序用例**残留的任务一起数进来。实测该写法会造成假失败：
        人为在前一个用例留下一个未完成的 `build_indices` 任务后，本断言失败
        （function 作用域下则看不到）。改看本图库自己的驱动，既隔离又仍有判别力
        —— 裸 clone 会往 `account_drivers` 里塞新驱动，新的未完成任务随之可见。
        """
        return sum(
            1
            for driver in memory_graph.account_drivers.values()
            if driver is not memory_graph.driver
            and (task := getattr(driver, "_init_task", None)) is not None
            and not task.done()
        )

    # 第一次取驱动**会**新建一个驱动并调度它的建索引任务——这是允许的（首次访问）。
    first = memory_graph.driver_for(account)
    after_first = own_pending_index_tasks()

    # 关键断言：**第二次**取同一账号不得再新建驱动、也不得再多一个后台任务。
    second = memory_graph.driver_for(account)
    assert first is second, "同一账号必须复用同一个驱动，否则每条查询泄漏一个驱动"
    assert own_pending_index_tasks() == after_first, (
        f"复用缓存的驱动不得新增后台任务（{after_first} -> {own_pending_index_tasks()}）"
    )

    # 同库名时 clone 本就返回自身（实测），不应占用缓存名额。
    same_db = memory_graph.driver_for("campfire")
    assert same_db is memory_graph.driver, "配置库名应返回 base 驱动本身"
    assert account in memory_graph.account_drivers


@pytest.mark.asyncio
async def test_driver_cache_evicts_when_full(memory_graph: MemoryGraph) -> None:
    """驱动缓存**有界**（CORE-11）：超过上界时淘汰最早插入的条目。

    为什么不写 `assert len(cache) <= max(initial + 1, MAX_CACHED_ACCOUNT_DRIVERS)`
    （2026-09-29 评审指出，已消融验证）：那个断言**恒真**——右边取 `max` 后必然
    不小于 `initial + 1`，即使把 `driver_for` 里的整段淘汰逻辑删掉也照样通过。

    现在的做法：用一个**临时调小的上界**真正压满缓存，验证：(a) 规模不超过上界，
    (b) 最早插入的那条被淘汰（FIFO），(c) 最近插入的仍在。
    为此把模块常量临时改小——这是**有意的**，因为构造 64 个驱动太慢，而我们要验的是
    「淘汰会不会发生」，不是「64 这个数字是多少」。
    """
    from campfire.modules.memory import graph as graph_module

    original_cap = graph_module.MAX_CACHED_ACCOUNT_DRIVERS
    test_cap = 3
    graph_module.MAX_CACHED_ACCOUNT_DRIVERS = test_cap
    memory_graph.account_drivers.clear()
    try:
        accounts = [f"it_mem_evict_{index}" for index in range(test_cap + 2)]
        for account in accounts:
            memory_graph.driver_for(account)

        assert len(memory_graph.account_drivers) <= test_cap, (
            f"缓存规模不得超过上界 {test_cap}，实际 {len(memory_graph.account_drivers)}"
        )
        assert accounts[0] not in memory_graph.account_drivers, "最早插入的条目应被淘汰（FIFO）"
        assert accounts[-1] in memory_graph.account_drivers, "最近插入的条目应仍在缓存"
    finally:
        graph_module.MAX_CACHED_ACCOUNT_DRIVERS = original_cap
        memory_graph.account_drivers.clear()


@pytest.mark.asyncio
async def test_aclose_clears_the_driver_cache(memory_graph: MemoryGraph) -> None:
    """`aclose()` 清空驱动缓存，且**不留下未完成的**后台建索引任务。

    ## 为什么断言只看「本图库自己的驱动」

    原写法扫 `asyncio.all_tasks()` 找未完成的 `build_indices` 任务。事件循环作用域
    改为 session 后（见 pyproject 的说明），整轮测试共用一个循环，于是 `all_tasks()`
    把**前序用例**残留的任务一起看到——实测在前一用例留下一个未完成的
    `build_indices` 任务后本用例失败，而 function 作用域下不会，即失败与被测代码
    无关。改看本图库自己的驱动即可隔离。

    ## 覆盖边界（本次实测结论）

    这条断言**抓不到「取消被消融」**：初始化任务是对已存在索引的幂等写入，实测约
    0.3 秒内自行 done；消融 `_cancel_driver_init_task` 后本用例在两种作用域下都
    照样通过。「取消确实发生」由**确定性单测**覆盖——见下一条
    `test_cancel_driver_init_task_really_cancels`，那里用不会自行结束的合成任务，
    消融后必然失败。
    """
    memory_graph.driver_for("it_mem_cache_probe_3")
    assert memory_graph.account_drivers, "前置条件：缓存里应已有条目"

    # `aclose()` 会清空 account_drivers，故先快照本图库**自己的**克隆驱动任务。
    clone_tasks = [
        task
        for driver in memory_graph.account_drivers.values()
        if driver is not memory_graph.driver and (task := getattr(driver, "_init_task", None)) is not None
    ]

    await memory_graph.aclose()

    assert memory_graph.account_drivers == {}, "关闭后不得留下缓存的驱动引用"
    still_pending = [task for task in clone_tasks if not task.done()]
    assert not still_pending, (
        f"关闭后仍有 {len(still_pending)} 个后台索引任务未结束——收口失败会让它在客户端关闭后继续跑并抛 ConnectionError"
    )


@pytest.mark.asyncio
async def test_cancel_driver_init_task_really_cancels() -> None:
    """`_cancel_driver_init_task` 必须**真的取消**任务，而不是只等它自己结束。

    ## 为什么用合成任务而不是真实驱动（确定性）

    真实 `_init_task` 是对已存在索引的幂等写入，实测约 0.3 秒内自行 done——用真实
    驱动写断言只能观测到「碰巧已完成」，消融掉 `task.cancel()` 也照样通过（实测：
    该消融在 function 与 session 两种循环作用域下都不被现有用例抓到）。
    这里用一个**永不自行结束**的任务，把「取消」变成可判定的单一变量。

    判别性（实测）：注释掉 `task.cancel()` 后本用例失败（任务仍 pending），
    恢复后通过。
    """
    from campfire.modules.memory.graph import _cancel_driver_init_task

    started = asyncio.Event()

    async def never_finishes() -> None:
        started.set()
        await asyncio.sleep(3600)  # 不会被真实等待，只用于模拟「长期运行的后台任务」

    task = asyncio.create_task(never_finishes())
    await asyncio.wait_for(started.wait(), timeout=5)

    class _DriverWithInitTask:
        """只带 `_init_task` 的最小替身：该函数只依赖这一个属性。"""

        def __init__(self, init_task: asyncio.Task[None]) -> None:
            self._init_task = init_task

    try:
        await _cancel_driver_init_task(_DriverWithInitTask(task))
        assert task.cancelled(), "任务未被取消——收口只等它结束，客户端关闭后它仍会抛错"
    finally:
        if not task.done():
            task.cancel()


@pytest.mark.asyncio
async def test_aclose_closes_the_shared_client_exactly_once(memory_graph: MemoryGraph) -> None:
    """**共享的 falkordb 客户端只被关闭一次**，不随缓存条目数重复关。

    为什么必须有这条（2026-09-29 评审发现，实测复现）：克隆驱动与 base **共享同一个
    falkordb 客户端**（实测 `clone.client is base.client`），而 `FalkorDriver.close()`
    内部就是 `await self.client.aclose()`。此前 `aclose()` 对每个缓存驱动调一次
    `close()`，实测 3 个账号时**同一个客户端被关 4 次**，会打断在途查询
    （`ConnectionError`）。模块 docstring 当时还宣称「不重复关客户端」——被实测否证。

    判别性：把 `aclose()` 里的 `_cancel_driver_init_task` 换回 `await scoped.close()`
    就会失败（计数变 4）。
    """
    for account in ("it_mem_close_a", "it_mem_close_b", "it_mem_close_c"):
        memory_graph.driver_for(account)

    client = memory_graph.driver.client
    # 前置条件：三个缓存驱动的客户端确实是同一个对象（本用例的前提）。
    for account in ("it_mem_close_a", "it_mem_close_b", "it_mem_close_c"):
        assert memory_graph.driver_for(account).client is client

    calls: list[str] = []
    original = client.aclose

    async def counting_aclose():  # noqa: ANN202
        calls.append("aclose")
        return await original()

    client.aclose = counting_aclose  # type: ignore[method-assign]
    await memory_graph.aclose()

    assert len(calls) == 1, f"共享客户端应只关一次，实际关了 {len(calls)} 次"


@pytest.mark.asyncio
async def test_driver_for_validates_the_account_key(memory_graph: MemoryGraph) -> None:
    """`driver_for` 做**入口校验**：畸形账号键不得成为图名或占用缓存。

    为什么必须有这条（2026-09-29 评审发现）：此前 `driver_for` 接受任意字符串，实测
    含换行/分号的键、5000 字符的键、以及框架哨兵 `'_'`（会落到 `default_db`）
    都会被接受。它是两条读路径与缓存的唯一共同入口，校验放这里比要求每个调用方
    记得调 `to_account_id` 可靠。
    """
    from campfire.modules.memory.identity import AccountIdError

    bad_keys = (
        "bad\nname; DROP",
        "x" * 5000,
        "_",  # 框架哨兵：clone 会落到 default_db
        "",  # 空
        "acct.aaa",  # Graphiti 的 group_id 判据不允许点
    )
    for bad in bad_keys:
        with pytest.raises(AccountIdError):
            memory_graph.driver_for(bad)
        assert bad not in memory_graph.account_drivers, f"被拒的键不得进入缓存：{bad!r}"

    # 合法键仍然可用（防止把校验做成「一律拒绝」）。
    assert memory_graph.driver_for("it_mem_valid_account") is not None
