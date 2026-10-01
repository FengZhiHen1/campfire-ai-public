"""案例路集成测试（真实 PostgreSQL）：案例条目表、按库别参数化的检索链、撤下。

对应 [公共案例库] 第 2、6、8 节与 [资料与案例检索] 第 1、3、4、5 节，覆盖本包的
质量地板校验点：

1. 缺 `source` 的案例条目被结果排除（不补默认值）；
2. 撤下条目不返回（`AC-09`），且从两路（向量 + 字面）都消失；
3. `library` 非法取值被拒（不静默退回资料库）；
4. 案例六字段在检索返回里必带；
5. 对抗：空 query（全量浏览路）、只命中卡片不命中标题的检索、manifest 缺字段整包拒绝。

只用虚构样例数据：`EVID-B` 未关闭前不得录真实素材（任务包红线）；上游真实
案例包只用于单元测试的形状核对，不落库。

嵌入用确定性替身（`TOKENHUB_API_KEY` 未配置），SQL、融合、聚合与撤下都是真实的。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from campfire.core.config import get_settings
from campfire.core.db import create_engine, create_sync_engine, session_scope
from campfire.modules.library.case_ingestion import NARRATIVE_SECTIONS, CaseIngestionError, ingest_case_package
from campfire.modules.library.case_schema import CasePackageError
from campfire.modules.library.embedding import EMBEDDING_DIM
from campfire.modules.library.ingestion import build_vector_store
from campfire.modules.library.models import CaseItem, KnowledgeItem, RetrievedNode
from campfire.modules.library.retrieval import (
    RetrievalError,
    browse,
    literal_search,
    search,
)
from campfire.modules.library.withdrawal import withdraw_item

pytestmark = pytest.mark.integration

#: 虚构样例的前缀：保证测试数据可辨认、可清理，且一眼看出不是真实素材。
FICTIONAL_PREFIX = "2099-"


def _fake_vector(text_value: str) -> list[float]:
    seed = sum(ord(ch) for ch in text_value) % 97
    return [0.001 * ((i + seed) % 97 + 1) for i in range(EMBEDDING_DIM)]


class _FakeEmbedder:
    async def aget_text_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        return [_fake_vector(t) for t in texts]


async def _fake_embed_query(query: str) -> list[float]:
    return _fake_vector(query)


@pytest.fixture
def _patched_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "campfire.modules.library.ingestion.build_embedding",
        lambda _settings: _FakeEmbedder(),
    )


def _require_db() -> None:
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")


def _card(**overrides: object) -> dict[str, object]:
    card: dict[str, object] = {
        "card_id": "{AWAITING_SYSTEM}",
        "raw_id": "{AWAITING_SYSTEM}",
        "title": "虚构卡片：结构化日程提示",
        "scenario": "虚构用例场景描述。",
        "behavior_type": "其他",
        "age_range": ["3", "6"],
        "severity_level": "轻",
        "setting": "家庭",
        "ebp_tags": ["视觉支持(VS)"],
        "parent_category": "环境调整",
        "immediate_action": "1. 展示图片日程表。",
        "comforting_phrase": "我们慢慢来。",
        "observation_metrics": "记录一周内主动查看的次数。",
        "medical_criteria": "出现自伤行为即就医。",
        "evidence_level": "INSTITUTIONAL",
        "caution_notes": "不要在情绪高峰时强行要求。",
        "contraindications": "无",
        "is_template": False,
        "_inferred": {"severity_level": "虚构推断理由"},
    }
    card.update(overrides)
    return card


def build_case_package(
    root: Path,
    *,
    slug: str,
    title: str = "虚构案例：结构化活动参与",
    card: dict[str, object] | None = None,
    narrative_keywords: str = "虚构关键词 结构化活动",
    aliases: str = "",
    manifest_overrides: dict[str, object] | None = None,
    source_type: str = "专家访谈转写",
    subject_type: str = "家长",
    authorization: str = "虚构样例（无真实来源）",
    status: str = "internal",
    review_status: str = "owner",
) -> Path:
    """造一个虚构案例包（manifest + L1 叙事 + 一张 L2 卡片）。

    刻意不做成通用工厂：参数只覆盖各用例真正需要的差异，避免长出一层
    「测试夹具框架」（元原则·最小实现）。
    """
    package = root / slug
    package.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, object] = {
        "external_key": f"{FICTIONAL_PREFIX}01-01_0000_{slug}",
        "title": title,
        "source_type": source_type,
        "subject_type": subject_type,
        "interview_at": "2099-01-01T00:00:00+08:00",
        "consent_scope": "ai_retrieval_and_advice",
        "consent_recorded_at": "2099-01-01",
        "evidence_level": "INSTITUTIONAL",
        "review_status": review_status,
        "reviewer": None,
        "authorization": authorization,
        "transcript_ref": "（虚构，无上游转写稿）",
        "keywords": narrative_keywords,
        "aliases": aliases,
        "status": status,
        "files": {"narrative": "L1_x.md", "cards": ["L2_x_01.json"]},
    }
    if manifest_overrides:
        manifest.update(manifest_overrides)
    (package / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    sections = "\n\n".join(
        f"## {name}\n\n虚构的{name}段落，提到结构化活动与图片日程表。" for name in NARRATIVE_SECTIONS
    )
    (package / "L1_x.md").write_text(f"# {title}\n\n{sections}\n", encoding="utf-8")
    (package / "L2_x_01.json").write_text(
        json.dumps(card if card is not None else _card(), ensure_ascii=False), encoding="utf-8"
    )
    return package


async def _cleanup_case(paths: list[str]) -> None:
    """清掉本文件写入的案例条目与其节点（表结构保留）。"""
    async with session_scope(get_settings()) as session:
        for source_path in paths:
            items = (await session.execute(select(CaseItem).where(CaseItem.source_path == source_path))).scalars().all()
            for item in items:
                await session.execute(
                    RetrievedNode.__table__.delete().where(RetrievedNode.node_id.like(f"{item.id}:%"))
                )
                await session.delete(item)


async def _node_counts(item_id: str) -> tuple[int, int]:
    """某条目的 `(节点总数, 元数据声称 withdrawn='false' 的节点数)`。

    第二个数就是「节点元数据与条目表矛盾」的节点数：条目撤下后既不该留有节点，
    更不该有节点声称自己未撤下——那会让向量路的 `withdrawn` 过滤对它失效，
    撤下只剩装配层的二次过滤兜底。
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


