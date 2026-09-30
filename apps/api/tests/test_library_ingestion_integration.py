"""摄取流水线的集成测试（真实 PostgreSQL，模拟嵌入）。

**为什么模拟嵌入**：`TOKENHUB_API_KEY` 在开发环境未配置，真实嵌入调用跑不了。
本文件因此**只验证嵌入之外的整条链**：分块 → 条目表与节点表**同事务**落库 →
幂等 → 节点可被向量存储读回。真实嵌入调用属未验证项，明确登记在交付说明里。

对应 RAG 策略第 7 节的纪律：一份文件一个事务、幂等、不留「一半进去了」的状态。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from llama_index.core.vector_stores.types import MetadataFilter, MetadataFilters, VectorStoreQuery
from sqlalchemy import func, select

from campfire.core.config import get_settings
from campfire.core.db import create_engine, create_sync_engine, session_scope
from campfire.modules.library.embedding import EMBEDDING_DIM
from campfire.modules.library.ingestion import IngestionError, build_vector_store, ingest_file
from campfire.modules.library.models import KnowledgeItem, RetrievedNode

pytestmark = pytest.mark.integration


#: 确定性假向量：同一文本必得同一向量，便于断言；不调用嵌入服务。
def _fake_vector(text: str) -> list[float]:
    seed = sum(ord(ch) for ch in text) % 97
    return [0.001 * ((i + seed) % 97 + 1) for i in range(EMBEDDING_DIM)]


class _FakeEmbedder:
    """替身嵌入器：只暴露流水线用到的那一个方法，形状与框架一致。"""

    async def aget_text_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        return [_fake_vector(t) for t in texts]


@pytest.fixture
def _patched_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 build_embedding 换成替身——流水线其余部分（含事务）保持真实。"""
    monkeypatch.setattr(
        "campfire.modules.library.ingestion.build_embedding",
        lambda _settings: _FakeEmbedder(),
    )


def _require_db() -> str:
    url = get_settings().database_url
    if not url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    return url


async def _cleanup(source_path: str) -> None:
    """清掉测试写入的条目与其节点，保持库干净（表结构保留）。"""
    async with session_scope(get_settings()) as session:
        items = (
            (await session.execute(select(KnowledgeItem).where(KnowledgeItem.source_path == source_path)))
            .scalars()
            .all()
        )
        for item in items:
            await session.execute(RetrievedNode.__table__.delete().where(RetrievedNode.node_id.like(f"{item.id}:%")))
            await session.delete(item)


@pytest.mark.asyncio
async def test_ingest_writes_item_and_nodes_in_one_transaction(tmp_path: Path, _patched_embedding: None) -> None:
    """一份文件：条目表与节点表都被写入，且节点可被向量存储读回。"""
    _require_db()
    doc = tmp_path / "guide.md"
    doc.write_text(
        "# 干预总则\n\n孤独症儿童的干预需要结构化环境。\n\n## 视觉支持\n\n使用图片日程表可以减少不确定性。\n",
        encoding="utf-8",
    )
    settings = get_settings()
    source_path = str(doc)

    try:
        sync_engine = create_sync_engine(settings)
        async_engine = create_engine(settings)
        store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

        async with session_scope(settings) as session:
            result = await ingest_file(
                settings,
                session,
                vector_store=store,
                path=doc,
                source="集成测试出处",
                applicable_scope="学龄前儿童",
                keywords="孤独症 autism",
                aliases="自闭症",
            )

        assert result.skipped is False
        assert result.chunks_written >= 1

        # 条目表已落库，且带来源与适用范围（不变量：缺这两项不进入检索）。
        async with session_scope(settings) as session:
            item = (
                await session.execute(select(KnowledgeItem).where(KnowledgeItem.source_path == source_path))
            ).scalar_one()
            assert item.source == "集成测试出处"
            assert item.applicable_scope == "学龄前儿童"
            assert item.withdrawn is False

        # 节点可被向量存储读回，且 metadata 带过滤维度。
        # 按 item_id 过滤以隔离本用例的数据——库中可能有其他测试留下的节点，
        # 只靠 top_k 取最近邻会取到别人的节点（本用例初版正是因此假失败）。
        query = VectorStoreQuery(
            query_embedding=_fake_vector("孤独症儿童的干预"),
            similarity_top_k=10,
            filters=MetadataFilters(
                filters=[
                    MetadataFilter(key="item_id", value=result.item_id),
                    MetadataFilter(key="withdrawn", value="false"),
                ]
            ),
        )
        hits = (await store.aquery(query)).nodes or []
        assert hits, "向量存储应能读回刚写入的节点"
        assert all(h.metadata.get("library") == "knowledge" for h in hits)
        assert all(h.metadata.get("item_id") == result.item_id for h in hits)
        assert any("干预" in h.text for h in hits), f"节点文本应含原文内容：{[h.text for h in hits]}"

        await async_engine.dispose()
        sync_engine.dispose()
    finally:
        await _cleanup(source_path)


