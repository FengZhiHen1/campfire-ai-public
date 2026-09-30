"""检索链的集成测试（真实 PostgreSQL）。

覆盖 RAG 策略第 3.1、4 节与资料与案例检索第 4、5 节在真实库上的行为：

- 字面路真的走 `ILIKE` 且命中中文标题/关键词（含 ≥3 连续汉字）；
- 1–2 字查询被闸门跳过字面路，仍能走向量路；
- 两路结果经 RRF 融合后聚合为条目；
- **撤下即刻不可检索**（查询时过滤，不依赖索引清理）；
- 两路都失败时抛 `RetrievalError`，**不返回空列表冒充「未找到」**。

嵌入用确定性替身（TOKENHUB_API_KEY 未配置），但 SQL、融合与聚合都是真实的。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from campfire.core.config import get_settings
from campfire.core.db import create_engine, create_sync_engine, session_scope
from campfire.modules.library.embedding import EMBEDDING_DIM
from campfire.modules.library.ingestion import build_vector_store, ingest_file
from campfire.modules.library.models import KnowledgeItem, RetrievedNode
from campfire.modules.library.retrieval import RetrievalError, literal_path_is_usable, search

pytestmark = pytest.mark.integration


def _fake_vector(text_value: str) -> list[float]:
    seed = sum(ord(ch) for ch in text_value) % 97
    return [0.001 * ((i + seed) % 97 + 1) for i in range(EMBEDDING_DIM)]


class _FakeEmbedder:
    async def aget_text_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        return [_fake_vector(t) for t in texts]


async def _fake_embed_query(query: str) -> list[float]:
    return _fake_vector(query)


def _require_db() -> str:
    url = get_settings().database_url
    if not url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    return url


async def _cleanup(paths: list[str]) -> None:
    async with session_scope(get_settings()) as session:
        for source_path in paths:
            items = (
                (await session.execute(select(KnowledgeItem).where(KnowledgeItem.source_path == source_path)))
                .scalars()
                .all()
            )
            for item in items:
                await session.execute(
                    RetrievedNode.__table__.delete().where(RetrievedNode.node_id.like(f"{item.id}:%"))
                )
                await session.delete(item)


@pytest.fixture
def _patched_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "campfire.modules.library.ingestion.build_embedding",
        lambda _settings: _FakeEmbedder(),
    )


async def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """灌入两份资料，返回它们的 source_path（供清理）。"""
    monkeypatch.setattr(
        "campfire.modules.library.ingestion.build_embedding",
        lambda _settings: _FakeEmbedder(),
    )
    settings = get_settings()
    doc_a = tmp_path / "a.md"
    doc_a.write_text("# 视觉支持\n\n使用图片日程表可以减少不确定性。\n", encoding="utf-8")
    doc_b = tmp_path / "b.md"
    doc_b.write_text("# 行为应对\n\n挑战性行为的功能分析步骤。\n", encoding="utf-8")

    sync_engine = create_sync_engine(settings)
    async_engine = create_engine(settings)
    store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

    async with session_scope(settings) as session:
        await ingest_file(
            settings,
            session,
            vector_store=store,
            path=doc_a,
            title="视觉支持策略",
            source="WHO 2024",
            applicable_scope="学龄前儿童",
            keywords="孤独症 autism",
            aliases="自闭症",
        )
    async with session_scope(settings) as session:
        await ingest_file(
            settings,
            session,
            vector_store=store,
            path=doc_b,
            title="行为应对指南",
            source="NICE 2023",
            applicable_scope="学龄期儿童",
            keywords="挑战性行为",
        )
    await async_engine.dispose()
    sync_engine.dispose()
    return [str(doc_a), str(doc_b)]


@pytest.mark.asyncio
async def test_literal_path_matches_chinese_keywords(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """字面路命中中文关键词，并经融合聚合为条目（≥3 连续汉字走字面路）。"""
    paths = await _seed(tmp_path, monkeypatch)
    settings = get_settings()
    try:
        sync_engine = create_sync_engine(settings)
        async_engine = create_engine(settings)
        store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

        async with session_scope(settings) as session:
            outcome = await search(session, store, "孤独症", embed_query=_fake_embed_query)
        results = outcome.items

        assert results, "应能检索到已入库的条目"
        titles = [r.title for r in results]
        assert "视觉支持策略" in titles
        # 返回契约字段完好。
        hit = next(r for r in results if r.title == "视觉支持策略")
        assert hit.source == "WHO 2024"
        assert hit.applicable_scope == "学龄前儿童"
        assert hit.status == "published"
        assert hit.library == "knowledge"

        await async_engine.dispose()
        sync_engine.dispose()
    finally:
        await _cleanup(paths)


@pytest.mark.asyncio
async def test_short_query_skips_literal_path_but_still_searches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1–2 字查询不走字面路，但检索仍可用（走向量路）——不得当成零结果。"""
    paths = await _seed(tmp_path, monkeypatch)
    settings = get_settings()
    try:
        assert literal_path_is_usable("干预") is False

        sync_engine = create_sync_engine(settings)
        async_engine = create_engine(settings)
        store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

        async with session_scope(settings) as session:
            outcome = await search(session, store, "干预", embed_query=_fake_embed_query)
        results = outcome.items

        assert results, "短查询应仍走向量路，而不是返回空"

        await async_engine.dispose()
        sync_engine.dispose()
    finally:
        await _cleanup(paths)


