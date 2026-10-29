"""集成测试：删除与纠正的端到端效果（`AC-08` / `RQ-MEM-03`）。

对应 `docs/技术设计/technical-details/通用记忆.md` 第 7 节与
`docs/需求/功能需求与验收.md` 的 `AC-08`：

> 删除一条记忆后，两条读取路径（时间线回看与应急预注入）都不再返回

本文件验证的是这个验收条件本身，而不是单个函数的返回值——因此它跨三处：
PostgreSQL 的账本、FalkorDB 的 episode 与派生事实、以及两条读路径的取数函数。

需要两个容器（postgres + falkordb），显式跑法：

    docker compose up -d postgres falkordb
    uv run pytest -m integration apps/api/tests/test_memory_deletion_integration.py

图库侧用假模型客户端：抽取要调 TokenHub（当前凭据是占位符，见 `TECH-02`），
因此派生事实由本文件直接落库（`_write_edge`），不走 `add_episode`。这足以验证
「删除后两条读路径都不返回」——它检验的是过滤逻辑，与抽取质量无关。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from campfire.core.config import EMBEDDING_DIM, get_settings
from campfire.core.db import session_scope
from campfire.modules.memory.deletion import correct_episode, delete_episode
from campfire.modules.memory.derived import read_emergency_facts
from campfire.modules.memory.graph import MemoryGraph, OrderedCrossEncoder
from campfire.modules.memory.identity import PendingId, derive_episode_uuid, to_account_id, to_episode_key
from campfire.modules.memory.ledger import deleted_episode_keys
from campfire.modules.memory.models import MemoryDeletionLedger
from campfire.modules.memory.store import read_timeline, write_episode

from .conftest import connect_falkordb_or_skip

pytestmark = pytest.mark.integration

#: 本文件专用账号（下划线形态，同时钉住「非 UUID 账号键可落库」）。
_ACCOUNT = "it_mem_del_account"


async def _read_timeline(graph, account, **kwargs):  # noqa: ANN001, ANN003, ANN201
    """调公开读入口（自动开会话取删除账本）。

    2026-09-30 起读入口只收 `session`——「已删清单」由函数内部取，调用方无法漏传或
    传空（此前传空列表会静默返回已删记忆）。本助手只替测试开会话，不绕过过滤。
    """
    async with session_scope(get_settings()) as session:
        return await read_timeline(session, graph, to_account_id(account), **kwargs)


async def _read_emergency_facts(graph, account, **kwargs):  # noqa: ANN001, ANN003, ANN201
    """调公开应急读入口（同上）。"""
    async with session_scope(get_settings()) as session:
        return await read_emergency_facts(session, graph, to_account_id(account), **kwargs)


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——不假装通过。

    仓库既有集成测试的统一做法：CI 不带 Postgres service，不跳过会让「没配环境」
    以「连接失败」的形式整片变红，误报成「代码坏了」。
    """
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

    # 连容器：`FalkorDB(...)` 构造函数本身发网络 I/O，且它抛的是
    # `redis.exceptions.ConnectionError`（不是内建类型）——两者都由
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
        # 清图用 GRAPH.DELETE（FalkorDB v4.20.7 对「清空后重写 + 字符串范围查询」
        # 返回过期结果，见 conftest.drop_falkordb_graph 的说明）。
        # 删图之前先收口缓存驱动的后台索引任务（`release_account_driver`）：
        # 顺序反了会让在途的 `CREATE INDEX` 撞上「图键已删」——实测报
        # `Encountered an empty key when opened key <图名>`，异常无人取回时在退出时
        # 打印 `Task exception was never retrieved`（QA-10），最坏把 FalkorDB 打崩。
        from .conftest import drop_falkordb_graph

        for account_id in list(graph.account_drivers):
            await graph.release_account_driver(account_id)
        await drop_falkordb_graph(graph.driver, _ACCOUNT)
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
    """`AC-08` 的主用例：删除一条记忆后，时间线与应急预注入都不再返回它。

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
        assert len(await _read_timeline(memory_graph, _ACCOUNT)) == 2

        async with session_scope(get_settings()) as session:
            result = await delete_episode(session, account_id=to_account_id(_ACCOUNT), episode_key=doomed)
        assert result.newly_deleted is True
        assert result.reason == "user_request"

        # 删除后：读路径自己取账本过滤（这是两条读路径的真实用法）。
        # 这里额外断言账本真的记了——否则「读路径返回空」可能因为别的原因，
        # 用例会变成假阳性（2026-09-30 改造：此前是手动取 keys 再传给读函数，
        # 现在读函数自己取，因此把「账本有这一行」改成显式断言）。
        async with session_scope(get_settings()) as session:
            deleted_keys = await deleted_episode_keys(session, _ACCOUNT)
        assert deleted_keys, "删除后账本应有记录（否则下面的断言不成立）"

        timeline = await _read_timeline(memory_graph, _ACCOUNT)
        assert [e.content for e in timeline] == ["保留的记忆"], "时间线仍返回已删除的记忆"

        facts = await _read_emergency_facts(memory_graph, _ACCOUNT)
        fact_texts = [f.fact for f in facts.facts]
        assert fact_texts == ["只引用保留记忆的事实"], "应急预注入仍返回引用已删记忆的派生事实"
    finally:
        await _clear_ledger()


@pytest.mark.asyncio
async def test_deletion_is_idempotent_and_does_not_error_on_repeat(memory_graph: MemoryGraph) -> None:
    """重复删除不是错误：第二次报 `newly_deleted=False`。

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
    """删除的正确性不依赖图库：只写账本，图库里残留不影响读路径。

    第 7 节：账本过滤是语义删除的唯一生效点，物理删除延期。因此删除一条记忆时
    不调图库——否则一个正常的删除请求会因基础设施故障而不可用。
    这里让图库里明显留着 episode 原文，验证读路径照样不返回它。
    """
    await _clear_ledger()
    now = datetime.now(timezone.utc)
    try:
        key = await _write_episode(memory_graph, "del-residue", "图库里仍有原文的记忆", now)

        async with session_scope(get_settings()) as session:
            await delete_episode(session, account_id=to_account_id(_ACCOUNT), episode_key=key)

        # 断言图库里确实还留着原文（不是靠物理删除实现的）。
        scoped = memory_graph.driver_for(_ACCOUNT)
        rows, _, _ = await scoped.execute_query("MATCH (e:Episodic {uuid: $u}) RETURN count(e) AS c", u=key)
        assert rows[0]["c"] == 1, "本用例的前提是图库残留仍在（物理清理延期）"

        async with session_scope(get_settings()) as session:
            deleted_keys = await deleted_episode_keys(session, _ACCOUNT)
        assert deleted_keys, "账本应有记录（否则下面的断言不成立）"
        timeline = await _read_timeline(memory_graph, _ACCOUNT)
        assert timeline == [], "账本已记录删除，图库残留不得让读路径返回它"
    finally:
        await _clear_ledger()


