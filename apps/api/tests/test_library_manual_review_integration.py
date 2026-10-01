"""人工处理队列的集成测试（真实 PostgreSQL）：复核件真的落库、按条目替换、随撤下清理。

D-82 的缺陷是「队列只存在于注释里」：判定确实生成了 `needs_manual_review` 与
`review_reason`，但除了 CLI 的一个计数之外没有任何落点——被拒绝嵌入的内容实际是被
静默丢弃的。本文件锁住新的落点（`campfire_manual_review`）的四件事：

1. 两条摄取路径（资料 / 案例）都把不可分块写成行，带 locator、原因与正文摘录；
2. 同一份文件重复摄取不堆行（幂等），把它修好之后重摄取会清掉旧行；
3. 撤下（CLI 用的同一个用例）连复核件一起清掉，已撤下条目重摄取不写回；
4. 落库与条目、节点同事务——写不进去就一起回滚，不留半份状态。

嵌入用确定性替身（本文件不验证供应商）；表、事务与 SQL 都是真实的。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select, text

from campfire.core.config import get_settings
from campfire.core.db import create_engine, create_sync_engine, session_scope
from campfire.modules.library.case_ingestion import NARRATIVE_SECTIONS, ingest_case_package
from campfire.modules.library.embedding import EMBEDDING_DIM
from campfire.modules.library.ingestion import build_vector_store, ingest_file
from campfire.modules.library.models import CaseItem, KnowledgeItem, RetrievedNode
from campfire.modules.library.withdrawal import withdraw_item

pytestmark = pytest.mark.integration


class _SimulatedFailure(Exception):
    """模拟「摄取之后、提交之前」的失败：验证复核件与摄取处在同一个事务里。"""


#: 一段无法二次切分的超长单元：单段、无标点，因此既没有段落边界也没有句子边界。
UNSPLITTABLE = "甲" * 2500

#: 不可分小节在源文件里的 locator（实测值）：框架给的 header_path 是父级路径，
#: `chunking._join_locator` 补上当前小节标题，因此它是「哪一节」的答案。
MANUAL_SECTION = "## 超长且不可分的小节"
MANUAL_LOCATOR = "/虚构指南/超长且不可分的小节/"

#: 不可分的原因（`chunking._split_oversized_paragraph` 给出的原文）。
MANUAL_REASON = "超长且找不到句子边界"


def _fake_vector(value: str) -> list[float]:
    seed = sum(ord(ch) for ch in value) % 97
    return [0.001 * ((i + seed) % 97 + 1) for i in range(EMBEDDING_DIM)]


class _FakeEmbedder:
    """替身嵌入器：只暴露流水线用到的那一个方法，形状与框架一致。"""

    async def aget_text_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        """按文本生成确定性假向量——不调用供应商，也不依赖 `TOKENHUB_API_KEY`。"""
        return [_fake_vector(t) for t in texts]


@pytest.fixture
def _patched_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 `build_embedding` 换成替身——流水线其余部分（含事务）保持真实。"""
    monkeypatch.setattr(
        "campfire.modules.library.ingestion.build_embedding",
        lambda _settings: _FakeEmbedder(),
    )


def _require_db() -> None:
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")


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


def _write_knowledge_doc(path: Path, *, unsplittable: bool, filler: str = "甲") -> None:
    """写一份资料 Markdown：一个正常小节 + 一个按需做成不可分单元的小节。

    `unsplittable=False` 时第二个小节是可切分的短文本——用来验证「把它修好之后再
    摄取一次，队列里的旧行会被清掉」。`filler` 换一个字符就能改掉文件哈希而保持
    「仍然不可分」，用于验证已撤下条目的重摄取路径。
    """
    body = filler * 2500 if unsplittable else "这一节已经可以正常切分了。"
    path.write_text(
        f"# 虚构指南\n\n## 正常小节\n\n这是一个可以正常嵌入的短段落。\n\n{MANUAL_SECTION}\n\n{body}\n",
        encoding="utf-8",
    )