@pytest.mark.asyncio
async def test_ingest_is_idempotent_for_unchanged_file(tmp_path: Path, _patched_embedding: None) -> None:
    """内容未变时跳过，且不产生重复条目（幂等）。"""
    _require_db()
    doc = tmp_path / "same.md"
    doc.write_text("# 标题\n\n内容不变。\n", encoding="utf-8")
    settings = get_settings()
    source_path = str(doc)

    try:
        sync_engine = create_sync_engine(settings)
        async_engine = create_engine(settings)
        store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

        async with session_scope(settings) as session:
            first = await ingest_file(
                settings, session, vector_store=store, path=doc, source="出处", applicable_scope="范围"
            )
        async with session_scope(settings) as session:
            second = await ingest_file(
                settings, session, vector_store=store, path=doc, source="出处", applicable_scope="范围"
            )

        assert first.skipped is False
        assert second.skipped is True, "内容未变的文件应被跳过"

        async with session_scope(settings) as session:
            count = (
                await session.execute(
                    select(func.count()).select_from(KnowledgeItem).where(KnowledgeItem.source_path == source_path)
                )
            ).scalar_one()
        assert count == 1, "幂等失败：产生了重复条目"

        await async_engine.dispose()
        sync_engine.dispose()
    finally:
        await _cleanup(source_path)


@pytest.mark.asyncio
async def test_frontmatter_supplies_item_metadata_and_stays_out_of_nodes(
    tmp_path: Path, _patched_embedding: None
) -> None:
    """文件 frontmatter 提供条目元数据，**不进入节点正文**。

    这是与语料加工件的接口：出处与适用范围写在文件里比命令行参数更不易错配，
    但 YAML 若被当作正文嵌入，就会污染检索内容（本用例的第二个断言）。
    """
    _require_db()
    doc = tmp_path / "corpus.md"
    doc.write_text(
        "---\n"
        "title: 加工件标题\n"
        "source: 国家卫健委公报 2022 年第 8 期\n"
        "applicable_scope: 0～6岁儿童\n"
        "keywords: 孤独症 筛查\n"
        "---\n"
        "\n"
        "# 正文根标题\n\n这是可检索的正文内容。\n",
        encoding="utf-8",
    )
    settings = get_settings()
    source_path = str(doc)

    try:
        sync_engine = create_sync_engine(settings)
        async_engine = create_engine(settings)
        store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

        async with session_scope(settings) as session:
            await ingest_file(settings, session, vector_store=store, path=doc)

        async with session_scope(settings) as session:
            item = (
                await session.execute(select(KnowledgeItem).where(KnowledgeItem.source_path == source_path))
            ).scalar_one()
            assert item.title == "加工件标题"
            assert item.source == "国家卫健委公报 2022 年第 8 期"
            assert item.applicable_scope == "0～6岁儿童"
            assert item.keywords == "孤独症 筛查"

            texts = (
                (await session.execute(select(RetrievedNode.text).where(RetrievedNode.node_id.like(f"{item.id}:%"))))
                .scalars()
                .all()
            )

        assert texts, "应有节点写入"
        assert all("applicable_scope:" not in t for t in texts), "frontmatter 不得进入节点正文"
        assert any("可检索的正文内容" in t for t in texts)

        await async_engine.dispose()
        sync_engine.dispose()
    finally:
        await _cleanup(source_path)


