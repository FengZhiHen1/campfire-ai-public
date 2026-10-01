"""集成测试：迁移建出的表与 LlamaIndex 框架的实际协作。

对应 docs/技术设计/technical-details/RAG策略.md 第 2 节与 TODO `TECH-19` 的已实测
结论。这些事实**只能在真实 PostgreSQL 上验证**，因此带 `integration` marker，
默认不在 `uv run pytest` 中运行（见根 pyproject.toml 的 addopts），
显式跑法：``uv run pytest -m integration``，需先 ``docker compose up -d postgres``。

锁住的是三条「迁移与框架之间没有书面契约」的约定——任一条失效都会让摄取或检索
在运行期静默出问题，而不是在测试里失败：

1. **表名约定**：框架把 `table_name` 渲染成 `data_<table_name>`；迁移必须建出同名表。
2. **结构约定**：`id bigint` + sequence 自增、`text`/`metadata_`/`node_id`/`embedding`
   的列名与类型必须与框架期望一致，否则写入报错或读空。
3. **过滤语义**：metadata 过滤真的下推到 SQL；且 `withdrawn` 这类布尔语义**必须以
   字符串存**——`MetadataFilter.value` 的类型联合不含 `bool`（实测传 `False` 被
   pydantic 严格模式拒绝）。
"""

from __future__ import annotations

import pytest
from llama_index.core.schema import TextNode
from llama_index.core.vector_stores.types import MetadataFilter, MetadataFilters, VectorStoreQuery
from llama_index.vector_stores.postgres import PGVectorStore
from pydantic import ValidationError
from sqlalchemy import text

from campfire.core.config import get_settings
from campfire.core.db import create_engine
from campfire.modules.library.models import EMBEDDING_DIM

pytestmark = pytest.mark.integration

#: 假向量：不调用嵌入服务，因此本测试不依赖 TOKENHUB_API_KEY。
_FAKE_VECTOR = [0.001 * ((i % 97) + 1) for i in range(EMBEDDING_DIM)]


def _async_dsn() -> str:
    """从配置取异步连接串；未配置则跳过（不假装通过）。"""
    url = get_settings().database_url
    if not url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    return url


def _sync_dsn() -> str:
    """框架需要同步连接串（它无条件同时建同步与异步引擎）。"""
    return _async_dsn().replace("postgresql+asyncpg://", "postgresql://")


def _store() -> PGVectorStore:
    return PGVectorStore.from_params(
        connection_string=_sync_dsn(),
        async_connection_string=_async_dsn(),
        table_name="campfire_node",
        embed_dim=EMBEDDING_DIM,
        perform_setup=False,  # DDL 归 Alembic 迁移所有
        use_jsonb=True,
    )


async def _table_exists(table: str) -> bool:
    engine = create_engine(get_settings())
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT to_regclass(:qualified) IS NOT NULL"),
                {"qualified": f"public.{table}"},
            )
            return bool(result.scalar())
    except Exception as exc:  # noqa: BLE001 —— 连不上库时跳过而不是假失败
        pytest.skip(f"数据库不可用（{type(exc).__name__}）——先 docker compose up -d postgres")
    finally:
        await engine.dispose()


async def _cleanup_nodes(node_ids: list[str]) -> None:
    """按 node_id 清理本文件写入的节点。

    注意：**框架只会删除一条匹配的行**，而 `node_id` 上没有唯一约束（框架自己
    也不建，加了会让重复写入由「覆盖」变「报错」），因此重复跑测试会累积多行。
    这里直接按 id 全删，保证跑完不留残留。
    """
    engine = create_engine(get_settings())
    try:
        async with engine.begin() as connection:
            for node_id in node_ids:
                await connection.execute(
                    text("DELETE FROM data_campfire_node WHERE node_id = :nid"),
                    {"nid": node_id},
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_created_the_tables_the_framework_expects() -> None:
    """迁移已建出两张表，且节点表名符合框架的 `data_` 前缀约定。"""
    assert await _table_exists("campfire_knowledge_item"), "条目表缺失——先跑 alembic upgrade head"
    assert await _table_exists("data_campfire_node"), (
        "节点表缺失或命名不符：框架会把 table_name 渲染成 data_<table_name>"
    )


@pytest.mark.asyncio
async def test_pgvector_store_can_write_and_query_migration_table() -> None:
    """写入 + 异步查询打通：列名、类型与 id sequence 都与框架一致。

    这是「迁移结构 = 框架期望」最强的可执行证据：`id` 缺 sequence 时写入会直接
    报 NotNullViolation，而不是悄悄失败。
    """
    store = _store()
    node = TextNode(
        text="集成测试节点",
        id_="it-migration-1",
        embedding=_FAKE_VECTOR,
        metadata={"item_id": "item-int-1", "library": "knowledge", "withdrawn": "false"},
    )

    try:
        store.add([node])
        result = await store.aquery(VectorStoreQuery(query_embedding=_FAKE_VECTOR, similarity_top_k=5))
        texts = [n.text for n in (result.nodes or [])]
        assert "集成测试节点" in texts
    finally:
        await _cleanup_nodes(["it-migration-1"])


@pytest.mark.asyncio
async def test_metadata_filter_is_applied_and_booleans_are_rejected() -> None:
    """过滤在 SQL 内生效；`withdrawn` 必须用字符串取值。

    布尔无法作为 `MetadataFilter.value`（框架的类型联合不含 bool），因此节点
    metadata 的撤下标记以 `"true"`/`"false"` 存储——本用例同时锁住这个表示法。
    """
    store = _store()
    active = TextNode(
        text="未撤下",
        id_="it-filter-a",
        embedding=_FAKE_VECTOR,
        metadata={"item_id": "item-int-A", "library": "knowledge", "withdrawn": "false"},
    )
    withdrawn = TextNode(
        text="已撤下",
        id_="it-filter-b",
        embedding=_FAKE_VECTOR,
        metadata={"item_id": "item-int-B", "library": "knowledge", "withdrawn": "true"},
    )

    try:
        store.add([active, withdrawn])

        kept = await store.aquery(
            VectorStoreQuery(
                query_embedding=_FAKE_VECTOR,
                similarity_top_k=10,
                filters=MetadataFilters(filters=[MetadataFilter(key="withdrawn", value="false")]),
            )
        )
        kept_ids = {n.metadata.get("item_id") for n in (kept.nodes or [])}
        assert "item-int-A" in kept_ids
        assert "item-int-B" not in kept_ids, "已撤下的节点不应出现在 withdrawn='false' 的结果里"

        # 布尔值必须被拒绝——若某天框架接受 bool，本断言会失败，那时可放宽。
        with pytest.raises(ValidationError):
            MetadataFilters(filters=[MetadataFilter(key="withdrawn", value=False)])
    finally:
        await _cleanup_nodes(["it-filter-a", "it-filter-b"])