def _store():
    settings = get_settings()
    sync_engine = create_sync_engine(settings)
    async_engine = create_engine(settings)
    return (
        settings,
        sync_engine,
        async_engine,
        build_vector_store(settings, engine=sync_engine, async_engine=async_engine),
    )


# ---------------------------------------------------------------------------
# 摄取：条目形状、节点形状、整包拒绝
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_writes_case_item_with_all_seven_fields(tmp_path: Path, _patched_embedding: None) -> None:
    """摄取的案例条目带齐七个案例专属字段与共有字段。"""
    _require_db()
    package = build_case_package(tmp_path, slug="fields")
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            result = await ingest_case_package(settings, session, vector_store=store, package_dir=package)

        assert result.skipped is False
        assert result.cards_written == 1
        assert result.narrative_nodes == len(NARRATIVE_SECTIONS)

        async with session_scope(settings) as session:
            item = (
                await session.execute(select(CaseItem).where(CaseItem.id == uuid.UUID(result.item_id)))
            ).scalar_one()
            assert item.authorization == "虚构样例（无真实来源）"
            assert item.source_type == "专家访谈转写"
            assert item.evidence_level == "INSTITUTIONAL"
            assert item.review_status == "owner"
            assert item.interview_at is not None
            assert item.makes_claims_high_risk is True, "卡片含 medical_criteria，应为高风险"
            assert item.inferred_fields == ["severity_level"]
            assert item.subject_type == "家长"
            assert item.status == "internal"
            assert item.source, "来源不得为空（不变量）"
            assert item.applicable_scope, "适用范围不得为空（不变量）"
    finally:
        await _cleanup_case([str(package)])
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_card_node_carries_card_level_metadata(tmp_path: Path, _patched_embedding: None) -> None:
    """卡片节点带卡片级维度（`card_id`、结构化过滤维度、被推断字段）。"""
    _require_db()
    package = build_case_package(tmp_path, slug="cardmeta")
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            result = await ingest_case_package(settings, session, vector_store=store, package_dir=package)

        async with session_scope(settings) as session:
            rows = (
                await session.execute(
                    text(
                        "select node_id, metadata_ from data_campfire_node "
                        "where metadata_->>'item_id' = :i and metadata_->>'node_kind' = 'card'"
                    ),
                    {"i": result.item_id},
                )
            ).all()

        assert len(rows) == 1
        metadata = rows[0].metadata_
        assert metadata["card_id"].endswith("#01"), f"card_id 规则应为 <external_key>#<NN>：{metadata['card_id']}"
        assert metadata["library"] == "case"
        assert metadata["withdrawn"] == "false"
        assert metadata["inferred_fields"] == ["severity_level"]
        # 结构化过滤维度（RAG 策略第 2 节的案例投影清单）
        for key in ("behavior_type", "age_range", "severity_level", "ebp_tags", "parent_category"):
            assert key in metadata, f"卡片节点缺少过滤维度 {key}"
        # 返回契约消费的字段
        for key in ("authorization", "source_type", "evidence_level", "review_status", "interview_at"):
            assert key in metadata, f"卡片节点缺少返回契约字段 {key}"
        # 标识字段不参与嵌入（此处断言它们不在文本里）
        assert "card_id" not in rows[0].node_id.split(":")[-1]
    finally:
        await _cleanup_case([str(package)])
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_manifest_missing_field_rejects_whole_package(tmp_path: Path, _patched_embedding: None) -> None:
    """manifest 缺字段 → 整包拒绝且不留半个案例（第 6 节）。

    判别性：把 `load_manifest` 的必填校验删掉，本用例的写入断言失败。
    """
    _require_db()
    package = build_case_package(tmp_path, slug="nofield", manifest_overrides={"authorization": None})
    settings, sync_engine, async_engine, store = _store()

    try:
        with pytest.raises(CaseIngestionError, match="authorization"):
            async with session_scope(settings) as session:
                await ingest_case_package(settings, session, vector_store=store, package_dir=package)

        async with session_scope(settings) as session:
            count = (
                await session.execute(
                    select(func.count()).select_from(CaseItem).where(CaseItem.source_path == str(package))
                )
            ).scalar_one()
        assert count == 0, "拒绝导入后仍留下条目——留下了「一半进去了」的状态"
    finally:
        await _cleanup_case([str(package)])
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_invalid_card_rejects_whole_package(tmp_path: Path, _patched_embedding: None) -> None:
    """卡片值域越界 → 整包拒绝，不留条目、不留节点（第 6 节）。"""
    _require_db()
    package = build_case_package(tmp_path, slug="badcard", card=_card(behavior_type="焦虑"))
    settings, sync_engine, async_engine, store = _store()

    try:
        with pytest.raises(CaseIngestionError, match="behavior_type"):
            async with session_scope(settings) as session:
                await ingest_case_package(settings, session, vector_store=store, package_dir=package)

        async with session_scope(settings) as session:
            count = (
                await session.execute(
                    select(func.count()).select_from(CaseItem).where(CaseItem.source_path == str(package))
                )
            ).scalar_one()
        assert count == 0
    finally:
        await _cleanup_case([str(package)])
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_case_ingest_is_idempotent_for_unchanged_package(tmp_path: Path, _patched_embedding: None) -> None:
    """内容未变时跳过，不产生重复条目（幂等）。"""
    _require_db()
    package = build_case_package(tmp_path, slug="idem")
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            first = await ingest_case_package(settings, session, vector_store=store, package_dir=package)
        async with session_scope(settings) as session:
            second = await ingest_case_package(settings, session, vector_store=store, package_dir=package)

        assert first.skipped is False
        assert second.skipped is True, "内容未变的案例包应被跳过"

        async with session_scope(settings) as session:
            count = (
                await session.execute(
                    select(func.count()).select_from(CaseItem).where(CaseItem.source_path == str(package))
                )
            ).scalar_one()
        assert count == 1, "幂等失败：产生了重复案例条目"
    finally:
        await _cleanup_case([str(package)])
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_changed_card_is_reingested(tmp_path: Path, _patched_embedding: None) -> None:
    """只改卡片内容（manifest 不动）也必须重新入库。

    这是哈希覆盖全部文件而非只哈希 manifest 的理由：只哈希 manifest 会让
    「卡片被重抽过」被静默跳过，库里留着旧卡片而运维以为已更新。
    """
    _require_db()
    package = build_case_package(tmp_path, slug="changed")
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            first = await ingest_case_package(settings, session, vector_store=store, package_dir=package)

        (package / "L2_x_01.json").write_text(
            json.dumps(_card(title="虚构卡片：改过的标题"), ensure_ascii=False), encoding="utf-8"
        )

        async with session_scope(settings) as session:
            second = await ingest_case_package(settings, session, vector_store=store, package_dir=package)

        assert first.skipped is False
        assert second.skipped is False, "卡片内容变了却被跳过——库里会留着旧卡片"
    finally:
        await _cleanup_case([str(package)])
        await async_engine.dispose()
        sync_engine.dispose()