@pytest.mark.asyncio
async def test_ingest_rejects_file_without_source_or_scope(tmp_path: Path, _patched_embedding: None) -> None:
    """缺来源或适用范围的文件**拒绝入库**（不变量：缺来源不进入检索）。

    这是 `RQ-KB-02` 与 `RQ-CON-03` 在入口处的闸门——校验必须在写库之前发生，
    否则「先入库再发现缺字段」就要靠清理补救。
    """
    _require_db()
    doc = tmp_path / "no-source.md"
    doc.write_text("# 标题\n\n这段内容缺少来源与适用范围。\n", encoding="utf-8")
    settings = get_settings()

    sync_engine = create_sync_engine(settings)
    async_engine = create_engine(settings)
    store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

    try:
        with pytest.raises(IngestionError, match="source"):
            async with session_scope(settings) as session:
                await ingest_file(settings, session, vector_store=store, path=doc)

        # 未写入任何条目。
        async with session_scope(settings) as session:
            count = (
                await session.execute(
                    select(func.count()).select_from(KnowledgeItem).where(KnowledgeItem.source_path == str(doc))
                )
            ).scalar_one()
        assert count == 0
    finally:
        await _cleanup(str(doc))
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_failure_after_item_write_rolls_back_the_item_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**写条目之后**节点写入失败，条目也必须回滚。

    与下一个用例的区别（这里补的是一个验证缺口）：那个用例的失败发生在嵌入
    阶段，即在任何写入之前——它只能证明「失败时没有写入」。真正要守的不变量是
    「不留一半进去了的状态」：条目已 flush 进事务、节点写入才失败时，条目同样
    不能留下。本用例在 ``_write_nodes`` 处注入故障来覆盖该路径。
    """
    _require_db()
    doc = tmp_path / "partial.md"
    doc.write_text("# 标题\n\n条目会先写入，随后节点写入失败。\n", encoding="utf-8")
    settings = get_settings()
    source_path = str(doc)

    async def _boom_write_nodes(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("模拟节点写入故障")

    monkeypatch.setattr(
        "campfire.modules.library.ingestion.build_embedding",
        lambda _settings: _FakeEmbedder(),
    )
    monkeypatch.setattr("campfire.modules.library.ingestion._write_nodes", _boom_write_nodes)

    sync_engine = create_sync_engine(settings)
    async_engine = create_engine(settings)
    store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

    try:
        with pytest.raises(RuntimeError):
            async with session_scope(settings) as session:
                await ingest_file(
                    settings, session, vector_store=store, path=doc, source="出处", applicable_scope="范围"
                )

        async with session_scope(settings) as session:
            count = (
                await session.execute(
                    select(func.count()).select_from(KnowledgeItem).where(KnowledgeItem.source_path == source_path)
                )
            ).scalar_one()
        assert count == 0, "节点写入失败后条目仍在——留下了一半的状态"
    finally:
        await _cleanup(source_path)
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_ingest_failure_rolls_back_everything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """嵌入失败时整份回滚：**不留「一半进去了」的状态**（RAG 策略第 7 节）。"""
    _require_db()
    doc = tmp_path / "boom.md"
    doc.write_text("# 标题\n\n这份文件的嵌入会失败。\n", encoding="utf-8")
    settings = get_settings()
    source_path = str(doc)

    class _BoomEmbedder:
        async def aget_text_embedding_batch(self, _texts: list[str]) -> list[list[float]]:
            raise RuntimeError("模拟嵌入服务故障")

    monkeypatch.setattr(
        "campfire.modules.library.ingestion.build_embedding",
        lambda _settings: _BoomEmbedder(),
    )

    sync_engine = create_sync_engine(settings)
    async_engine = create_engine(settings)
    store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

    try:
        from campfire.modules.library.ingestion import IngestionError

        with pytest.raises(IngestionError):
            async with session_scope(settings) as session:
                await ingest_file(
                    settings, session, vector_store=store, path=doc, source="出处", applicable_scope="范围"
                )

        # 回滚后条目表与节点表都不应留下这行。
        async with session_scope(settings) as session:
            count = (
                await session.execute(
                    select(func.count()).select_from(KnowledgeItem).where(KnowledgeItem.source_path == source_path)
                )
            ).scalar_one()
        assert count == 0, "失败后条目仍存在——事务未回滚"
    finally:
        await _cleanup(source_path)
        await async_engine.dispose()
        sync_engine.dispose()