@pytest.mark.asyncio
async def test_both_paths_merge_when_text_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """两路命中同一份内容时，必须合并为一条并标 `both`。

    **已修复缺陷的回归测试**（2026-09-29）：框架 ``TextNode.hash`` 由「文本 +
    metadata」共同决定；字面路若只带文本构造节点，哈希与向量路不同，RRF 就永远
    判不出「两路都命中」——实测 23 个节点 text 全同、hash 全不同，`hit_paths`
    恒为 ``vector``，融合退化成只有向量路。
    """
    paths = await _seed(tmp_path, monkeypatch)
    settings = get_settings()
    try:
        sync_engine = create_sync_engine(settings)
        async_engine = create_engine(settings)
        store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

        # 「孤独症」既是关键词（字面路命中），也语义相关（向量路命中）。
        async with session_scope(settings) as session:
            outcome = await search(session, store, "孤独症", embed_query=_fake_embed_query)
        results = outcome.items

        assert results, "应有结果"
        hits = {r.ranking.get("hit_paths") for r in results}
        assert "both" in hits, f"两路应合并为 both，实际只有 {hits}——两路哈希未对齐"

        # 两路命中得分应高于单路（RRF 的 Σ1/(rank+k) 叠加）。
        both = next(r for r in results if r.ranking.get("hit_paths") == "both")
        only_vector = next((r for r in results if r.ranking.get("hit_paths") == "vector"), None)
        if only_vector is not None:
            assert float(both.ranking["fused_score"]) > float(only_vector.ranking["fused_score"])

        await async_engine.dispose()
        sync_engine.dispose()
    finally:
        await _cleanup(paths)


@pytest.mark.asyncio
async def test_locator_points_to_a_section_not_just_the_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`locator` 要能定位到章节，而不是整份文档（引用回指 `AC-05` 的前提）。

    框架的 `header_path` 只有父级路径，直接拿它当 locator 会让同章所有块指向
    同一位置。
    """
    paths = await _seed(tmp_path, monkeypatch)
    settings = get_settings()
    try:
        sync_engine = create_sync_engine(settings)
        async_engine = create_engine(settings)
        store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

        async with session_scope(settings) as session:
            outcome = await search(session, store, "孤独症", embed_query=_fake_embed_query)
        results = outcome.items

        locators = [r.locator for r in results if r.locator]
        assert locators, "结果应带 locator"
        # 至少有一个 locator 含具体章节名，而不只是文档根。
        assert any(loc.strip("/").count("/") >= 1 for loc in locators), f"locator 未定位到章节：{locators}"

        await async_engine.dispose()
        sync_engine.dispose()
    finally:
        await _cleanup(paths)


@pytest.mark.asyncio
async def test_withdrawn_item_is_immediately_unsearchable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """撤下即刻不可检索（`RQ-KB-04`）：查询时过滤，不依赖索引清理。"""
    paths = await _seed(tmp_path, monkeypatch)
    settings = get_settings()
    try:
        sync_engine = create_sync_engine(settings)
        async_engine = create_engine(settings)
        store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

        async with session_scope(settings) as session:
            before = (await search(session, store, "孤独症", embed_query=_fake_embed_query)).items
        assert any(r.title == "视觉支持策略" for r in before)

        # 撤下：同一事务内改条目状态与删节点（RAG 策略第 2 节）。
        async with session_scope(settings) as session:
            item = (
                await session.execute(select(KnowledgeItem).where(KnowledgeItem.source_path == paths[0]))
            ).scalar_one()
            item.withdrawn = True
            await session.execute(RetrievedNode.__table__.delete().where(RetrievedNode.node_id.like(f"{item.id}:%")))

        async with session_scope(settings) as session:
            after = (await search(session, store, "孤独症", embed_query=_fake_embed_query)).items

        assert not any(r.title == "视觉支持策略" for r in after), "撤下后不应再检索到该条目"

        await async_engine.dispose()
        sync_engine.dispose()
    finally:
        await _cleanup(paths)


@pytest.mark.asyncio
async def test_both_paths_failing_raises_instead_of_returning_empty() -> None:
    """两路都失败时抛错——**不得返回空列表让模型以为「没有相关资料」**。"""
    _require_db()

    class _BoomStore:
        async def aquery(self, _query: object) -> object:
            raise RuntimeError("模拟向量路故障")

    async def _boom_embed(_query: str) -> list[float]:
        raise RuntimeError("模拟嵌入故障")

    class _BoomSession:
        async def execute(self, *_args: object, **_kwargs: object) -> object:
            raise RuntimeError("模拟字面路故障")

    with pytest.raises(RetrievalError):
        await search(
            _BoomSession(),  # type: ignore[arg-type]
            _BoomStore(),  # type: ignore[arg-type]
            "孤独症",
            embed_query=_boom_embed,
        )


# ---------------------------------------------------------------------------
# scope 过滤（search_knowledge 的第三个参数）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scope_filters_both_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`scope` 在**两条路**上都生效，不是只过滤一边。

    夹具里两份资料的 `applicable_scope` 分别是「学龄前儿童」与「学龄期儿童」。
    给 `scope="学龄前"` 时应只得前者。

    **为什么必须两条路都测**：只给向量路加过滤、字面路不过滤，会把另一范围的条目
    从字面路漏进来——这条用例单看向量路结果会通过，看汇总标题才会失败。
    """
    paths = await _seed(tmp_path, monkeypatch)
    settings = get_settings()
    try:
        sync_engine = create_sync_engine(settings)
        async_engine = create_engine(settings)
        store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

        async with session_scope(settings) as session:
            outcome = await search(session, store, "儿童", embed_query=_fake_embed_query, scope="学龄前")

        titles = {r.title for r in outcome.items}
        assert "视觉支持策略" in titles, f"本范围内的条目应返回（实际 {titles}）"
        assert "行为应对指南" not in titles, "范围外的条目不得返回"

        await async_engine.dispose()
        sync_engine.dispose()
    finally:
        await _cleanup(paths)