# ---------------------------------------------------------------------------
# 库别参数化：非法取值被拒、两库不串
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_library", ["", "cases", "Knowledge", "knowledge ", "1"])
def test_invalid_library_is_rejected(bad_library: str) -> None:
    """`library` 非法取值被拒（质量地板校验点 ③）。

    不静默退回资料库：那会让 `search_cases` 拿到资料条目并当成案例呈现。
    """
    import asyncio

    class _NoSession:
        async def execute(self, *_a: object, **_kw: object) -> object:
            raise AssertionError("非法库别不应走到查库")

    class _NoStore:
        async def aquery(self, _q: object) -> object:
            raise AssertionError("非法库别不应走到向量路")

    with pytest.raises(RetrievalError, match="非法库别"):
        asyncio.run(
            search(
                _NoSession(),  # type: ignore[arg-type]  # 最小替身：非法库别必须在触到查询之前就被拒，不需要真会话
                _NoStore(),  # type: ignore[arg-type]  # 同上：向量路连碰都不该被碰到
                "查询",
                library=bad_library,
                embed_query=_fake_embed_query,
            )
        )


def test_invalid_library_is_rejected_by_literal_search() -> None:
    """字面路同样拒绝非法库别（表名取自映射表，不能靠默认值兜底）。"""
    import asyncio

    class _NoSession:
        async def execute(self, *_a: object, **_kw: object) -> object:
            raise AssertionError("非法库别不应走到查库")

    with pytest.raises(RetrievalError, match="非法库别"):
        asyncio.run(literal_search(_NoSession(), "虚构查询", library="bogus"))  # type: ignore[arg-type]  # 最小替身：非法库别必须在触到查询之前就被拒


@pytest.mark.asyncio
async def test_case_search_never_returns_knowledge_items(tmp_path: Path, _patched_embedding: None) -> None:
    """案例检索不混入资料条目，反之亦然（`RQ-KB-01` 两库分离）。

    这条用例必须两库都有数据才有判别力：库为空时「结果里没有资料条目」
    是无意义的真。因此这里先灌一份资料与一份案例，再断言各自只回自己的。
    """
    _require_db()
    package = build_case_package(tmp_path, slug="sep", narrative_keywords="虚构关键词 结构化活动")
    settings, sync_engine, async_engine, store = _store()

    knowledge_doc = tmp_path / "knowledge.md"
    knowledge_doc.write_text("# 资料标题\n\n结构化活动的资料正文。\n", encoding="utf-8")

    from campfire.modules.library.ingestion import ingest_file

    try:
        async with session_scope(settings) as session:
            await ingest_file(
                settings,
                session,
                vector_store=store,
                path=knowledge_doc,
                title="虚构资料条目",
                source="虚构出处",
                applicable_scope="虚构范围",
                keywords="结构化活动",
            )
        async with session_scope(settings) as session:
            await ingest_case_package(settings, session, vector_store=store, package_dir=package)

        async with session_scope(settings) as session:
            case_outcome = await search(session, store, "结构化活动", library="case", embed_query=_fake_embed_query)
        async with session_scope(settings) as session:
            knowledge_outcome = await search(
                session, store, "结构化活动", library="knowledge", embed_query=_fake_embed_query
            )

        assert case_outcome.items, "案例库应有命中（否则本用例没有判别力）"
        assert knowledge_outcome.items, "资料库应有命中（否则本用例没有判别力）"

        assert all(r.library == "case" for r in case_outcome.items), "案例检索混入了其他库"
        assert all(r.library == "knowledge" for r in knowledge_outcome.items), "资料检索混入了其他库"
        assert "虚构资料条目" not in {r.title for r in case_outcome.items}, "案例结果里出现了资料条目"
        assert "虚构案例：结构化活动参与" not in {r.title for r in knowledge_outcome.items}, "资料结果里出现了案例条目"
    finally:
        await _cleanup_case([str(package)])
        async with session_scope(settings) as session:
            items = (
                (await session.execute(select(KnowledgeItem).where(KnowledgeItem.source_path == str(knowledge_doc))))
                .scalars()
                .all()
            )
            for item in items:
                await session.execute(
                    RetrievedNode.__table__.delete().where(RetrievedNode.node_id.like(f"{item.id}:%"))
                )
                await session.delete(item)
        await async_engine.dispose()
        sync_engine.dispose()


