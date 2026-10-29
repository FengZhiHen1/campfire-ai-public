"""字面路必须有相关度名次（审查修正 2026-10-29）：`ORDER BY id` 让 top-K 与名次都失效。

`id` 是 `uuid4`，随机的，所以旧写法有两个真实后果：① 命中条目多于 `LITERAL_TOP_K` 时，
「留下哪 30 条」由随机 UUID 决定；② 候选内喂给 RRF 的名次也是 UUID 序，而 RRF 只吃名次
（RAG 策略第 4 节）——字面路的名次信息整个失效。此外同一份语料在新库重建（UUID 全新）后，
同一查询的候选集会变，「同一快照 → 同一检索行为」这条评测前提被破坏。

现在的判据是 `GREATEST(相似度)`（`retrieval._literal_ranking_sql`），词元只经绑定参数进 SQL。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete

from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.modules.library.models import KnowledgeItem
from campfire.modules.library.retrieval import MAX_RANKING_TERMS, _literal_ranking_sql, literal_search

#: 只在字面路用例里出现的词（≥3 连续汉字才走字面路），把测试数据与库里其他条目隔开。
_RARE_TERM = "谐波校准仪"


def test_literal_ranking_uses_similarity_with_bound_parameters() -> None:
    """排序表达式 = 各词元 × 各列的 `similarity`，词元只出现在绑定参数里（注入判据）。

    判别性：把词元格式化进 SQL 文本，本用例失败；改回 `ORDER BY id`，集成用例失败。
    """
    fragment, params = _literal_ranking_sql([_RARE_TERM, "干预"])

    assert fragment.startswith("GREATEST("), fragment
    for column in ("title", "keywords", "aliases"):
        assert f"similarity({column}, :s0)" in fragment
        assert f"similarity({column}, :s1)" in fragment
    assert params == {"s0": _RARE_TERM, "s1": "干预"}
    assert _RARE_TERM not in fragment, "词元不得拼进 SQL 片段（模型可控值）"
    assert "干预" not in fragment


def test_literal_ranking_caps_the_number_of_terms() -> None:
    """排序最多用 `MAX_RANKING_TERMS` 个词元（成本上界）；匹配范围不受影响。"""
    terms = [f"词元{i}" for i in range(MAX_RANKING_TERMS + 5)]

    fragment, params = _literal_ranking_sql(terms)

    assert len(params) == MAX_RANKING_TERMS
    assert f":s{MAX_RANKING_TERMS - 1}" in fragment
    assert f":s{MAX_RANKING_TERMS}" not in fragment
    assert params["s0"] == terms[0]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_literal_path_ranks_by_similarity_not_uuid() -> None:
    """字面路第 0 名必须是**最相似**的条目，而不是 UUID 最小的那条。

    数据为「旧实现确定性失败」而构造：三条都命中同一个罕见词、相似度不同，且最相似的
    那条被显式给了**最大 UUID**——旧实现 `ORDER BY id` 会把它排到最后。
    """
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    settings = get_settings()
    stamp = uuid.uuid4().hex[:8]
    exact_id = uuid.UUID(f"{'f' * 8}-0000-4000-8000-000000000001")
    weak_id = uuid.UUID(f"{'0' * 8}-0000-4000-8000-000000000002")
    mid_id = uuid.UUID(f"{'5' * 5}000-0000-4000-8000-000000000003")
    keywords = {
        exact_id: _RARE_TERM,
        mid_id: f"{_RARE_TERM} 相关条目 说明文本 补充信息",
        weak_id: f"与 {_RARE_TERM} 有关但不直接命中的一长串描述性关键词集合，相似度因此更低",
    }

    async with session_scope(settings) as session:
        for item_id, value in keywords.items():
            session.add(
                KnowledgeItem(
                    id=item_id,
                    title=f"审查用例 {stamp}",
                    source="审查用例",
                    applicable_scope="测试",
                    keywords=value,
                    aliases="",
                    source_path=f"audit-literal/{stamp}/{item_id}.md",
                    doc_hash="0" * 64,
                )
            )

    try:
        async with session_scope(settings) as session:
            hits = await literal_search(session, _RARE_TERM, top_k=10)
        ordered = [item_id for item_id, _rank in hits]
        assert ordered, "字面路应命中刚写入的三条"
        assert ordered[0] == str(exact_id), f"最相似的条目必须排在第一位，实际 {ordered}"
        assert [rank for _item_id, rank in hits] == list(range(len(hits))), "名次必须是 0..n-1"
    finally:
        async with session_scope(settings) as session:
            await session.execute(
                delete(KnowledgeItem).where(KnowledgeItem.source_path.like(f"audit-literal/{stamp}/%"))
            )