@pytest.mark.asyncio
async def test_scope_matching_nothing_returns_empty_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """没有任何条目匹配 `scope` 时返回**空结果**，而不是报错或退回「不过滤」。

    这一格容易写错：空允许集若被送进向量路的 `IN` 过滤，会生成
    ``metadata_->>'item_id' IN ()`` —— **SQL 语法错误**（实测）。实现因此提前返回。

    判别性：去掉 `search()` 里 `if not scope_ids: return ...` 的提前返回，
    本用例会因 `IN ()` 报错而失败。
    """
    paths = await _seed(tmp_path, monkeypatch)
    settings = get_settings()
    try:
        sync_engine = create_sync_engine(settings)
        async_engine = create_engine(settings)
        store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

        async with session_scope(settings) as session:
            outcome = await search(session, store, "孤独症", embed_query=_fake_embed_query, scope="不存在的范围")

        assert outcome.items == []
        # 这是**正常空结果**，不是降级——两路都正常，只是没有匹配。
        assert outcome.degraded_paths == ()

        await async_engine.dispose()
        sync_engine.dispose()
    finally:
        await _cleanup(paths)


@pytest.mark.asyncio
async def test_scope_value_cannot_inject_sql(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`scope` 里的引号与 `OR` **不得**改变查询语义（注入防护）。

    实测背景：框架的 `MetadataFilter` 用 f-string 拼 SQL（无绑定参数），把值包成
    ``'%{value}%'``。payload 用 ``x' OR 1=1 --``：``--`` 把框架补在尾部的 ``%%'``
    注释掉，剩下的 ``OR 1=1`` 恒真，且 `OR` 的优先级会**逃逸整个 AND 链**、
    连带绕过库别/撤下/状态三个过滤（实测生成
    ``... ILIKE '%%x' OR 1=1 --%%'``）。

    ⚠️ **payload 的选择是有讲究的**：我第一版用 ``x' OR '1'='1``，它渲染成
    ``'1'='1%'``（尾部多了 ``%``）——**恒假**，注入根本不会生效。那条用例因此
    「实现与天真实现都通过」，消融时暴露为**假阴性**。`OR 1=1 --` 才真正逃逸。

    断言注入串被当成**普通子串**：没有条目含这段文本，因此结果必须为空；
    若注入生效，`OR 1=1` 会让所有条目都返回。
    """
    paths = await _seed(tmp_path, monkeypatch)
    settings = get_settings()
    try:
        sync_engine = create_sync_engine(settings)
        async_engine = create_engine(settings)
        store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)

        async with session_scope(settings) as session:
            outcome = await search(session, store, "孤独症", embed_query=_fake_embed_query, scope="x' OR 1=1 --")

        assert outcome.items == [], f"注入串必须被当作普通子串（实际返回 {[r.title for r in outcome.items]}）"

        await async_engine.dispose()
        sync_engine.dispose()
    finally:
        await _cleanup(paths)