# ---------------------------------------------------------------------------
# 返回契约：案例六字段必带（第 3 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_results_carry_every_contract_field(tmp_path: Path, _patched_embedding: None) -> None:
    """案例检索结果带齐共有字段 + 案例六字段 + `inferred_fields`（第 3 节）。

    这六项不是装饰：缺任一个，输出就无法如实回答「谁说的、多可信、什么时候」
    （[公共案例库] 第 8 节的呈现规则因此无法落地）。
    """
    _require_db()
    package = build_case_package(tmp_path, slug="contract")
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            await ingest_case_package(settings, session, vector_store=store, package_dir=package)
        async with session_scope(settings) as session:
            outcome = await search(session, store, "结构化活动", library="case", embed_query=_fake_embed_query)

        assert outcome.items, "应有命中"
        hit = outcome.items[0]

        # 共有字段（第 3 节的 KnowledgeResult）
        assert hit.item_id
        assert hit.library == "case"
        assert hit.title
        assert hit.snippet
        assert hit.source
        assert hit.applicable_scope
        assert hit.status
        assert hit.ranking.get("hit_paths")

        # 案例必带六项
        assert hit.authorization == "虚构样例（无真实来源）"
        assert hit.source_type == "专家访谈转写"
        assert hit.evidence_level == "INSTITUTIONAL"
        assert hit.review_status == "owner"
        assert hit.interview_at is not None
        assert hit.makes_claims_high_risk is True

        # inferred_fields：命中卡片时有值；命中叙事小节时为空清单
        assert isinstance(hit.inferred_fields, list)
    finally:
        await _cleanup_case([str(package)])
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_card_hits_aggregate_into_a_single_case_entry(tmp_path: Path, _patched_embedding: None) -> None:
    """卡片级命中聚合回案例条目，同一案例只出现一条（第 2 节）。

    「呈现单位是案例、检索单位是卡片」的可测部分：一个案例有 1 张卡片 + 5 个叙事
    小节，共 6 个节点；检索命中其中多个时，结果里必须只有一条该案例
    （否则同一个案例会以多行出现，使用者看到重复的依据）。
    判别性：把 `aggregate_to_items` 的 `item_id` 聚合改成按 `node_id` 出条目，
    本用例的「只出现一条」断言失败。

    ⚠️ 本用例不断言 snippet 来自卡片：snippet 取的是「名次最高的节点」，
    而本文件用确定性假嵌入（没有 TOKENHUB_API_KEY），名次与语义无关、
    哪条节点胜出是任意的。断言「卡片胜出」会是一条时真时假的检查——那比不测更糟。
    卡片是否真的成为可检索节点由下面那条用例直接核对节点层。
    """
    _require_db()
    package = build_case_package(
        tmp_path,
        slug="cardonly",
        title="虚构案例：与查询词无关的标题",
        narrative_keywords="无关词甲",
        card=_card(comforting_phrase="我们慢慢来，先深呼吸再一起看日程表。"),
    )
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            result = await ingest_case_package(settings, session, vector_store=store, package_dir=package)
        async with session_scope(settings) as session:
            outcome = await search(session, store, "深呼吸", library="case", embed_query=_fake_embed_query)

        assert outcome.items, "应能检索到"
        titles = [r.title for r in outcome.items]
        assert titles.count("虚构案例：与查询词无关的标题") == 1, f"同一案例应只出现一条：{titles}"
        # 六字段在该条目上仍在场（聚合补字段的路径覆盖到案例分支）。
        hit = outcome.items[0]
        assert hit.review_status == "owner"
        # inferred_fields 的契约是「该 snippet 所属卡片的推断清单」：命中卡片时
        # 为该卡片的清单，命中叙事小节时为空。假嵌入下胜出节点是任意的，因此这里
        # 断言的是取值只能落在这两个合法状态之一，不能是别的东西
        # （例如案例级并集或畸形字符串）——恒真或恒假的断言都没有价值。
        assert hit.inferred_fields in ([], ["severity_level"]), f"推断清单取值非法：{hit.inferred_fields}"
        assert result.cards_written == 1
    finally:
        await _cleanup_case([str(package)])
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_card_body_is_indexed_as_its_own_node(tmp_path: Path, _patched_embedding: None) -> None:
    """卡片正文真的进了节点表（检索单位是卡片的可执行证据）。

    只断言节点层：卡片节点的文本含卡片字段内容，且不含 `_inferred` 的值
    （推断依据不参与嵌入，RAG 策略第 1.3 节）。
    """
    _require_db()
    package = build_case_package(
        tmp_path,
        slug="cardnode",
        card=_card(comforting_phrase="我们慢慢来，先深呼吸再一起看日程表。"),
    )
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            result = await ingest_case_package(settings, session, vector_store=store, package_dir=package)

        async with session_scope(settings) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "select text from data_campfire_node "
                            "where metadata_->>'item_id' = :i and metadata_->>'node_kind' = 'card'"
                        ),
                        {"i": result.item_id},
                    )
                )
                .scalars()
                .all()
            )

        assert len(rows) == 1, "一张卡片应产出恰好一个节点"
        card_text = rows[0]
        assert "深呼吸" in card_text, "卡片正文未进入节点"
        assert "comforting_phrase" in card_text, "卡片节点应是「字段名：值」的结构化拼接"
        assert "虚构推断理由" not in card_text, "_inferred 的值不得参与嵌入"
        assert "card_id" not in card_text, "标识字段不得参与嵌入"
    finally:
        await _cleanup_case([str(package)])
        await async_engine.dispose()
        sync_engine.dispose()


