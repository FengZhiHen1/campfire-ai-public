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

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from campfire.core.config import get_settings
from campfire.core.db import create_engine, create_sync_engine, dispose_engine, session_scope
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


@pytest_asyncio.fixture(autouse=True)
async def _dispose_shared_engine() -> AsyncIterator[None]:
    """每个用例前后释放共享引擎（跨事件循环复用会失效，见摄取集成测试的说明）。"""
    await dispose_engine()
    yield
    await dispose_engine()


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
            results = await search(session, store, "孤独症", embed_query=_fake_embed_query)

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
            results = await search(session, store, "干预", embed_query=_fake_embed_query)

        assert results, "短查询应仍走向量路，而不是返回空"

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
            before = await search(session, store, "孤独症", embed_query=_fake_embed_query)
        assert any(r.title == "视觉支持策略" for r in before)

        # 撤下：同一事务内改条目状态与删节点（RAG 策略第 2 节）。
        async with session_scope(settings) as session:
            item = (
                await session.execute(select(KnowledgeItem).where(KnowledgeItem.source_path == paths[0]))
            ).scalar_one()
            item.withdrawn = True
            await session.execute(RetrievedNode.__table__.delete().where(RetrievedNode.node_id.like(f"{item.id}:%")))

        async with session_scope(settings) as session:
            after = await search(session, store, "孤独症", embed_query=_fake_embed_query)

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
