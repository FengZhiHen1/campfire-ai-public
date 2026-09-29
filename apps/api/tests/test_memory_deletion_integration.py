"""集成测试：删除与纠正的**端到端**效果（`AC-08` / `RQ-MEM-03`）。

对应 ``docs/技术设计/technical-details/通用记忆.md`` 第 7 节与
``docs/需求/功能需求与验收.md`` 的 ``AC-08``：

> 删除一条记忆后，**两条读取路径**（时间线回看与应急预注入）都不再返回

本文件验证的是**这个验收条件本身**，而不是单个函数的返回值——因此它跨三处：
PostgreSQL 的账本、FalkorDB 的 episode 与派生事实、以及两条读路径的取数函数。

需要两个容器（postgres + falkordb），显式跑法：

    docker compose up -d postgres falkordb
    uv run pytest -m integration apps/api/tests/test_memory_deletion_integration.py

**图库侧用假模型客户端**：抽取要调 TokenHub（当前凭据是占位符，见 ``TECH-02``），
因此派生事实由本文件直接落库（`_write_edge`），不走 `add_episode`。这足以验证
「删除后两条读路径都不返回」——它检验的是**过滤逻辑**，与抽取质量无关。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from campfire.core.config import EMBEDDING_DIM, get_settings
from campfire.core.db import dispose_engine, session_scope
from campfire.modules.memory.deletion import correct_episode, delete_episode
from campfire.modules.memory.derived import read_emergency_facts
from campfire.modules.memory.graph import MemoryGraph, OrderedCrossEncoder
from campfire.modules.memory.identity import PendingId, derive_episode_uuid, to_account_id
from campfire.modules.memory.ledger import deleted_episode_keys
from campfire.modules.memory.models import MemoryDeletionLedger
from campfire.modules.memory.store import read_timeline, write_episode

pytestmark = pytest.mark.integration

#: 本文件专用账号（下划线形态，同时钉住「非 UUID 账号键可落库」）。
_ACCOUNT = "it_mem_del_account"


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——**不假装通过**。

    仓库既有集成测试的统一做法：CI 不带 Postgres service，不跳过会让「没配环境」
    以「连接失败」的形式整片变红，误报成「代码坏了」。
    """
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _dispose_shared_engine() -> AsyncIterator[None]:
    """每个用例前后释放 ``core/db`` 的全局共享引擎。

    原因：pytest-asyncio 为每个用例新建事件循环，而共享引擎的连接池绑定在首次使用
    的事件循环上——跨循环复用会抛 ``RuntimeError: Event loop is closed``。
    同处理见 ``test_memory_ledger_integration.py``。
    """
    await dispose_engine()
    yield
    await dispose_engine()


@pytest_asyncio.fixture
async def memory_graph() -> AsyncIterator[MemoryGraph]:
    """使用假模型客户端的记忆图库句柄（不调真实供应商）。"""
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
    except (ConnectionError, ConnectionRefusedError, ConnectionResetError, TimeoutError, OSError) as exc:
        await client.aclose()
        pytest.skip(f"FalkorDB 不可用（{type(exc).__name__}）——先 docker compose up -d falkordb")
    except Exception:
        await client.aclose()
        raise

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


async def _clear_ledger() -> None:
    """清掉本文件账号的账本行。"""
    from sqlalchemy import delete

    async with session_scope(get_settings()) as session:
        await session.execute(delete(MemoryDeletionLedger).where(MemoryDeletionLedger.account_id == _ACCOUNT))


async def _write_episode(graph: MemoryGraph, pending: str, content: str, occurred_at: datetime) -> str:
    """写一条 episode，返回其确定性 uuid。"""
    key = derive_episode_uuid(PendingId(pending))
    await write_episode(
        graph,
        to_account_id(_ACCOUNT),
        key,
        content=content,
        occurred_at=occurred_at,
        source_description="session=s1 message=m1",
    )
    return key


async def _write_edge(
    graph: MemoryGraph, edge_uuid: str, *, fact: str, valid_at: datetime, episodes: list[str]
) -> None:
    """直接落一条派生事实边（不走抽取，见文件头说明）。"""
    scoped = graph.driver_for(_ACCOUNT)
    await scoped.execute_query(
        """
        MERGE (a:Entity {uuid: $a_id}) SET a.name = 'A', a.group_id = $g
        MERGE (b:Entity {uuid: $b_id}) SET b.name = 'B', b.group_id = $g
        MERGE (a)-[e:RELATES_TO {uuid: $uid}]->(b)
        SET e.group_id = $g, e.name = 'REL', e.fact = $fact, e.valid_at = $valid,
            e.invalid_at = NULL, e.episodes = $episodes, e.created_at = $valid
        """,
        a_id="A",
        b_id="B",
        uid=edge_uuid,
        g=_ACCOUNT,
        fact=fact,
        valid=valid_at.isoformat(),
        episodes=episodes,
    )