# ---------------------------------------------------------------------------
# 缺字段条目被排除（不变量：不补默认值）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_item_without_source_is_excluded_from_results(tmp_path: Path, _patched_embedding: None) -> None:
    """缺 `source` 的案例条目被结果排除，不补默认值（质量地板校验点 ①）。

    做法：先正常入库，再把条目表的 `source` 直接在库里清空（模拟旁路写入/脏数据），
    然后断言检索与浏览都不返回它。表上是 NOT NULL，因此这里用临时解除约束的
    方式构造该状态——它正是「不变量必须由代码兜住、不能只靠存储层」的理由：
    约束变更、历史数据、将来的运维旁路都可能绕开 NOT NULL。
    """
    _require_db()
    package = build_case_package(tmp_path, slug="nosource")
    settings, sync_engine, async_engine, store = _store()

    engine = create_engine(settings)
    try:
        async with session_scope(settings) as session:
            result = await ingest_case_package(settings, session, vector_store=store, package_dir=package)
        async with session_scope(settings) as session:
            before = await search(session, store, "结构化活动", library="case", embed_query=_fake_embed_query)
        assert any(r.title == "虚构案例：结构化活动参与" for r in before.items), "前置：清空前应能检索到"

        # 临时解除 NOT NULL 以构造「缺来源」的脏数据（这正是要防的旁路写入）。
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE campfire_case_item ALTER COLUMN source DROP NOT NULL"))
            await conn.execute(
                text("UPDATE campfire_case_item SET source = '' WHERE id = CAST(:i AS uuid)"),
                {"i": result.item_id},
            )

        async with session_scope(settings) as session:
            after = await search(session, store, "结构化活动", library="case", embed_query=_fake_embed_query)
        async with session_scope(settings) as session:
            browsed = await browse(session, library="case", limit=50)

        assert not any(r.title == "虚构案例：结构化活动参与" for r in after.items), "缺来源的条目不进入检索结果"
        assert not any(r.title == "虚构案例：结构化活动参与" for r in browsed.items), "缺来源的条目不进入浏览结果"
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE campfire_case_item ALTER COLUMN source SET NOT NULL"))
        await engine.dispose()
        await _cleanup_case([str(package)])
        await async_engine.dispose()
        sync_engine.dispose()


