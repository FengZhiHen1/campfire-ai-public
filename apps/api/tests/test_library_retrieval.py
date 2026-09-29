"""检索链的单元测试：RRF 融合、条目聚合、字面路闸门（纯函数，不连库）。

对应 RAG 策略第 4 节（融合与聚合）与第 3.1 节（中文约束）：
- RRF 只用名次、不做跨路分数加权归一化；
- 同一 item_id 的多个节点聚合为条目、只保留名次最高的节点作为 snippet；
- 同一轮不重复注入同一条目；
- 缺来源或状态的条目不进入结果（不补默认值）；
- <3 个连续汉字的查询不走字面路。
"""

from __future__ import annotations

import uuid

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from campfire.modules.library.models import KnowledgeItem
from campfire.modules.library.retrieval import (
    MIN_CJK_FOR_TRIGRAM,
    _reciprocal_rank_fuse,
    aggregate_to_items,
    literal_path_is_usable,
)


def _node(text: str, item_id: str, score: float) -> NodeWithScore:
    return NodeWithScore(
        node=TextNode(text=text, id_=f"{item_id}:0", metadata={"item_id": item_id}),
        score=score,
    )


def _item(item_id: str, **overrides: object) -> KnowledgeItem:
    item = KnowledgeItem(
        title=overrides.pop("title", "标题"),  # type: ignore[arg-type]
        source=overrides.pop("source", "出处"),  # type: ignore[arg-type]
        applicable_scope=overrides.pop("applicable_scope", "范围"),  # type: ignore[arg-type]
        status=overrides.pop("status", "published"),  # type: ignore[arg-type]
    )
    item.id = uuid.UUID(item_id)  # type: ignore[assignment]
    item.withdrawn = bool(overrides.pop("withdrawn", False))
    return item


# ---------------------------------------------------------------- 字面路闸门


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("孤独症", True),  # 3 个连续汉字：可用
        ("孤独症儿童", True),
        ("孤独症 autism", True),  # 含 3 字词元即可用
        ("干预", False),  # 2 字：退化
        ("症", False),  # 1 字
        ("autism", False),  # 无汉字
        ("", False),
        ("a b c", False),
    ],
)
def test_literal_path_gate_follows_min_cjk_rule(query: str, expected: bool) -> None:
    """字面路需 ≥3 个连续汉字，否则跳过该路（RAG 策略第 3.1 节）。"""
    assert literal_path_is_usable(query) is expected
    assert MIN_CJK_FOR_TRIGRAM == 3


# ---------------------------------------------------------------- RRF 融合


def test_fusion_merges_identical_content_across_paths() -> None:
    """两路命中同一内容时只算一条——框架按内容哈希合并，我们照搬。"""
    vector = [_node("孤独症儿童干预指南", "a", 0.9)]
    literal = [_node("孤独症儿童干预指南", "a", 1.0)]

    fused = _reciprocal_rank_fuse(vector, literal)

    assert len(fused) == 1, "同一内容在两路命中应合并为一条"


def test_fusion_uses_rank_not_raw_scores() -> None:
    """RRF 只用名次：一边的分数尺度不同不影响名次结果。"""
    vector = [_node("甲", "a", 0.01), _node("乙", "b", 0.009)]
    literal = [_node("乙", "b", 999.0), _node("甲", "a", 1.0)]

    fused = _reciprocal_rank_fuse(vector, literal)

    # 「乙」在向量路第 2、字面路第 1；「甲」在向量路第 1、字面路第 2——
    # 名次对称，因此两者分数相同（RRF 的对称性）。
    assert len(fused) == 2
    assert pytest.approx(fused[0].score, rel=1e-9) == fused[1].score


def test_fusion_ranks_items_hit_by_both_paths_first() -> None:
    """两路都命中的内容排在前（RRF 的核心收益）。"""
    both = _node("两路都命中", "a", 0.5)
    only_vector = _node("仅向量路", "b", 0.9)
    only_literal = _node("仅字面路", "c", 0.9)

    fused = _reciprocal_rank_fuse([both, only_vector], [both, only_literal])

    assert fused[0].node.text == "两路都命中"


def test_fusion_handles_one_empty_path() -> None:
    """单路为空时只按另一路排序（失败语义：降级而非失败）。"""
    vector = [_node("甲", "a", 1.0), _node("乙", "b", 0.5)]

    fused = _reciprocal_rank_fuse(vector, [])

    assert [n.node.text for n in fused] == ["甲", "乙"]


# ---------------------------------------------------------------- 条目聚合


def test_aggregation_keeps_best_node_per_item_and_dedupes() -> None:
    """同一 item_id 的多个节点聚合为一条，snippet 取名次最高的节点。"""
    item = _item("11111111-1111-1111-1111-111111111111")
    nodes = [
        _node("低分片段", item_ := str(item.id), 0.1),
        _node("高分片段", item_, 0.9),
        _node("另一个低分片段", item_, 0.2),
    ]

    results = aggregate_to_items(nodes, {item_: item})

    assert len(results) == 1, "同一轮不得重复注入同一条目"
    assert results[0].snippet == "高分片段"


def test_aggregation_excludes_items_missing_source_or_status() -> None:
    """缺来源或状态的条目不进入结果——不补默认值（不变量）。"""
    item_id = "22222222-2222-2222-2222-222222222222"
    no_source = _item(item_id)
    no_source.source = ""  # type: ignore[assignment]
    nodes = [_node("内容", item_id, 0.9)]

    results = aggregate_to_items(nodes, {item_id: no_source})

    assert results == []


def test_aggregation_excludes_withdrawn_items() -> None:
    """已撤下的条目不返回（`RQ-KB-04`）。"""
    item_id = "33333333-3333-3333-3333-333333333333"
    withdrawn = _item(item_id, withdrawn=True)
    nodes = [_node("内容", item_id, 0.9)]

    results = aggregate_to_items(nodes, {item_id: withdrawn})

    assert results == []


def test_aggregation_carries_return_contract_fields() -> None:
    """返回结果带齐返回契约需要的字段（来源、适用范围、状态、locator）。"""
    item_id = "44444444-4444-4444-4444-444444444444"
    item = _item(item_id, title="干预指南", source="WHO 2024", applicable_scope="学龄前")
    node = TextNode(text="片段", id_=f"{item_id}:0", metadata={"item_id": item_id, "locator": "/总则/"})

    results = aggregate_to_items([NodeWithScore(node=node, score=0.5)], {item_id: item})

    assert len(results) == 1
    got = results[0]
    assert got.library == "knowledge"
    assert got.title == "干预指南"
    assert got.source == "WHO 2024"
    assert got.applicable_scope == "学龄前"
    assert got.status == "published"
    assert got.locator == "/总则/"


def test_aggregation_respects_top_k() -> None:
    """返回条目数受 top_k 限制。"""
    items = {f"{i:08d}-0000-0000-0000-000000000000": _item(f"{i:08d}-0000-0000-0000-000000000000") for i in range(5)}
    nodes = [_node(f"内容{i}", f"{i:08d}-0000-0000-0000-000000000000", 1.0 - i * 0.1) for i in range(5)]

    results = aggregate_to_items(nodes, items, top_k=3)

    assert len(results) == 3