def _card() -> dict[str, object]:
    """一张通过值域校验的虚构卡片（字段形状照公共案例库第 3 节）。"""
    return {
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


def build_case_package(root: Path, *, slug: str) -> Path:
    """造一个虚构案例包：五节叙事里只有 `场景背景` 是不可分单元。"""
    package = root / slug
    package.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, object] = {
        "external_key": f"2099-01-01_0000_{slug}",
        "title": "虚构案例：人工处理队列",
        "source_type": "专家访谈转写",
        "subject_type": "家长",
        "interview_at": "2099-01-01T00:00:00+08:00",
        "consent_scope": "ai_retrieval_and_advice",
        "consent_recorded_at": "2099-01-01",
        "evidence_level": "INSTITUTIONAL",
        "review_status": "owner",
        "reviewer": None,
        "authorization": "虚构样例（无真实来源）",
        "transcript_ref": "（虚构，无上游转写稿）",
        "keywords": "虚构关键词",
        "aliases": "",
        "status": "internal",
        "files": {"narrative": "L1_x.md", "cards": ["L2_x_01.json"]},
    }
    (package / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    sections = []
    for name in NARRATIVE_SECTIONS:
        body = UNSPLITTABLE if name == "场景背景" else f"虚构的{name}段落。"
        sections.append(f"## {name}\n\n{body}")
    (package / "L1_x.md").write_text("# 虚构案例\n\n" + "\n\n".join(sections) + "\n", encoding="utf-8")
    (package / "L2_x_01.json").write_text(json.dumps(_card(), ensure_ascii=False), encoding="utf-8")
    return package


async def _review_rows(source_path: str) -> list[dict[str, object]]:
    """该来源路径下的复核件行（按 locator 排序，便于断言）。"""
    async with session_scope(get_settings()) as session:
        rows = (
            await session.execute(
                text(
                    "select library, item_id, source_path, locator, excerpt, review_reason, created_at"
                    " from campfire_manual_review where source_path = :p order by locator"
                ),
                {"p": source_path},
            )
        ).mappings()
        return [dict(row) for row in rows]


async def _cleanup(source_path: str) -> None:
    """清掉本次用例写入的条目、节点与复核件（表结构保留）。"""
    async with session_scope(get_settings()) as session:
        await session.execute(text("delete from campfire_manual_review where source_path = :p"), {"p": source_path})
        for model in (KnowledgeItem, CaseItem):
            items = (await session.execute(select(model).where(model.source_path == source_path))).scalars().all()
            for item in items:
                await session.execute(
                    RetrievedNode.__table__.delete().where(RetrievedNode.node_id.like(f"{item.id}:%"))
                )
                await session.delete(item)


@pytest.mark.asyncio
async def test_knowledge_ingest_records_the_manual_review_rows(tmp_path: Path, _patched_embedding: None) -> None:
    """资料侧：不可分块落成复核件，带 locator、原因与正文摘录。

    判别性：去掉 `ingest_file` 里的 `record_manual_reviews` 调用，本用例失败
    （表里一行都没有）——这正是 D-82 的回归守卫。
    """
    _require_db()
    doc = tmp_path / "guide.md"
    _write_knowledge_doc(doc, unsplittable=True)
    source_path = str(doc)
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            result = await ingest_file(
                settings,
                session,
                vector_store=store,
                path=doc,
                source="集成测试出处",
                applicable_scope="学龄前儿童",
            )

        assert result.needs_manual_review == 1
        assert result.chunks_written == 2, "只有可嵌入的两个小节写节点"

        rows = await _review_rows(source_path)
        assert len(rows) == 1, f"应有且只有一行复核件：{rows}"
        row = rows[0]
        assert row["library"] == "knowledge"
        assert str(row["item_id"]) == result.item_id
        assert row["locator"] == MANUAL_LOCATOR
        assert row["review_reason"] == MANUAL_REASON
        assert str(row["excerpt"]).startswith(f"{MANUAL_LOCATOR}\n"), "摘录以章节路径开头，复核人据此定位"
        assert "甲" * 200 in str(row["excerpt"]), "摘录必须带上该块的实际正文"
        assert "原文共" in str(row["excerpt"]), "摘录截断必须留痕，否则复核人会把它当成全部内容"
        assert row["created_at"] is not None

        # 该条目的节点只有可嵌入块：不可分块的正文只出现在复核件里，不落节点表。
        async with session_scope(settings) as session:
            node_count = (
                await session.execute(
                    text("select count(*) from data_campfire_node where metadata_->>'item_id' = :i"),
                    {"i": result.item_id},
                )
            ).scalar_one()
        assert int(node_count) == 2
    finally:
        await _cleanup(source_path)
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_reingesting_an_unchanged_file_does_not_pile_up_rows(tmp_path: Path, _patched_embedding: None) -> None:
    """同一份文件重复摄取：幂等跳过，复核件不堆积（内容未变 ⟹ 同一批不可分块）。"""
    _require_db()
    doc = tmp_path / "same.md"
    _write_knowledge_doc(doc, unsplittable=True)
    source_path = str(doc)
    settings, sync_engine, async_engine, store = _store()

    try:
        for _ in range(2):
            async with session_scope(settings) as session:
                result = await ingest_file(
                    settings, session, vector_store=store, path=doc, source="出处", applicable_scope="范围"
                )

        assert result.skipped is True, "内容未变的第二次摄取应被跳过"
        assert len(await _review_rows(source_path)) == 1, "复核件被重复堆积——队列变成了历史账本"
    finally:
        await _cleanup(source_path)
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_fixing_the_file_clears_its_rows(tmp_path: Path, _patched_embedding: None) -> None:
    """把源文件修好再摄取：旧复核件被清掉，而不是留在队列里让人去修一个已不存在的问题。

    判别性：把 `ingest_file` 里的 `delete_manual_reviews` 删掉，本用例失败（旧行还在）。
    """
    _require_db()
    doc = tmp_path / "fixed.md"
    _write_knowledge_doc(doc, unsplittable=True)
    source_path = str(doc)
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            await ingest_file(settings, session, vector_store=store, path=doc, source="出处", applicable_scope="范围")
        assert len(await _review_rows(source_path)) == 1

        _write_knowledge_doc(doc, unsplittable=False)
        async with session_scope(settings) as session:
            second = await ingest_file(
                settings, session, vector_store=store, path=doc, source="出处", applicable_scope="范围"
            )

        assert second.skipped is False, "内容变了就不该跳过"
        assert second.needs_manual_review == 0
        assert await _review_rows(source_path) == [], "修好之后旧复核件必须消失"
    finally:
        await _cleanup(source_path)
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_withdrawal_clears_the_rows(tmp_path: Path, _patched_embedding: None) -> None:
    """撤下：复核件随检索节点一起清掉——条目已撤下，待处理的正文不留在库里。"""
    _require_db()
    doc = tmp_path / "withdrawn.md"
    _write_knowledge_doc(doc, unsplittable=True)
    source_path = str(doc)
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            result = await ingest_file(
                settings, session, vector_store=store, path=doc, source="出处", applicable_scope="范围"
            )
        assert len(await _review_rows(source_path)) == 1

        async with session_scope(settings) as session:
            withdrawal = await withdraw_item(session, library="knowledge", item_id=result.item_id, reason="上游撤回")

        assert withdrawal.nodes_deleted > 0
        assert withdrawal.manual_reviews_deleted == 1
        assert await _review_rows(source_path) == []
    finally:
        await _cleanup(source_path)
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_reingesting_a_withdrawn_item_writes_no_rows_back(tmp_path: Path, _patched_embedding: None) -> None:
    """已撤下条目重新交付（哈希变了、内容仍不可分）：不重建节点，也不写回复核件。"""
    _require_db()
    doc = tmp_path / "withdrawn-reingest.md"
    _write_knowledge_doc(doc, unsplittable=True)
    source_path = str(doc)
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            first = await ingest_file(
                settings, session, vector_store=store, path=doc, source="出处", applicable_scope="范围"
            )
        async with session_scope(settings) as session:
            await withdraw_item(session, library="knowledge", item_id=first.item_id)
        assert await _review_rows(source_path) == []

        _write_knowledge_doc(doc, unsplittable=True, filler="乙")
        async with session_scope(settings) as session:
            second = await ingest_file(
                settings, session, vector_store=store, path=doc, source="出处", applicable_scope="范围"
            )

        assert second.skipped is False
        assert second.chunks_written == 0, "已撤下条目不重建节点"
        assert second.needs_manual_review == 0
        assert await _review_rows(source_path) == [], "已撤下条目不该把正文摘录重新写进队列"
    finally:
        await _cleanup(source_path)
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_case_ingest_records_the_manual_review_rows(tmp_path: Path, _patched_embedding: None) -> None:
    """案例侧：叙事里的不可分小节同样落成复核件，库别是 `case`、locator 是那一节。"""
    _require_db()
    package = build_case_package(tmp_path, slug="manual-review-case")
    source_path = str(package)
    settings, sync_engine, async_engine, store = _store()

    try:
        async with session_scope(settings) as session:
            result = await ingest_case_package(settings, session, vector_store=store, package_dir=package)

        assert result.needs_manual_review == 1
        assert result.cards_written == 1
        assert result.narrative_nodes == len(NARRATIVE_SECTIONS) - 1

        rows = await _review_rows(source_path)
        assert len(rows) == 1, f"应有且只有一行复核件：{rows}"
        row = rows[0]
        assert row["library"] == "case"
        assert str(row["item_id"]) == result.item_id
        assert row["locator"] == "/场景背景/"
        assert row["review_reason"] == MANUAL_REASON
        assert str(row["excerpt"]).startswith("/场景背景/\n甲")
        assert "原文共" in str(row["excerpt"])
    finally:
        await _cleanup(source_path)
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_a_rolled_back_ingest_leaves_no_rows(tmp_path: Path, _patched_embedding: None) -> None:
    """摄取所在事务回滚时，复核件一行都不留——它与条目、节点同事务。

    判别性：若写复核件走自己的会话或自己的提交点，本用例失败（回滚后行还在）。
    那种半份状态就是「条目没入库、队列里却留着它的正文摘录」。
    """
    _require_db()
    doc = tmp_path / "rollback.md"
    _write_knowledge_doc(doc, unsplittable=True)
    source_path = str(doc)
    settings, sync_engine, async_engine, store = _store()

    try:
        with pytest.raises(_SimulatedFailure):
            async with session_scope(settings) as session:
                result = await ingest_file(
                    settings, session, vector_store=store, path=doc, source="出处", applicable_scope="范围"
                )
                assert result.needs_manual_review == 1, "本用例需要在回滚前确实写入了复核件"
                raise _SimulatedFailure

        assert await _review_rows(source_path) == [], "回滚后复核件仍在——它没有与摄取同事务"
    finally:
        await _cleanup(source_path)
        await async_engine.dispose()
        sync_engine.dispose()