# ---------------------------------------------------------------------------
# 撤下：AC-09（两路都消失 + 幂等）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_withdrawn_case_disappears_from_both_paths(tmp_path: Path, _patched_embedding: None) -> None:
    """撤下后两路（向量 + 字面）都查不到，浏览路也不返回（`AC-09`）。

    为什么必须分两路断言：向量路靠「查询时过滤 `withdrawn`」，字面路靠条目表的
    `WHERE withdrawn IS FALSE`。只删节点不置标记，字面路仍会命中条目；
    只置标记不删节点，向量路在聚合前就已过滤、看似安全——但节点会一直被召回并
    占用候选槽位。两条路各断言一次，才覆盖这两种半吊子实现。
    """
    _require_db()
    # 关键词与标题都含查询词，保证字面路可用（≥3 连续汉字）。
    package = build_case_package(
        tmp_path,
        slug="withdraw",
        title="虚构案例：结构化活动撤下用例",
        narrative_keywords="结构化活动 撤下",
    )
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            result = await ingest_case_package(settings, session, vector_store=store, package_dir=package)

        # 撤下前：字面路与检索路都应命中。
        async with session_scope(settings) as session:
            literal_before = await literal_search(session, "结构化活动", library="case")
        async with session_scope(settings) as session:
            fused_before = await search(session, store, "结构化活动", library="case", embed_query=_fake_embed_query)
        assert literal_before, "前置：撤下前字面路应命中"
        assert any(r.title == "虚构案例：结构化活动撤下用例" for r in fused_before.items), "前置：撤下前应命中"

        # 撤下（条目标记 + 删节点，同事务）。
        async with session_scope(settings) as session:
            withdrawal = await withdraw_item(session, library="case", item_id=result.item_id, reason="虚构测试撤下")
        assert withdrawal.already_withdrawn is False
        assert withdrawal.nodes_deleted > 0, "撤下应删除该条目的检索节点"

        # 撤下后：字面路、检索路、浏览路都不返回。
        async with session_scope(settings) as session:
            literal_after = await literal_search(session, "结构化活动", library="case")
        async with session_scope(settings) as session:
            fused_after = await search(session, store, "结构化活动", library="case", embed_query=_fake_embed_query)
        async with session_scope(settings) as session:
            browsed_after = await browse(session, library="case", limit=50)

        assert literal_after == [], "撤下后字面路仍命中——条目表的 withdrawn 过滤失效"
        assert not any(r.title == "虚构案例：结构化活动撤下用例" for r in fused_after.items), "撤下后检索仍返回"
        assert not any(r.title == "虚构案例：结构化活动撤下用例" for r in browsed_after.items), "撤下后浏览仍返回"

        # 撤下后该条目不应留下任何节点。
        async with session_scope(settings) as session:
            leftovers = (
                await session.execute(
                    text("select count(*) from data_campfire_node where metadata_->>'item_id' = :i"),
                    {"i": result.item_id},
                )
            ).scalar_one()
        assert leftovers == 0, "撤下后仍留有节点——向量路会继续召回它"
    finally:
        await _cleanup_case([str(package)])
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_withdrawal_is_idempotent(tmp_path: Path, _patched_embedding: None) -> None:
    """撤下重复执行两次：第二次不报错、标 `already_withdrawn`（幂等实测）。

    任务包自检要求「撤下幂等实测两次」；这里就是那两次连续调用。
    """
    _require_db()
    package = build_case_package(tmp_path, slug="idemwithdraw")
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            result = await ingest_case_package(settings, session, vector_store=store, package_dir=package)

        async with session_scope(settings) as session:
            first = await withdraw_item(session, library="case", item_id=result.item_id, reason="第一次")
        async with session_scope(settings) as session:
            second = await withdraw_item(session, library="case", item_id=result.item_id, reason="第二次")

        assert first.already_withdrawn is False
        assert second.already_withdrawn is True, "重复撤下应被识别为幂等而不是再次变更"
        assert first.nodes_deleted > 0
        assert second.nodes_deleted == 0

        # 首次撤下的时间与原因不被重跑覆盖（审计事实）。
        async with session_scope(settings) as session:
            item = (
                await session.execute(select(CaseItem).where(CaseItem.id == uuid.UUID(result.item_id)))
            ).scalar_one()
            assert item.withdrawn_reason == "第一次", "重复撤下覆盖了首次原因——审计事实失真"
            assert item.withdrawn_at is not None
    finally:
        await _cleanup_case([str(package)])
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_reingest_after_withdrawal_does_not_rebuild_nodes(tmp_path: Path, _patched_embedding: None) -> None:
    """撤下后重新摄取改过的包：不重建节点，且节点元数据不得与条目表矛盾（D-16）。

    撤下在向量路上的生效机制就是「该条目没有节点」（`withdrawal.py` 同事务删除）；
    内容哈希变化时无条件重建节点，会让「撤下后节点真删」的承诺被后续摄取推翻，
    而重建时硬编码的 `withdrawn="false"` 又让向量路的 `withdrawn` 过滤对已撤下
    条目失效——安全性只剩装配层的二次过滤，等于把「撤下生效」押在调用方记得过滤上。

    判别性（对未修复实现会失败）：重建的节点让「节点数不增加」失败，
    其中声称 `withdrawn="false"` 的节点让「元数据与条目表一致」失败。
    """
    _require_db()
    package = build_case_package(tmp_path, slug="withdraw-reingest")
    settings, sync_engine, async_engine, store = _store()

    try:
        # 前置：入库后节点在场——否则后面的「不增加」是无意义的真。
        async with session_scope(settings) as session:
            first = await ingest_case_package(settings, session, vector_store=store, package_dir=package)
        total_before, _ = await _node_counts(first.item_id)
        assert total_before == 1 + len(NARRATIVE_SECTIONS), f"前置：应写入 1 张卡片 + 五节叙事节点，实际 {total_before}"

        # 前置对照：撤下前两路都命得中——否则文末的「查不到」是无判别力的空断言。
        async with session_scope(settings) as session:
            literal_before = await literal_search(session, "结构化活动", library="case")
        async with session_scope(settings) as session:
            fused_before = await search(session, store, "结构化活动", library="case", embed_query=_fake_embed_query)
        assert any(item_id == first.item_id for item_id, _rank in literal_before), "前置：撤下前字面路应命中该条目"
        assert any(r.item_id == first.item_id for r in fused_before.items), "前置：撤下前检索路应命中该条目"

        async with session_scope(settings) as session:
            withdrawal = await withdraw_item(session, library="case", item_id=first.item_id, reason="虚构测试撤下")
        assert withdrawal.nodes_deleted == total_before
        assert await _node_counts(first.item_id) == (0, 0), "前置：撤下应清空该条目的节点"

        # 改内容后重新摄取：上游修订后重新交付是正常运维路径。
        (package / "L2_x_01.json").write_text(
            json.dumps(_card(title="虚构卡片：撤下后改过的标题"), ensure_ascii=False), encoding="utf-8"
        )
        async with session_scope(settings) as session:
            second = await ingest_case_package(settings, session, vector_store=store, package_dir=package)

        assert second.item_id == first.item_id, "同一 source_path 应复用同一条目，不该新建条目"
        assert second.skipped is False, "内容已变，不该被当作「未变」跳过"
        assert await _node_counts(first.item_id) == (0, 0), (
            "撤下后重新摄取重建了节点（或写回了声称未撤下的节点）——「撤下即删节点」的承诺被推翻"
        )
        assert (second.cards_written, second.narrative_nodes) == (0, 0), "已撤下的条目不得写回节点"

        # 条目表的撤下事实与审计字段仍在：摄取不得动摇撤下状态。
        async with session_scope(settings) as session:
            item = (await session.execute(select(CaseItem).where(CaseItem.id == uuid.UUID(first.item_id)))).scalar_one()
            assert item.withdrawn is True, "重新摄取把条目恢复成在库——撤下被上游重新交付静默推翻"
            assert item.withdrawn_reason == "虚构测试撤下"
            assert item.withdrawn_at is not None

        # 端到端：撤下的用户可见后果不因重新摄取而改变（两路都查不到）。
        async with session_scope(settings) as session:
            literal_after = await literal_search(session, "结构化活动", library="case")
        async with session_scope(settings) as session:
            fused_after = await search(session, store, "结构化活动", library="case", embed_query=_fake_embed_query)
        assert all(item_id != first.item_id for item_id, _rank in literal_after), "撤下后字面路仍命中该条目"
        assert all(r.item_id != first.item_id for r in fused_after.items), "撤下后检索路仍返回该条目"

        # 再摄取同一份改过的包：走同一条「内容未变」幂等路径（撤下状态不破坏幂等）。
        async with session_scope(settings) as session:
            third = await ingest_case_package(settings, session, vector_store=store, package_dir=package)
        assert third.skipped is True, "已撤下条目的重复摄取应被幂等跳过"
    finally:
        await _cleanup_case([str(package)])
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_reingest_unchanged_after_withdrawal_clears_residual_nodes(
    tmp_path: Path, _patched_embedding: None
) -> None:
    """撤下后重新交付同一份包（哈希不变）：幂等跳过也要清掉残留节点。

    与 `test_reingest_after_withdrawal_does_not_rebuild_nodes` 互补：那条走「改了卡片
    再重摄取」分支（哈希变化），本用例一个字节都不改，落在幂等早返回分支上——上游最
    常见的重交付形态正是同一份包再送一次。

    对未修复实现：`skipped` 为真，但残留节点仍在（节点数断言是 (1, 1) 而非 (0, 0)）。
    """
    _require_db()
    package = build_case_package(tmp_path, slug="withdraw-unchanged")
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            first = await ingest_case_package(settings, session, vector_store=store, package_dir=package)

        async with session_scope(settings) as session:
            await withdraw_item(session, library="case", item_id=first.item_id, reason="虚构测试撤下")
        assert await _node_counts(first.item_id) == (0, 0), "前置：撤下应清空节点"

        # 造出「撤下之后节点又出现」的状态：旁路写入一条声称未撤下的节点。
        async with session_scope(settings) as session:
            table = store._table_class  # noqa: SLF001 —— 与摄取写节点同一张框架表模型
            session.add(
                table(
                    node_id=f"{first.item_id}:stray",
                    text="旁路写入的残留正文",
                    embedding=_fake_vector("旁路写入的残留正文"),
                    metadata_={"item_id": first.item_id, "library": "case", "withdrawn": "false"},
                )
            )
        assert await _node_counts(first.item_id) == (1, 1), "前置：应已注入一条声称未撤下的残留节点"

        # 包内文件一个字节都不改：这次走的是幂等「内容未变」分支。
        async with session_scope(settings) as session:
            second = await ingest_case_package(settings, session, vector_store=store, package_dir=package)

        assert second.skipped is True, "前置：内容未变的包应被幂等跳过"
        assert (second.cards_written, second.narrative_nodes) == (0, 0), "跳过语义不变：不写节点"
        assert await _node_counts(first.item_id) == (0, 0), (
            "哈希未变的重复摄取没有清掉已撤下案例的残留节点——「撤下后该条目没有节点」这条承诺在这条路径上不成立"
        )
    finally:
        await _cleanup_case([str(package)])
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_withdraw_rejects_invalid_library_and_unknown_item(tmp_path: Path, _patched_embedding: None) -> None:
    """撤下拒绝非法库别与不存在的条目（不静默成功）。"""
    _require_db()
    from campfire.modules.library.withdrawal import WithdrawalError

    settings, sync_engine, async_engine, store = _store()
    try:
        async with session_scope(settings) as session:
            with pytest.raises(WithdrawalError, match="非法库别"):
                await withdraw_item(session, library="bogus", item_id="11111111-1111-4111-8111-111111111111")

        async with session_scope(settings) as session:
            with pytest.raises(WithdrawalError, match="条目不存在"):
                await withdraw_item(session, library="case", item_id="11111111-1111-4111-8111-111111111111")

        async with session_scope(settings) as session:
            with pytest.raises(RetrievalError, match="非法条目 id"):
                await withdraw_item(session, library="case", item_id="not-a-uuid")
    finally:
        await async_engine.dispose()
        sync_engine.dispose()


