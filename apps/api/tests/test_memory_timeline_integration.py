"""集成测试：时间线回看的读写路径与删除过滤（真实 FalkorDB）。

对应 ``docs/技术设计/technical-details/通用记忆.md`` 第 3、4、7 节与
``read_memory`` 契约（`docs/技术设计/面/consult/tools/read_memory.md`）。

带 ``integration`` marker，默认不在 ``uv run pytest`` 中运行；显式跑法：

    docker compose up -d falkordb
    uv run pytest -m integration apps/api/tests/test_memory_timeline_integration.py

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

import os
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from campfire.core.config import EMBEDDING_DIM
from campfire.modules.memory.graph import MemoryGraph, OrderedCrossEncoder
from campfire.modules.memory.identity import PendingId, derive_episode_uuid, to_account_id
from campfire.modules.memory.store import (
    TIMELINE_MAX_LIMIT,
    read_timeline,
    write_episode,
)

pytestmark = pytest.mark.integration

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

    from falkordb.asyncio import FalkorDB
    from graphiti_core.driver.falkordb_driver import FalkorDriver
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

    client = FalkorDB(host="localhost", port=6380)
    driver = FalkorDriver(falkor_db=client, database="campfire")
    try:
        await driver.execute_query("RETURN 1 AS ok")
    except Exception as exc:  # noqa: BLE001
        await client.aclose()
        pytest.skip(f"FalkorDB 不可用（{type(exc).__name__}）——先 docker compose up -d falkordb")

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
        for account in (_ACCOUNT_A, _ACCOUNT_B):
            scoped = driver.clone(database=account)
            await scoped.execute_query("MATCH (n) DETACH DELETE n")
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

    episodes = await read_timeline(memory_graph, to_account_id(_ACCOUNT_A), deleted_keys=[])

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

    episodes = await read_timeline(
        memory_graph,
        to_account_id(_ACCOUNT_A),
        deleted_keys=[],
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

    hit = await read_timeline(memory_graph, to_account_id(_ACCOUNT_A), deleted_keys=[], query="超市")
    assert [e.content for e in hit] == ["他害怕嘈杂的超市"]

    # 大小写不敏感：英文同样命中。
    await _write(memory_graph, _ACCOUNT_A, "kw-3", content="Sensory Overload", occurred_at=now)
    upper = await read_timeline(memory_graph, to_account_id(_ACCOUNT_A), deleted_keys=[], query="sensory")
    assert [e.content for e in upper] == ["Sensory Overload"]


@pytest.mark.asyncio
async def test_timeline_limit_is_bounded_by_server_cap(memory_graph: MemoryGraph) -> None:
    """`limit` 超上界时被收敛（CORE-11：不信任调用方给的上限）。

    这里只断言「不会返回超过上界」——不构造 200+ 条数据（那会拖慢集成测试），
    而是给一个超大 limit 并确认返回条数 ≤ 服务端上界。
    """
    now = datetime.now(timezone.utc)
    for index in range(3):
        await _write(
            memory_graph, _ACCOUNT_A, f"cap-{index}", content=f"第 {index} 条", occurred_at=now - timedelta(days=index)
        )

    episodes = await read_timeline(memory_graph, to_account_id(_ACCOUNT_A), deleted_keys=[], limit=10_000)
    assert len(episodes) <= TIMELINE_MAX_LIMIT
    assert len(episodes) == 3


@pytest.mark.asyncio
async def test_timeline_rejects_reversed_window(memory_graph: MemoryGraph) -> None:
    """非法时间区间显式失败（契约的失败语义），不静默返回全部。"""
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="since"):
        await read_timeline(
            memory_graph,
            to_account_id(_ACCOUNT_A),
            deleted_keys=[],
            since=now,
            until=now - timedelta(days=1),
        )


# ---------------------------------------------------------------------------
# 删除过滤（第 7 节：账本过滤是唯一生效点）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deleted_key_is_excluded_from_timeline(memory_graph: MemoryGraph) -> None:
    """账本里的 key 不出现在时间线里——删除生效点在读取侧。"""
    now = datetime.now(timezone.utc)
    keep = await _write(memory_graph, _ACCOUNT_A, "del-1", content="保留的", occurred_at=now - timedelta(days=1))
    gone = await _write(memory_graph, _ACCOUNT_A, "del-2", content="要删除的", occurred_at=now)

    before = await read_timeline(memory_graph, to_account_id(_ACCOUNT_A), deleted_keys=[])
    assert len(before) == 2

    after = await read_timeline(memory_graph, to_account_id(_ACCOUNT_A), deleted_keys=[gone])
    assert [e.content for e in after] == ["保留的"]
    assert keep in [e.episode_uuid for e in after]


@pytest.mark.asyncio
async def test_deleted_filter_is_pushed_down_not_post_filtered(memory_graph: MemoryGraph) -> None:
    """删除过滤下推到查询：`limit` 的配额不被已删除项占用。

    这条是「下推 vs 读回再过滤」的判别用例：三条记录里删掉最近两条，取 `limit=1`
    时必须返回**剩下那条**。若实现是「先取 1 条再过滤」，会取到已删除的那条、
    过滤后得到空——本用例会失败。二者的差别正是第 7 节要求下推的原因。
    """
    now = datetime.now(timezone.utc)
    oldest = await _write(memory_graph, _ACCOUNT_A, "pd-1", content="最老的", occurred_at=now - timedelta(days=2))
    newer = await _write(memory_graph, _ACCOUNT_A, "pd-2", content="较新", occurred_at=now - timedelta(days=1))
    newest = await _write(memory_graph, _ACCOUNT_A, "pd-3", content="最新", occurred_at=now)

    episodes = await read_timeline(memory_graph, to_account_id(_ACCOUNT_A), deleted_keys=[newest, newer], limit=1)
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

    a = await read_timeline(memory_graph, to_account_id(_ACCOUNT_A), deleted_keys=[])
    b = await read_timeline(memory_graph, to_account_id(_ACCOUNT_B), deleted_keys=[])

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

    episodes = await read_timeline(memory_graph, to_account_id(_ACCOUNT_A), deleted_keys=[])
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