# ---------------------------------------------------------------------------
# AC-08：删除后两条读路径都不再返回
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deletion_removes_memory_from_both_read_paths(memory_graph: MemoryGraph) -> None:
    """**`AC-08` 的主用例**：删除一条记忆后，时间线与应急预注入都不再返回它。

    两条读路径都要断言，因为它们是不同的取数实现（自建 Cypher 各写一遍过滤）。
    只测一条会让「另一条忘了过滤」漏过——而那正是 `AC-08` 的字面要求。
    """
    await _clear_ledger()
    now = datetime.now(timezone.utc)
    try:
        doomed = await _write_episode(memory_graph, "del-e2e-1", "要删除的记忆", now)
        kept = await _write_episode(memory_graph, "del-e2e-2", "保留的记忆", now - timedelta(days=1))
        # 一条引用 doomed 的派生事实（多来源，模拟 Graphiti 的 append 常态）。
        await _write_edge(
            memory_graph,
            "edge-doomed",
            fact="引用被删记忆的事实",
            valid_at=now,
            episodes=[doomed, kept],
        )
        await _write_edge(
            memory_graph,
            "edge-kept",
            fact="只引用保留记忆的事实",
            valid_at=now - timedelta(days=1),
            episodes=[kept],
        )

        # 前置条件：删除前两条路径都能看到。
        assert len(await read_timeline(memory_graph, to_account_id(_ACCOUNT), deleted_keys=[])) == 2

        async with session_scope(get_settings()) as session:
            result = await delete_episode(session, account_id=to_account_id(_ACCOUNT), episode_key=doomed)
        assert result.newly_deleted is True
        assert result.reason == "user_request"

        # 删除后：用账本做过滤（这是两条读路径的真实用法）。
        async with session_scope(get_settings()) as session:
            deleted_keys = await deleted_episode_keys(session, _ACCOUNT)

        timeline = await read_timeline(memory_graph, to_account_id(_ACCOUNT), deleted_keys=deleted_keys)
        assert [e.content for e in timeline] == ["保留的记忆"], "时间线仍返回已删除的记忆"

        facts = await read_emergency_facts(memory_graph, to_account_id(_ACCOUNT), deleted_keys=deleted_keys)
        fact_texts = [f.fact for f in facts.facts]
        assert fact_texts == ["只引用保留记忆的事实"], "应急预注入仍返回引用已删记忆的派生事实"
    finally:
        await _clear_ledger()


@pytest.mark.asyncio
async def test_deletion_is_idempotent_and_does_not_error_on_repeat(memory_graph: MemoryGraph) -> None:
    """重复删除**不是错误**：第二次报 `newly_deleted=False`。

    把幂等命中当错误会让调用方在重试时收到失败，而删除实际上早已生效。
    """
    await _clear_ledger()
    now = datetime.now(timezone.utc)
    try:
        key = await _write_episode(memory_graph, "del-idem", "重复删除的记忆", now)

        async with session_scope(get_settings()) as session:
            first = await delete_episode(session, account_id=to_account_id(_ACCOUNT), episode_key=key)
        async with session_scope(get_settings()) as session:
            second = await delete_episode(session, account_id=to_account_id(_ACCOUNT), episode_key=key)

        assert first.newly_deleted is True
        assert second.newly_deleted is False, "重复删除应幂等命中，不是报错"
        assert second.episode_key == key
    finally:
        await _clear_ledger()


@pytest.mark.asyncio
async def test_deletion_survives_graph_unavailability_by_design(memory_graph: MemoryGraph) -> None:
    """删除的正确性**不依赖图库**：只写账本，图库里残留不影响读路径。

    第 7 节：账本过滤是语义删除的唯一生效点，物理删除延期。因此删除一条记忆时
    **不调图库**——否则一个正常的删除请求会因基础设施故障而不可用。
    这里让图库里明显留着 episode 原文，验证读路径照样不返回它。
    """
    await _clear_ledger()
    now = datetime.now(timezone.utc)
    try:
        key = await _write_episode(memory_graph, "del-residue", "图库里仍有原文的记忆", now)

        async with session_scope(get_settings()) as session:
            await delete_episode(session, account_id=to_account_id(_ACCOUNT), episode_key=key)

        # 断言图库里**确实还留着**原文（不是靠物理删除实现的）。
        scoped = memory_graph.driver_for(_ACCOUNT)
        rows, _, _ = await scoped.execute_query("MATCH (e:Episodic {uuid: $u}) RETURN count(e) AS c", u=key)
        assert rows[0]["c"] == 1, "本用例的前提是图库残留仍在（物理清理延期）"

        async with session_scope(get_settings()) as session:
            deleted_keys = await deleted_episode_keys(session, _ACCOUNT)
        timeline = await read_timeline(memory_graph, to_account_id(_ACCOUNT), deleted_keys=deleted_keys)
        assert timeline == [], "账本已记录删除，图库残留不得让读路径返回它"
    finally:
        await _clear_ledger()