# ---------------------------------------------------------------------------
# 对抗用例：空 query 浏览路、authorization 过滤、scope 过滤
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_query_browses_all_cases_by_recency(tmp_path: Path, _patched_embedding: None) -> None:
    """空 query = 全量浏览流，按最近入库排序（资料库面第 3 节），不走检索两路。

    不编造「热门」排序：无真实行为数据支撑排序策略前只用时间序。
    """
    _require_db()
    first = build_case_package(tmp_path, slug="browse-a", title="虚构案例：先入库")
    second = build_case_package(tmp_path, slug="browse-b", title="虚构案例：后入库")
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            await ingest_case_package(settings, session, vector_store=store, package_dir=first)
        async with session_scope(settings) as session:
            await ingest_case_package(settings, session, vector_store=store, package_dir=second)

        async with session_scope(settings) as session:
            outcome = await search(session, store, "   ", library="case", embed_query=_fake_embed_query)

        titles = [r.title for r in outcome.items]
        assert "虚构案例：先入库" in titles
        assert "虚构案例：后入库" in titles
        assert titles.index("虚构案例：后入库") < titles.index("虚构案例：先入库"), "应按最近入库排序（倒序）"
        # 浏览路不走向量/字面两路 → 没有「某一路不可用」这回事。
        assert outcome.degraded_paths == ()
        # 浏览路也带案例六字段（列表消费形状）
        sample = next(r for r in outcome.items if r.title == "虚构案例：先入库")
        assert sample.review_status == "owner"
        assert sample.evidence_level == "INSTITUTIONAL"
        assert sample.interview_at is not None
        assert sample.authorization == "虚构样例（无真实来源）"
        assert sample.inferred_fields == [], "浏览路是条目级列表，无卡片级推断标注"
    finally:
        await _cleanup_case([str(first), str(second)])
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_authorization_filter_applies_to_both_paths(tmp_path: Path, _patched_embedding: None) -> None:
    """`authorization` 过滤在两条路上都生效，且走绑定参数（第 3 节、工具契约第 6 节）。

    为什么必须两条路都测：只给向量路加过滤、字面路不过滤，会把未授权条目从字面路
    漏进结果——单看向量路结果会通过，看汇总标题才会失败。

    这条同时是 `authorization` 列名的回归护栏：它是 PostgreSQL 保留字，
    原生 SQL 里必须加双引号，否则 `syntax error at or near "from"`。
    """
    _require_db()
    allowed = build_case_package(tmp_path, slug="auth-ok", title="虚构案例：已授权", authorization="已授权")
    denied = build_case_package(tmp_path, slug="auth-no", title="虚构案例：未授权", authorization="未授权")
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            await ingest_case_package(settings, session, vector_store=store, package_dir=allowed)
        async with session_scope(settings) as session:
            await ingest_case_package(settings, session, vector_store=store, package_dir=denied)

        async with session_scope(settings) as session:
            literal = await literal_search(session, "结构化活动", library="case", authorization="已授权")
        async with session_scope(settings) as session:
            outcome = await search(
                session,
                store,
                "结构化活动",
                library="case",
                embed_query=_fake_embed_query,
                authorization="已授权",
            )

        assert literal, "字面路应命中已授权条目（authorization 列名/过滤可用）"
        titles = {r.title for r in outcome.items}
        assert "虚构案例：已授权" in titles, f"已授权条目应返回（实际 {titles}）"
        assert "虚构案例：未授权" not in titles, "未授权条目不得返回"
        assert all(r.authorization == "已授权" for r in outcome.items), "返回项的授权状态应符合过滤值"
    finally:
        await _cleanup_case([str(allowed), str(denied)])
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_scope_filter_applies_to_case_search(tmp_path: Path, _patched_embedding: None) -> None:
    """`scope` 过滤在案例路同样生效（两库共用检索链，过滤语义一致）。"""
    _require_db()
    parent = build_case_package(tmp_path, slug="scope-parent", title="虚构案例：家长经验", subject_type="家长")
    teacher = build_case_package(tmp_path, slug="scope-teacher", title="虚构案例：老师经验", subject_type="老师")
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            await ingest_case_package(settings, session, vector_store=store, package_dir=parent)
        async with session_scope(settings) as session:
            await ingest_case_package(settings, session, vector_store=store, package_dir=teacher)

        async with session_scope(settings) as session:
            outcome = await search(
                session, store, "结构化活动", library="case", embed_query=_fake_embed_query, scope="家长"
            )

        titles = {r.title for r in outcome.items}
        assert "虚构案例：家长经验" in titles, f"本范围内的条目应返回（实际 {titles}）"
        assert "虚构案例：老师经验" not in titles, "范围外的条目不得返回"
    finally:
        await _cleanup_case([str(parent), str(teacher)])
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_scope_matching_nothing_returns_empty_not_an_error(tmp_path: Path, _patched_embedding: None) -> None:
    """没有任何案例匹配 `scope` 时返回空结果，而不是报错（空 `IN ()` 的护栏）。

    这一格容易写错：空允许集若被送进向量路的 `IN` 过滤，会生成
    `metadata_->>'item_id' IN ()` —— SQL 语法错误（实测）。实现因此提前返回。
    """
    _require_db()
    package = build_case_package(tmp_path, slug="scope-none")
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            await ingest_case_package(settings, session, vector_store=store, package_dir=package)

        async with session_scope(settings) as session:
            outcome = await search(
                session, store, "结构化活动", library="case", embed_query=_fake_embed_query, scope="不存在的范围"
            )

        assert outcome.items == []
        assert outcome.degraded_paths == (), "这是正常空结果，不是降级"
    finally:
        await _cleanup_case([str(package)])
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_authorization_value_cannot_inject_sql(tmp_path: Path, _patched_embedding: None) -> None:
    """`authorization` 里的引号与 `OR` 不得改变查询语义（注入防护）。

    实测背景：框架的 `MetadataFilter` 用 f-string 拼 SQL（无绑定参数）。payload 用
    `x' OR 1=1 --` 会逃逸整个 AND 链、连带绕过库别/撤下/状态三个过滤。
    本实现因此把「模型可控值」拦在 MetadataFilter 之外（先用绑定参数算允许集）。

    判别性：把 `_item_filters_sql` 的 `:authorization` 改回字符串拼接，本用例失败。
    """
    _require_db()
    package = build_case_package(tmp_path, slug="inject")
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            await ingest_case_package(settings, session, vector_store=store, package_dir=package)

        async with session_scope(settings) as session:
            outcome = await search(
                session,
                store,
                "结构化活动",
                library="case",
                embed_query=_fake_embed_query,
                authorization="x' OR 1=1 --",
            )

        assert outcome.items == [], f"注入串必须被当作普通值（实际返回 {[r.title for r in outcome.items]}）"
    finally:
        await _cleanup_case([str(package)])
        await async_engine.dispose()
        sync_engine.dispose()


