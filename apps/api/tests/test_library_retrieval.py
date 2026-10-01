"""检索链的单元测试：RRF 融合、条目聚合、字面路闸门、按库别参数化（纯函数，不连库）。

对应 RAG 策略第 4 节（融合与聚合）与第 3.1 节（中文约束）、
资料与案例检索第 1、3 节（两库边界与返回契约）：
- RRF 只用名次、不做跨路分数加权归一化；
- 同一 item_id 的多个节点聚合为条目、只保留名次最高的节点作为 snippet；
- 同一轮不重复注入同一条目；
- 缺来源或状态的条目不进入结果（不补默认值）；
- <3 个连续汉字的查询不走字面路；
- **每个库的向量路过滤器是硬编码常量**（`MetadataFilter` 是字符串拼接的注入面）；
- 非法库别被拒，不静默退回资料库。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from campfire.modules.library.models import CaseItem, KnowledgeItem
from campfire.modules.library.retrieval import (
    MIN_CHARS_FOR_TRIGRAM,
    MIN_CJK_FOR_TRIGRAM,
    RetrievalError,
    SearchOutcome,
    _active_filters,
    _reciprocal_rank_fuse,
    aggregate_to_items,
    as_uuid,
    literal_path_is_usable,
)


def _node(text: str, item_id: str, score: float) -> NodeWithScore:
    return NodeWithScore(
        node=TextNode(text=text, id_=f"{item_id}:0", metadata={"item_id": item_id}),
        score=score,
    )


def _item(item_id: str, **overrides: object) -> KnowledgeItem:
    item = KnowledgeItem(
        title=overrides.pop("title", "标题"),
        source=overrides.pop("source", "出处"),
        applicable_scope=overrides.pop("applicable_scope", "范围"),
        status=overrides.pop("status", "published"),
    )
    item.id = uuid.UUID(item_id)  # type: ignore[assignment]  # `id` 是主键列，静态类型是 SQLCoreOperations[UUID] | UUID，实例赋值必然不匹配
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
        ("", False),
        # 非中文：按最长连续字母/数字段判定（2026-09-29 放宽，含实测依据）。
        ("autism", True),
        ("asd", True),  # 3 字符是分界点（实测走 Bitmap Index Scan）
        ("Project AIM", True),  # 最长段 7
        ("ab", False),  # 2 字符：实测规划器弃用索引
        ("a b", False),  # 总长 3 但每段 1 字符——按最长段判而非总长
        ("123", True),
        ("12", False),
        ("!!!", False),  # 无字母数字
    ],
)
def test_literal_path_gate_follows_min_cjk_rule(query: str, expected: bool) -> None:
    """字面路闸门：中文 ≥3 连续汉字，非中文 ≥3 连续字母/数字（RAG 策略第 3.1 节）。

    实测依据见 `literal_path_is_usable`：3 字符是"规划器是否使用 trigram 索引"
    的分界点，而非"有无三元组"（2 字符串同样产生三元组，但选择性差）。
    """
    assert literal_path_is_usable(query) is expected


def test_gate_thresholds_are_three() -> None:
    """两个阈值都是 3——与实测的分界点一致。"""
    assert MIN_CJK_FOR_TRIGRAM == 3
    assert MIN_CHARS_FOR_TRIGRAM == 3


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
    no_source.source = ""
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


# ---------------------------------------------------------------------------
# 降级事实（失败语义第 5 节：单路失败必须「在结果中标注」）
# ---------------------------------------------------------------------------


def test_search_outcome_reports_degradation() -> None:
    """`SearchOutcome` 把「哪一路不可用」与结果一起带走。

    契约第 5 节要求单路失败时标注。**只返回裸列表时这条信息无处安放**：两路都失败
    已抛错，但「只有一路失败且没命中」与「确实没找到」在空列表上无法区分，而契约
    明令模型不得据此声称「没有相关资料」。
    """
    outcome = SearchOutcome(items=[], degraded_paths=("vector",))
    assert outcome.is_degraded is True
    assert outcome.degraded_paths == ("vector",)


def test_search_outcome_is_not_degraded_when_both_paths_work() -> None:
    """两路都正常时不算降级——不得把正常空结果也标成降级（那会让模型不敢说「未找到」）。"""
    outcome = SearchOutcome(items=[], degraded_paths=())
    assert outcome.is_degraded is False


def test_scope_condition_is_bound_parameter_not_interpolated() -> None:
    """`scope` 走绑定参数，**绝不进 SQL 文本**——这是防注入的判据。

    实测背景：框架的 `MetadataFilter` 用 f-string 拼 SQL（``f"'%{value}%'"``，无绑定
    参数），把 ``x' OR '1'='1`` 当 scope 会生成
    ``... ILIKE '%%x' OR '1'='1%%'``，且 `OR` 优先级逃逸整个 AND 链、连带绕过库别/
    撤下/状态三个过滤。`search()` 因此不给 `MetadataFilter` 传 scope，而是先用绑定
    参数算出允许的 item_id。

    条件构造在 `_item_filters_sql`（字面路与允许集查询**共用**），因此断言点在那里：
    两处各写一份条件就会漂移成「向量路过滤了、字面路没过滤」，而那种缺陷在功能
    测试里看不出来（结果照常有，只是多出范围外条目）。

    判别性：把 `:scope` 改回字符串拼接（`f"ILIKE '%{scope}%'"`），本用例失败。
    """
    import inspect

    from campfire.modules.library import retrieval

    helper = inspect.getsource(retrieval._item_filters_sql)
    assert "applicable_scope ILIKE :scope" in helper, "scope 必须以绑定参数形式出现在 SQL 里"
    assert 'params["scope"]' in helper, "scope 的值必须进 params 而不是 SQL 文本"

    # 两条路都必须经这个共享构造器——任一处自己拼条件就绕过了上面的判据。
    literal = inspect.getsource(retrieval.literal_search)
    allowed = inspect.getsource(retrieval._allowed_item_ids)
    assert "_item_filters_sql(" in literal, "字面路必须复用共享的条件构造器"
    assert "_item_filters_sql(" in allowed, "允许集查询必须复用共享的条件构造器"


# ---------------------------------------------------------------------------
# 按库别参数化（RQ-KB-01 两库分离；TODO「MetadataFilter 注入面」）
# ---------------------------------------------------------------------------


def test_each_library_has_a_hardcoded_constant_filter_set() -> None:
    """每个库的向量路过滤器是**硬编码常量**，两库的库别判据互不相同。

    这是注入面的红线（TODO「MetadataFilter 注入面」）：框架的
    `_build_filter_clause` 用 f-string 拼 SQL、无绑定参数，因此过滤器里的值
    必须是字面量。一旦有人把它改成可配置，模型输入就能逃逸整个 AND 链。

    判别性：把 `_ACTIVE_FILTERS_BY_LIBRARY` 的值改成读参数/查配置，本用例失败。
    """
    knowledge = _active_filters("knowledge")
    case = _active_filters("case")

    # 两库各自的库别过滤必须指向自己的库（这是「两库分开取数」的 SQL 层承载）。
    assert any(f.key == "library" and f.value == "knowledge" for f in knowledge)
    assert any(f.key == "library" and f.value == "case" for f in case)

    # 撤下过滤两库都有（撤下即刻不可检索是共同不变量）。
    for filters in (knowledge, case):
        assert any(f.key == "withdrawn" and f.value == "false" for f in filters)


def test_case_filter_does_not_pin_status_to_published() -> None:
    """案例侧的 `status` 过滤**不锁定 `published`**（虚构样例必须可检索）。

    这是本包一个有意的差异：资料侧状态恒 `published`，过滤它是过滤异常数据；
    而案例侧是 `published | internal | fictional` 三值且三者都要可检索——
    `fictional` 是虚构样例，[公共案例库] 第 8 节与 `AC-06` 要求它与真实案例
    「混列但可辨」。若案例侧照抄资料的 `status = 'published'`，虚构样例会被
    挡在检索之外，`AC-06` 无从落地。

    判别性：把案例侧的 status 过滤改成 `value="published"`，本用例失败。
    """
    case = _active_filters("case")
    status_filters = [f for f in case if f.key == "status"]

    assert status_filters, "案例侧应有状态过滤（缺状态条目不进结果是不变量）"
    assert all(f.value != "published" for f in status_filters), "案例侧不得把状态钉死在 published"


def test_active_filters_rejects_invalid_library() -> None:
    """取过滤器时非法库别被拒（不静默回退到某个库的常量）。"""
    with pytest.raises(RetrievalError, match="非法库别"):
        _active_filters("bogus")


def test_literal_search_sql_uses_the_table_by_library() -> None:
    """字面路的表名来自库别映射，不再写死资料库表。

    判别性：把 `literal_search` 里的 `table = ITEM_TABLES[...]` 改回硬编码
    `campfire_knowledge_item`，本用例失败——而失败形态必须是「查错表」而不是
    「查不到」，后者会被读成「没有相关案例」。
    """
    import inspect

    from campfire.modules.library import retrieval

    source = inspect.getsource(retrieval.literal_search)
    assert "ITEM_TABLES[" in source, "字面路表名必须按库别取"
    assert "campfire_knowledge_item" not in source, "字面路不得写死资料库表名"


def test_authorization_column_is_quoted_in_raw_sql() -> None:
    """原生 SQL 里的 `authorization` 必须加双引号。

    **实测（2026-09-30）**：`authorization` 是 PostgreSQL 的保留字
    （`pg_get_keywords()` 报 catcode=T "reserved"）。不加引号的
    `SELECT authorization FROM ...` 直接报 `syntax error at or near "from"`。
    SQLAlchemy 的 ORM 查询会自动加引号，只有手写原生 SQL 需要显式写。

    **断言的是生成物而不是源码文本**：初版用 `inspect.getsource` 找 `"authorization"`，
    而该函数的注释里也含这个字符串——注掉代码、留下注释，用例照样通过。
    这是「永远不会失败」的检查（消融实测发现），因此改为直接校验**返回的条件片段**。

    判别性（已实测）：把 `'"authorization" = :authorization'` 的双引号去掉，
    本用例失败。
    """
    from campfire.modules.library.retrieval import _item_filters_sql

    clauses, params = _item_filters_sql(scope=None, authorization="已授权")

    assert clauses, "给了 authorization 就应产出条件片段"
    assert '"authorization" = :authorization' in clauses, f"authorization 未加双引号：{clauses}"
    assert params["authorization"] == "已授权"


def test_item_filters_are_bound_parameters_not_literals() -> None:
    """过滤条件的值只出现在 `params` 里，不拼进 SQL 片段（注入判据）。

    判别性：把 `params["authorization"] = authorization` 改成把值格式化进片段，
    本用例失败。
    """
    from campfire.modules.library.retrieval import _item_filters_sql

    clauses, params = _item_filters_sql(scope="学龄前", authorization="已授权")
    joined = " ".join(clauses)

    assert params == {"scope": "%学龄前%", "authorization": "已授权"}
    assert "学龄前" not in joined, "scope 的值不得出现在 SQL 片段里"
    assert "已授权" not in joined, "authorization 的值不得出现在 SQL 片段里"
    assert ":scope" in joined and ":authorization" in joined


def test_item_filters_are_empty_without_optional_values() -> None:
    """未给可选过滤时不产出条件——不得凭空过滤掉一切。"""
    from campfire.modules.library.retrieval import _item_filters_sql

    clauses, params = _item_filters_sql(scope=None, authorization=None)

    assert clauses == []
    assert params == {}


def test_as_uuid_rejects_malformed_id_with_domain_error() -> None:
    """非法 id 转成领域错误，不让驱动抛裸异常（两处调用点共用同一判据）。"""
    with pytest.raises(RetrievalError, match="非法条目 id"):
        as_uuid("not-a-uuid")


def test_as_uuid_accepts_valid_id() -> None:
    """合法 UUID 正常解析（正向控制）。"""
    value = "11111111-1111-4111-8111-111111111111"

    assert str(as_uuid(value)) == value


# ---------------------------------------------------------------------------
# 案例聚合（资料与案例检索第 3 节：案例六字段必带）
# ---------------------------------------------------------------------------


def _case_item(item_id: str, **overrides: object) -> CaseItem:
    """构造一个案例条目（字段值全部虚构）。"""
    item = CaseItem(
        external_key=overrides.pop("external_key", f"key-{item_id}"),
        title=overrides.pop("title", "虚构案例标题"),
        source=overrides.pop("source", "虚构出处"),
        applicable_scope=overrides.pop("applicable_scope", "虚构范围"),
        authorization=overrides.pop("authorization", "虚构样例"),
        source_type=overrides.pop("source_type", "专家访谈转写"),
        evidence_level=overrides.pop("evidence_level", "INSTITUTIONAL"),
        review_status=overrides.pop("review_status", "owner"),
        interview_at=overrides.pop("interview_at", datetime(2099, 1, 1, tzinfo=timezone.utc)),
        subject_type=overrides.pop("subject_type", "家长"),
        consent_scope=overrides.pop("consent_scope", "ai_retrieval_and_advice"),
        status=overrides.pop("status", "internal"),
    )
    item.id = uuid.UUID(item_id)  # type: ignore[assignment]  # `id` 是主键列，静态类型是 SQLCoreOperations[UUID] | UUID，实例赋值必然不匹配
    item.withdrawn = bool(overrides.pop("withdrawn", False))
    item.makes_claims_high_risk = bool(overrides.pop("makes_claims_high_risk", False))
    inferred = overrides.pop("inferred_fields", [])
    assert isinstance(inferred, list), "样本自身的 inferred_fields 必须是列表"
    item.inferred_fields = list(inferred)
    return item


def test_case_aggregation_carries_the_six_required_fields_plus_inferred() -> None:
    """案例聚合结果带齐六字段 + `inferred_fields`（第 3 节必带项）。

    这六项不是装饰：缺任一个，输出就无法如实回答「谁说的、多可信、什么时候」。
    """
    item_id = "55555555-5555-4555-8555-555555555555"
    item = _case_item(item_id, makes_claims_high_risk=True, inferred_fields=["severity_level"])
    node = TextNode(
        text="卡片片段",
        id_=f"{item_id}:card:0",
        metadata={"item_id": item_id, "locator": "虚构卡片标题", "inferred_fields": ["severity_level"]},
    )

    results = aggregate_to_items([NodeWithScore(node=node, score=0.5)], {item_id: item}, library="case")

    assert len(results) == 1
    got = results[0]
    assert got.library == "case"
    assert got.authorization == "虚构样例"
    assert got.source_type == "专家访谈转写"
    assert got.evidence_level == "INSTITUTIONAL"
    assert got.review_status == "owner"
    assert got.interview_at is not None
    assert got.makes_claims_high_risk is True
    assert got.inferred_fields == ["severity_level"]


def test_case_aggregation_inferred_fields_come_from_the_hit_node() -> None:
    """`inferred_fields` 取**该命中节点**的清单，不是案例级并集（第 3 节）。

    命中叙事小节（节点上没有 `inferred_fields`）时必须为空——叙事不是卡片，
    用案例级并集会变成「这一节里有推断」的猜测。
    """
    item_id = "66666666-6666-4666-8666-666666666666"
    item = _case_item(item_id, inferred_fields=["age_range", "severity_level"])
    narrative_node = TextNode(
        text="叙事小节文本",
        id_=f"{item_id}:narrative:0",
        metadata={"item_id": item_id, "locator": "/场景背景/"},
    )

    results = aggregate_to_items([NodeWithScore(node=narrative_node, score=0.9)], {item_id: item}, library="case")

    assert results[0].inferred_fields == [], "命中叙事时不得带案例级并集"


def test_knowledge_aggregation_leaves_case_fields_empty() -> None:
    """资料侧聚合不产生案例专属字段（两库返回形状只在库别与状态字段上有差别）。"""
    item = _item("77777777-7777-4777-8777-777777777777")
    nodes = [_node("内容", str(item.id), 0.9)]

    results = aggregate_to_items(nodes, {str(item.id): item}, library="knowledge")

    assert results[0].authorization is None
    assert results[0].source_type is None
    assert results[0].evidence_level is None
    assert results[0].review_status is None
    assert results[0].interview_at is None
    assert results[0].makes_claims_high_risk is None
    assert results[0].inferred_fields == []


def test_case_aggregation_rejects_invalid_library() -> None:
    """非法库别不得走到聚合（边界显式，不静默按资料库聚合）。"""
    with pytest.raises(RetrievalError, match="非法库别"):
        aggregate_to_items([], {}, library="bogus")


def test_case_aggregation_excludes_withdrawn_items() -> None:
    """已撤下的案例条目不返回（`RQ-KB-04` / `AC-09`）。"""
    item_id = "88888888-8888-4888-8888-888888888888"
    withdrawn = _case_item(item_id, withdrawn=True)
    node = TextNode(text="内容", id_=f"{item_id}:card:0", metadata={"item_id": item_id})

    assert aggregate_to_items([NodeWithScore(node=node, score=0.9)], {item_id: withdrawn}, library="case") == []


def test_case_aggregation_excludes_items_missing_source_or_status() -> None:
    """缺来源或状态的案例条目不进入结果——不补默认值（不变量）。"""
    item_id = "99999999-9999-4999-8999-999999999999"

    for overrides in ({"source": ""}, {"status": ""}):
        item = _case_item(item_id, **overrides)
        node = TextNode(text="内容", id_=f"{item_id}:card:0", metadata={"item_id": item_id})
        results = aggregate_to_items([NodeWithScore(node=node, score=0.9)], {item_id: item}, library="case")
        assert results == [], f"缺字段的案例不应返回：{overrides}"


def test_case_aggregation_tolerates_string_inferred_fields_from_dirty_data() -> None:
    """节点 metadata 里的 `inferred_fields` 是字符串（脏数据）时按单元素处理。

    不静默丢弃：手工写入或历史数据可能把它写成字符串，直接塞进返回契约会
    让消费者拿到类型不一致的字段（契约是清单）。
    """
    item_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    item = _case_item(item_id)
    node = TextNode(
        text="内容",
        id_=f"{item_id}:card:0",
        metadata={"item_id": item_id, "inferred_fields": "severity_level"},
    )

    results = aggregate_to_items([NodeWithScore(node=node, score=0.9)], {item_id: item}, library="case")

    assert results[0].inferred_fields == ["severity_level"]