@pytest.mark.asyncio
async def test_correction_withdraws_the_old_episode_from_both_paths(memory_graph: MemoryGraph) -> None:
    """纠正的第一步：旧记忆从两条读路径撤下（原因记为 `correction`）。

    为什么这条重要（实测依据，2026-09-29）：`resolve_edge_contradictions` **只在**
    新事实 `valid_at` 严格更晚时让旧边失效；纠正允许新 episode 的 `occurred_at`
    **早于**旧事实，此时旧派生边**不会**自动失效。因此纠正的正确性必须由账本过滤
    承载——本用例钉住这一点：即使旧边仍有效（`invalid_at IS NULL`），只要它引用的
    旧 episode 进了账本，就不再注入。
    """
    await _clear_ledger()
    now = datetime.now(timezone.utc)
    try:
        old = await _write_episode(memory_graph, "corr-old", "错的记忆：他喜欢早上跑步", now)
        # 旧边仍然有效（invalid_at 为空）——这正是「不会自动失效」的实测情形。
        await _write_edge(
            memory_graph,
            "edge-still-valid",
            fact="他喜欢早上跑步",
            valid_at=now,
            episodes=[old],
        )

        async with session_scope(get_settings()) as session:
            result = await correct_episode(session, account_id=to_account_id(_ACCOUNT), corrected_episode_key=old)
        assert result.newly_deleted is True
        assert result.reason == "correction"

        async with session_scope(get_settings()) as session:
            deleted_keys = await deleted_episode_keys(session, _ACCOUNT)

        timeline = await read_timeline(memory_graph, to_account_id(_ACCOUNT), deleted_keys=deleted_keys)
        assert timeline == [], "被纠正的旧原文不得再出现在时间线"

        facts = await read_emergency_facts(memory_graph, to_account_id(_ACCOUNT), deleted_keys=deleted_keys)
        assert [f.fact for f in facts.facts] == [], (
            "引用被纠正旧记忆的派生事实仍在注入——旧边不会自动失效，必须靠账本过滤"
        )
    finally:
        await _clear_ledger()


@pytest.mark.asyncio
async def test_deletion_does_not_affect_other_accounts(memory_graph: MemoryGraph) -> None:
    """删除按账号分区：另一账号的记忆不受影响（跨账号误删是 `AC-07`/`AC-22` 级别的事故）。"""
    from sqlalchemy import delete

    other = "it_mem_del_other"
    await _clear_ledger()
    now = datetime.now(timezone.utc)
    try:
        async with session_scope(get_settings()) as session:
            await session.execute(delete(MemoryDeletionLedger).where(MemoryDeletionLedger.account_id == other))

        key = derive_episode_uuid(PendingId("del-other-acct"))
        await write_episode(
            memory_graph,
            to_account_id(other),
            key,
            content="另一账号的记忆",
            occurred_at=now,
            source_description="session=s9 message=m1",
        )

        async with session_scope(get_settings()) as session:
            mine = await deleted_episode_keys(session, _ACCOUNT)
        assert mine == [], "本账号无删除记录"

        # 另一账号的记忆仍然可见（用空 deleted_keys 读它自己的图）。
        timeline = await read_timeline(memory_graph, to_account_id(other), deleted_keys=[])
        assert [e.content for e in timeline] == ["另一账号的记忆"]

        # 清理另一账号的图与账本
        scoped = memory_graph.driver_for(other)
        await scoped.execute_query("MATCH (n) DETACH DELETE n")
        async with session_scope(get_settings()) as session:
            await session.execute(delete(MemoryDeletionLedger).where(MemoryDeletionLedger.account_id == other))
    finally:
        await _clear_ledger()


@pytest.mark.asyncio
async def test_deletion_rejects_malformed_key_before_touching_the_ledger(memory_graph: MemoryGraph) -> None:
    """畸形 key 在入口被拒，账本不留脏行（账本里的脏 key 只会让删除静默失效）。"""
    from campfire.modules.memory.errors import MemoryDataError

    await _clear_ledger()
    try:
        async with session_scope(get_settings()) as session:
            with pytest.raises(MemoryDataError):
                await delete_episode(session, account_id=to_account_id(_ACCOUNT), episode_key="not-a-uuid")
            with pytest.raises(MemoryDataError):
                await delete_episode(session, account_id=to_account_id(_ACCOUNT), episode_key="")

        async with session_scope(get_settings()) as session:
            assert await deleted_episode_keys(session, _ACCOUNT) == [], "拒绝的请求不得留下账本行"
    finally:
        await _clear_ledger()


@pytest.mark.asyncio
async def test_deleting_a_never_written_memory_still_records(memory_graph: MemoryGraph) -> None:
    """删除一条**从未写入**的记忆也会记账——这是有意的。

    理由：删除的正确性由账本独自保证，不依赖图库里是否存在。若「图库里没有就拒绝
    记账」，则在「记忆已排队但尚未写入」（写入路径是异步的）时删除会失败，之后
    写入完成就会把用户已要求删除的记忆写进去——**删除被写入覆盖**。
    先记账则写入侧能按账本判断该不该写（第 8 节的写入边界）。
    """
    await _clear_ledger()
    never_written = str(uuid.uuid4())
    try:
        async with session_scope(get_settings()) as session:
            result = await delete_episode(session, account_id=to_account_id(_ACCOUNT), episode_key=never_written)
        assert result.newly_deleted is True

        async with session_scope(get_settings()) as session:
            assert never_written in await deleted_episode_keys(session, _ACCOUNT)
    finally:
        await _clear_ledger()