# ---------------------------------------------------------------------------
# 既有资料检索零回归（本包改动不得影响资料路）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_knowledge_path_still_works_unchanged(tmp_path: Path, _patched_embedding: None) -> None:
    """资料路检索在参数化之后行为不变（零回归的正面证据）。

    既有 `test_library_retrieval_integration.py` 覆盖了边界，这里补一条最小正例，
    确认默认库别仍是资料库（不传 `library` 时不得悄悄变成案例库）。
    """
    _require_db()
    doc = tmp_path / "knowledge-regression.md"
    doc.write_text("# 虚构资料标题\n\n结构化活动的资料正文。\n", encoding="utf-8")
    settings, sync_engine, async_engine, store = _store()

    from campfire.modules.library.ingestion import ingest_file

    try:
        async with session_scope(settings) as session:
            await ingest_file(
                settings,
                session,
                vector_store=store,
                path=doc,
                title="虚构资料回归用例",
                source="虚构出处",
                applicable_scope="虚构范围",
                keywords="结构化活动",
            )

        async with session_scope(settings) as session:
            outcome = await search(session, store, "结构化活动", embed_query=_fake_embed_query)

        assert any(r.title == "虚构资料回归用例" for r in outcome.items), "默认库别应仍是资料库"
        assert all(r.library == "knowledge" for r in outcome.items)
        assert all(r.authorization is None for r in outcome.items), "资料侧不应出现案例专属字段"
    finally:
        async with session_scope(settings) as session:
            items = (
                (await session.execute(select(KnowledgeItem).where(KnowledgeItem.source_path == str(doc))))
                .scalars()
                .all()
            )
            for item in items:
                await session.execute(
                    RetrievedNode.__table__.delete().where(RetrievedNode.node_id.like(f"{item.id}:%"))
                )
                await session.delete(item)
        await async_engine.dispose()
        sync_engine.dispose()


def test_case_package_error_is_distinct_from_generic_package_error() -> None:
    """案例包的领域错误类型与 schema 错误区分开（调用方据此分别处置）。

    `CasePackageError` 是「包不合契约」（读文件阶段），`CaseIngestionError` 是
    「摄取失败」（含嵌入与写库）。混成一个类型会让调用方无法区分
    「这个包有问题」与「库写不进去」——前者要人改包，后者要重试。
    """
    assert issubclass(CaseIngestionError, Exception)
    assert not issubclass(CaseIngestionError, CasePackageError)
