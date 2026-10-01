"""摄取流水线的集成测试（真实 PostgreSQL，模拟嵌入）。

为什么模拟嵌入：`TOKENHUB_API_KEY` 在开发环境未配置，真实嵌入调用跑不了。
本文件因此只验证嵌入之外的整条链：分块 → 条目表与节点表同事务落库 →
幂等 → 节点可被向量存储读回。真实嵌入调用属未验证项，明确登记在交付说明里。

对应 RAG 策略第 7 节的纪律：一份文件一个事务、幂等、不留「一半进去了」的状态。
撤下的资料条目重新摄取时不得重建节点（`RQ-KB-04` / `D-16` 资料侧）见文末两个用例。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from llama_index.core.vector_stores.types import MetadataFilter, MetadataFilters, VectorStoreQuery
from sqlalchemy import func, select, text

from campfire.core.config import get_settings
from campfire.core.db import create_engine, create_sync_engine, session_scope
from campfire.modules.library.embedding import EMBEDDING_DIM
from campfire.modules.library.ingestion import IngestionError, build_vector_store, ingest_file
from campfire.modules.library.models import KnowledgeItem, RetrievedNode
from campfire.modules.library.retrieval import literal_search, search
from campfire.modules.library.withdrawal import withdraw_item

pytestmark = pytest.mark.integration


#: 确定性假向量：同一文本必得同一向量，便于断言；不调用嵌入服务。
def _fake_vector(text: str) -> list[float]:
    seed = sum(ord(ch) for ch in text) % 97
    return [0.001 * ((i + seed) % 97 + 1) for i in range(EMBEDDING_DIM)]


class _FakeEmbedder:
    """替身嵌入器：只暴露流水线用到的那一个方法，形状与框架一致。"""

    async def aget_text_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        return [_fake_vector(t) for t in texts]


class _CountingEmbedder(_FakeEmbedder):
    """替身嵌入器 + 调用计数：用于断言「已撤下条目不再付一次嵌入往返」。"""

    def __init__(self) -> None:
        self.calls = 0

    async def aget_text_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return await super().aget_text_embedding_batch(texts)


async def _fake_embed_query(query: str) -> list[float]:
    return _fake_vector(query)


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


async def _node_counts(item_id: str) -> tuple[int, int]:
    """某条目的 `(节点总数, 元数据声称 withdrawn='false' 的节点数)`。

    第二个数就是「节点元数据与条目表矛盾」的节点数：撤下后既不该留有节点，
    也不该有节点声称自己未撤下。
    """
    async with session_scope(get_settings()) as session:
        row = (
            await session.execute(
                text(
                    "select count(*) as total,"
                    " count(*) filter (where metadata_->>'withdrawn' = 'false') as claiming_active"
                    " from data_campfire_node where metadata_->>'item_id' = :i"
                ),
                {"i": item_id},
            )
        ).one()
    return int(row.total), int(row.claiming_active)


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
    """文件 frontmatter 提供条目元数据，不进入节点正文。

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
    """缺来源或适用范围的文件拒绝入库（不变量：缺来源不进入检索）。

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
    """写条目之后节点写入失败，条目也必须回滚。

    与下一个用例的区别（这里补的是一个验证缺口）：那个用例的失败发生在嵌入
    阶段，即在任何写入之前——它只能证明「失败时没有写入」。真正要守的不变量是
    「不留一半进去了的状态」：条目已 flush 进事务、节点写入才失败时，条目同样
    不能留下。本用例在 `_write_nodes` 处注入故障来覆盖该路径。
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
    """嵌入失败时整份回滚：不留「一半进去了」的状态（RAG 策略第 7 节）。"""
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