@pytest.mark.asyncio
async def test_correction_withdraws_the_old_episode_from_both_paths(memory_graph: MemoryGraph) -> None:
    """纠正的第一步：旧记忆从两条读路径撤下（原因记为 `correction`）。

    为什么这条重要（实测依据，2026-09-29）：`resolve_edge_contradictions` 只在
    新事实 `valid_at` 严格更晚时让旧边失效；纠正允许新 episode 的 `occurred_at`
    早于旧事实，此时旧派生边不会自动失效。因此纠正的正确性必须由账本过滤
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
        assert deleted_keys, "纠正后账本应有记录（否则下面的断言不成立）"

        timeline = await _read_timeline(memory_graph, _ACCOUNT)
        assert timeline == [], "被纠正的旧原文不得再出现在时间线"

        facts = await _read_emergency_facts(memory_graph, _ACCOUNT)
        assert [f.fact for f in facts.facts] == [], (
            "引用被纠正旧记忆的派生事实仍在注入——旧边不会自动失效，必须靠账本过滤"
        )
    finally:
        await _clear_ledger()


@pytest.mark.asyncio
async def test_deletion_is_isolated_between_accounts(memory_graph: MemoryGraph) -> None:
    """跨账号隔离：删 A 的记忆，B 的记忆仍在两条读路径上可见。

    为什么重写这条（2026-09-29 评审发现它此前是空转测试）：原实现名为
    「删除不影响其它账号」，但函数体从不调用任何删除 API——只有写 episode、
    读时间线、断言账本为空。消融验证：把 `delete_episode`/`correct_episode` 换成
    no-op 后，本文件 7 条中 6 条失败，只有它仍然通过，即其断言在该名下永远不会
    失败（AGENTS.md 明令禁止）。现在它真的执行删除，并断言另一账号不受影响。

    跨账号误删是 `AC-07`/`AC-22` 级别的事故，因此这条必须真的覆盖删除动作。
    """
    from sqlalchemy import delete

    other = "it_mem_del_other"
    await _clear_ledger()
    now = datetime.now(timezone.utc)
    try:
        async with session_scope(get_settings()) as session:
            await session.execute(delete(MemoryDeletionLedger).where(MemoryDeletionLedger.account_id == other))
        # 开测前先删另一账号的图（GRAPH.DELETE）：本用例会往里写数据，若上次运行在断言处失败，
        # 收尾的清理不会执行，残留会让下一次运行看到多条内容而假失败
        # （实测踩过：连续 3 次消融运行后该账号积了 3 条）。清理放在 try 内、
        # 写入之前，使用例可重复运行。用删图键而不是清节点，理由见
        # conftest.drop_falkordb_graph（「清空后重写」会让范围查询返回过期结果）。
        from .conftest import drop_falkordb_graph

        # 删图前先收口该账号的克隆驱动：它的后台建索引任务还在跑时删图会撞上
        # 「图键已删」（`Encountered an empty key`，QA-10 的竞态）。
        await memory_graph.release_account_driver(other)
        await drop_falkordb_graph(memory_graph.driver, other)

        # 两个账号各写一条记忆（各自图里）。
        mine_key = await _write_episode(memory_graph, "iso-mine", "我的记忆", now)
        # 另一账号的 key 用 `to_episode_key` 收窄：`write_episode` 的入参是
        # `EpisodeUuid`（uuid 文本的语义类型），裸 `str(uuid.uuid4())` 只是「恰好
        # 长得像」，走校验入口才把「这是合法 episode 标识」变成已证事实。
        other_key = to_episode_key(str(uuid.uuid4()))
        await write_episode(
            memory_graph,
            to_account_id(other),
            other_key,
            content="另一账号的记忆",
            occurred_at=now,
            source_description="session=s9 message=m1",
        )

        # 真的删除本账号的那条（这是原实现缺的一步）。
        async with session_scope(get_settings()) as session:
            result = await delete_episode(session, account_id=to_account_id(_ACCOUNT), episode_key=mine_key)
        assert result.newly_deleted is True

        async with session_scope(get_settings()) as session:
            my_deleted = await deleted_episode_keys(session, _ACCOUNT)
            other_deleted = await deleted_episode_keys(session, other)
        assert my_deleted == [mine_key], "账本只应记本账号的删除"
        assert other_deleted == [], "本次删除不得在另一账号的账本里留下记录"

        # 本账号：删掉的不再返回。
        timeline = await _read_timeline(memory_graph, _ACCOUNT)
        assert timeline == [], "本账号已删的记忆不得返回"

        # 另一账号：不受影响（用它自己的账本读它自己的图）。
        other_timeline = await _read_timeline(memory_graph, other)
        assert [e.content for e in other_timeline] == ["另一账号的记忆"], "删本账号的记忆不得影响另一账号"

        # 清理另一账号的图与账本
        from .conftest import drop_falkordb_graph

        # 删图前先收口该账号的克隆驱动：它的后台建索引任务还在跑时删图会撞上
        # 「图键已删」（`Encountered an empty key`，QA-10 的竞态）。
        await memory_graph.release_account_driver(other)
        await drop_falkordb_graph(memory_graph.driver, other)
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
    """删除一条从未写入的记忆也会记账——这是有意的。

    理由：删除的正确性由账本独自保证，不依赖图库里是否存在。若「图库里没有就拒绝
    记账」，则在「记忆已排队但尚未写入」（写入路径是异步的）时删除会失败，之后
    写入完成就会把用户已要求删除的记忆写进去——删除被写入覆盖。
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