# ---------------------------------------------------------------------------
# 撤下后的重新摄取：不得重建节点（RQ-KB-04 / AC-09 的资料侧，D-16）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reingest_after_withdrawal_does_not_rebuild_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """撤下后重新摄取改过的文件：不重建节点、不再嵌入、两路查不到（D-16 资料侧）。

    资料侧与案例侧的差别必须说清（本用例的判别点）：资料侧节点 metadata 本就派生自
    条目状态（`_node_metadata`），撤下后重建的节点会自称 `withdrawn='true'`，向量路的
    `withdrawn` 过滤因此兜得住——内容不会复活，这与案例侧硬编码 `"false"` 时
    「撤下被推翻」的失效模式不同。真正被推翻的是「撤下后该条目没有节点」这条物理
    不变量：撤下的正文重新落回检索存储，取数是否读得到就只剩「每条路径都记得过滤
    `withdrawn`」这一层；而且为永远不会被检索的内容又付了一次嵌入往返（正文再次
    发给供应商）。

    对未修复实现：节点数断言是 `(1, 0)` 而非 `(0, 0)`，嵌入次数是 2 而非 1。
    """
    _require_db()
    embedder = _CountingEmbedder()
    monkeypatch.setattr("campfire.modules.library.ingestion.build_embedding", lambda _settings: embedder)

    doc = tmp_path / "withdraw-reingest.md"
    # 关键词 ≥3 连续汉字：字面路才可用（RAG 策略第 3.1 节），前置对照才有判别力。
    query = "撤下重摄取"
    doc.write_text("# 探针资料\n\n第一版正文：结构化环境与图片日程表。\n", encoding="utf-8")
    settings = get_settings()
    source_path = str(doc)

    sync_engine = create_sync_engine(settings)
    async_engine = create_engine(settings)
    store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

    try:
        async with session_scope(settings) as session:
            first = await ingest_file(
                settings,
                session,
                vector_store=store,
                path=doc,
                source="集成测试出处",
                applicable_scope="学龄前儿童",
                keywords=query,
            )
        total_before, _ = await _node_counts(first.item_id)
        assert total_before == first.chunks_written >= 1, "前置：应写入节点"
        assert embedder.calls == 1, "前置：首次摄取应嵌入一次"

        # 前置对照：撤下前两路都命中——否则文末的「查不到」是无判别力的空断言。
        async with session_scope(settings) as session:
            literal_before = await literal_search(session, query, library="knowledge")
        async with session_scope(settings) as session:
            fused_before = await search(session, store, query, library="knowledge", embed_query=_fake_embed_query)
        assert any(item_id == first.item_id for item_id, _rank in literal_before), "前置：撤下前字面路应命中"
        assert any(r.item_id == first.item_id for r in fused_before.items), "前置：撤下前检索路应命中"

        async with session_scope(settings) as session:
            withdrawal = await withdraw_item(session, library="knowledge", item_id=first.item_id, reason="集成测试撤下")
        assert withdrawal.nodes_deleted == total_before
        assert await _node_counts(first.item_id) == (0, 0), "前置：撤下应清空该条目的节点"

        # 改内容后重新摄取：上游修订后重新交付是正常运维路径。
        doc.write_text(f"# 探针资料（改过）\n\n第二版正文：含查询词 {query}，仍讲图片日程表。\n", encoding="utf-8")
        async with session_scope(settings) as session:
            second = await ingest_file(
                settings,
                session,
                vector_store=store,
                path=doc,
                source="集成测试出处",
                applicable_scope="学龄前儿童",
                keywords=query,
            )

        assert second.item_id == first.item_id, "同一 source_path 应复用同一条目，不该新建条目"
        assert second.skipped is False, "内容已变，不该被当作「未变」跳过"
        assert await _node_counts(first.item_id) == (0, 0), (
            "撤下后重新摄取重建了节点——「撤下即删节点」的承诺被推翻，撤下的正文也重新落回检索存储"
        )
        assert second.chunks_written == 0, "已撤下的条目不得写回节点：写入计数须如实报 0"
        assert second.headers == [], "没有写入节点就不该报告定位信息"
        assert embedder.calls == 1, "已撤下的条目不重建节点，也就不该再付一次嵌入往返（正文不得再次发给供应商）"

        # 条目表的撤下事实与审计字段仍在：摄取不得动摇撤下状态。
        async with session_scope(settings) as session:
            item = (
                await session.execute(select(KnowledgeItem).where(KnowledgeItem.id == uuid.UUID(first.item_id)))
            ).scalar_one()
            assert item.withdrawn is True, "重新摄取把条目恢复成在库——撤下被文件重新交付静默推翻"
            assert item.withdrawn_reason == "集成测试撤下"
            assert item.withdrawn_at is not None

        # 端到端：撤下的用户可见后果不因重新摄取而改变（两路都查不到）。
        async with session_scope(settings) as session:
            literal_after = await literal_search(session, query, library="knowledge")
        async with session_scope(settings) as session:
            fused_after = await search(session, store, query, library="knowledge", embed_query=_fake_embed_query)
        assert all(item_id != first.item_id for item_id, _rank in literal_after), "撤下后字面路仍命中该条目"
        assert all(r.item_id != first.item_id for r in fused_after.items), "撤下后检索路仍返回该条目"

        # 再摄取同一份改过的文件：走同一条「内容未变」幂等路径（撤下状态不破坏幂等）。
        async with session_scope(settings) as session:
            third = await ingest_file(
                settings,
                session,
                vector_store=store,
                path=doc,
                source="集成测试出处",
                applicable_scope="学龄前儿童",
                keywords=query,
            )
        assert third.skipped is True, "已撤下条目的重复摄取应被幂等跳过"
        assert embedder.calls == 1, "幂等跳过同样不该嵌入"
    finally:
        await _cleanup(source_path)
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_reingest_after_withdrawal_clears_residual_nodes(tmp_path: Path, _patched_embedding: None) -> None:
    """撤下后重新摄取顺带清掉残留节点（历史脏数据或旁路写入）。

    为什么单独一条：`ingest_file` 承诺「对已撤下条目同样先删旧节点、清残留」。
    正常撤下路径（`withdraw_item`）已经把节点删净，所以那条承诺只有在「撤下之后
    节点又出现」时才可判伪——本用例直接造出这个状态（模拟运维直连写库或历史脏数据），
    断言重摄取把它清掉。

    对未修复实现：重摄取会写回新节点，节点数为 1 而非 0。
    """
    _require_db()
    doc = tmp_path / "stray.md"
    doc.write_text("# 残留用例\n\n第一版正文。\n", encoding="utf-8")
    settings = get_settings()
    source_path = str(doc)

    sync_engine = create_sync_engine(settings)
    async_engine = create_engine(settings)
    store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

    try:
        async with session_scope(settings) as session:
            first = await ingest_file(
                settings, session, vector_store=store, path=doc, source="出处", applicable_scope="范围"
            )
        async with session_scope(settings) as session:
            await withdraw_item(session, library="knowledge", item_id=first.item_id, reason="集成测试撤下")
        assert await _node_counts(first.item_id) == (0, 0), "前置：撤下应清空节点"

        # 造出「撤下之后节点又出现」的状态：旁路写入一条声称未撤下的节点。
        async with session_scope(settings) as session:
            table = store._table_class  # noqa: SLF001 —— 与摄取写节点同一张框架表模型
            session.add(
                table(
                    node_id=f"{first.item_id}:stray",
                    text="旁路写入的残留正文",
                    embedding=_fake_vector("旁路写入的残留正文"),
                    metadata_={"item_id": first.item_id, "library": "knowledge", "withdrawn": "false"},
                )
            )
        assert await _node_counts(first.item_id) == (1, 1), "前置：应已注入一条声称未撤下的残留节点"

        doc.write_text("# 残留用例\n\n第二版正文（已改）。\n", encoding="utf-8")
        async with session_scope(settings) as session:
            second = await ingest_file(
                settings, session, vector_store=store, path=doc, source="出处", applicable_scope="范围"
            )

        assert second.skipped is False, "内容已变，不该被跳过"
        assert await _node_counts(first.item_id) == (0, 0), "撤下后重新摄取没有清掉残留节点（也没有拦住写回）"
    finally:
        await _cleanup(source_path)
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_reingest_unchanged_after_withdrawal_clears_residual_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """撤下后重新交付同一份文件（哈希不变）：幂等跳过也要清掉残留节点。

    为什么要与上一条分开：`test_reingest_after_withdrawal_clears_residual_nodes`
    走的是「改了内容再重摄取」分支（哈希变化，清理发生在写新节点之前）；而上游最常见的
    重交付形态正是同一份内容再送一次（哈希不变），这条路径此前在幂等早返回处就结束，
    清理一次都不执行。

    对未修复实现：`skipped` 为真，但残留节点仍在（节点数断言是 (1, 1) 而非 (0, 0)）。
    """
    _require_db()
    embedder = _CountingEmbedder()
    monkeypatch.setattr("campfire.modules.library.ingestion.build_embedding", lambda _settings: embedder)

    doc = tmp_path / "stray-unchanged.md"
    doc.write_text("# 残留用例（内容不变）\n\n第一版正文：结构化环境与图片日程表。\n", encoding="utf-8")
    settings = get_settings()
    source_path = str(doc)

    sync_engine = create_sync_engine(settings)
    async_engine = create_engine(settings)
    store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

    try:
        async with session_scope(settings) as session:
            first = await ingest_file(
                settings, session, vector_store=store, path=doc, source="出处", applicable_scope="范围"
            )
        assert embedder.calls == 1, "前置：首次摄取应嵌入一次"

        async with session_scope(settings) as session:
            await withdraw_item(session, library="knowledge", item_id=first.item_id, reason="集成测试撤下")
        assert await _node_counts(first.item_id) == (0, 0), "前置：撤下应清空节点"

        # 造出「撤下之后节点又出现」的状态：旁路写入一条声称未撤下的节点。
        async with session_scope(settings) as session:
            table = store._table_class  # noqa: SLF001 —— 与摄取写节点同一张框架表模型
            session.add(
                table(
                    node_id=f"{first.item_id}:stray",
                    text="旁路写入的残留正文",
                    embedding=_fake_vector("旁路写入的残留正文"),
                    metadata_={"item_id": first.item_id, "library": "knowledge", "withdrawn": "false"},
                )
            )
        assert await _node_counts(first.item_id) == (1, 1), "前置：应已注入一条声称未撤下的残留节点"

        # 文件一个字节都不改：这次走的是幂等「内容未变」分支。
        async with session_scope(settings) as session:
            second = await ingest_file(
                settings, session, vector_store=store, path=doc, source="出处", applicable_scope="范围"
            )

        assert second.skipped is True, "前置：内容未变应被幂等跳过"
        assert (second.chunks_written, second.headers) == (0, []), "跳过语义不变：不写节点、不报定位"
        assert embedder.calls == 1, "幂等跳过不得嵌入"
        assert await _node_counts(first.item_id) == (0, 0), (
            "哈希未变的重复摄取没有清掉已撤下条目的残留节点——「撤下后该条目没有节点」这条承诺在这条路径上不成立"
        )
    finally:
        await _cleanup(source_path)
        await async_engine.dispose()
        sync_engine.dispose()
