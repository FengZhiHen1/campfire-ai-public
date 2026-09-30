"""案例入库契约的单元测试：manifest 校验、卡片值域、推断字段与嵌入文本（不连库）。

对应 [公共案例库] 第 3、4、6、7 节与 [RAG 策略] 第 1.3 节：

- manifest **缺字段即整包拒绝**（第 6 节），且错误信息要指出缺的是哪个字段；
- 卡片值域越界必须被拒（第 4 节「值域不重写」：沿用上游 `validate_l2.py` 的约束）；
- `review_status` 三档与「具名审阅者只在 professional 档」的判据（第 7 节）；
- `inferred_fields` 由 `_inferred` 的键推出（第 4 节）；
- 卡片嵌入文本**不含** `_inferred` 与标识字段（第 1.3 节）。

**不连库**：这些是纯函数，落库行为由 `test_library_case_integration.py` 覆盖。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from campfire.modules.library.case_schema import (
    BEHAVIOR_TYPES,
    PARENT_CATEGORIES,
    SETTINGS,
    SEVERITY_LEVELS,
    VALID_EBP_TAGS,
    CasePackageError,
    build_card_embedding_text,
    inferred_field_names,
    load_manifest,
    parse_interview_at,
    validate_card,
)


def _valid_card(**overrides: object) -> dict[str, object]:
    """一张合法卡片（形状取自上游 L2 的真实结构，值全部虚构）。"""
    card: dict[str, object] = {
        "card_id": "{AWAITING_SYSTEM}",
        "raw_id": "{AWAITING_SYSTEM}",
        "title": "虚构卡片标题",
        "scenario": "虚构场景描述。",
        "behavior_type": "其他",
        "age_range": ["3", "6"],
        "severity_level": "轻",
        "setting": "家庭",
        "ebp_tags": ["视觉支持(VS)"],
        "parent_category": "环境调整",
        "immediate_action": "1. 动作一。",
        "comforting_phrase": "慢慢来。",
        "observation_metrics": "记录 1 周内的次数。",
        "medical_criteria": "出现自伤即就医。",
        "evidence_level": "INSTITUTIONAL",
        "caution_notes": "注意一。",
        "contraindications": "无",
        "is_template": False,
        "_inferred": {"severity_level": "虚构推断理由"},
    }
    card.update(overrides)
    return card


def _valid_manifest(**overrides: object) -> dict[str, object]:
    manifest: dict[str, object] = {
        "external_key": "2099-01-01_0000_fictional",
        "title": "虚构案例标题",
        "source_type": "专家访谈转写",
        "subject_type": "家长",
        "interview_at": "2099-01-01T00:00:00+08:00",
        "consent_scope": "ai_retrieval_and_advice",
        "consent_recorded_at": "2099-01-01",
        "evidence_level": "INSTITUTIONAL",
        "review_status": "owner",
        "reviewer": None,
        "authorization": "虚构样例（无真实来源）",
        "transcript_ref": "（虚构）",
        "files": {"narrative": "L1_x.md", "cards": ["L2_x_01.json"]},
    }
    manifest.update(overrides)
    return manifest


def _write_manifest(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# manifest：缺字段即整包拒绝（第 6 节）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing",
    [
        "external_key",
        "title",
        "source_type",
        "subject_type",
        "interview_at",
        "consent_scope",
        "evidence_level",
        "review_status",
        "authorization",
        "files",
    ],
)
def test_manifest_rejects_each_missing_required_field(tmp_path: Path, missing: str) -> None:
    """删掉任一必填字段 → 整包拒绝，且错误信息指出是哪个字段。

    判别性：把 `load_manifest` 的必填字段循环删掉，本用例失败。
    """
    payload = _valid_manifest()
    del payload[missing]

    with pytest.raises(CasePackageError, match=missing):
        load_manifest(_write_manifest(tmp_path, payload))


def test_manifest_rejects_missing_narrative_or_cards_keys(tmp_path: Path) -> None:
    """`files` 缺 `narrative` 或 `cards` → 拒绝（第 6 节的 manifest 契约）。"""
    with pytest.raises(CasePackageError, match="narrative"):
        load_manifest(_write_manifest(tmp_path, _valid_manifest(files={"cards": ["a.json"]})))

    with pytest.raises(CasePackageError, match="cards"):
        load_manifest(_write_manifest(tmp_path, _valid_manifest(files={"narrative": "L1.md"})))


def test_manifest_rejects_empty_card_list(tmp_path: Path) -> None:
    """`cards` 为空数组 → 拒绝：案例至少要有一张卡片（检索单位是卡片）。"""
    with pytest.raises(CasePackageError, match="cards"):
        load_manifest(_write_manifest(tmp_path, _valid_manifest(files={"narrative": "L1.md", "cards": []})))


def test_manifest_rejects_missing_file(tmp_path: Path) -> None:
    """manifest.json 不存在 → 拒绝，不静默当空包。"""
    with pytest.raises(CasePackageError, match="manifest.json"):
        load_manifest(tmp_path / "nope.json")


def test_manifest_rejects_invalid_json(tmp_path: Path) -> None:
    """非法 JSON → 拒绝。"""
    path = tmp_path / "manifest.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(CasePackageError, match="JSON"):
        load_manifest(path)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("subject_type", "公司"),
        ("evidence_level", "GUESS"),
        ("review_status", "reviewed"),
    ],
)
def test_manifest_rejects_out_of_domain_values(tmp_path: Path, field: str, bad_value: str) -> None:
    """值域越界 → 拒绝，错误信息带字段名（在入口先拒，不留给落库时的 CheckViolation）。"""
    with pytest.raises(CasePackageError, match=field):
        load_manifest(_write_manifest(tmp_path, _valid_manifest(**{field: bad_value})))


def test_manifest_accepts_the_valid_shape(tmp_path: Path) -> None:
    """合法 manifest 被正确解析（正向控制：确认上面的拒绝不是因为解析器一律报错）。"""
    manifest = load_manifest(_write_manifest(tmp_path, _valid_manifest()))

    assert manifest.external_key == "2099-01-01_0000_fictional"
    assert manifest.review_status == "owner"
    assert manifest.reviewer is None
    assert manifest.card_files == ("L2_x_01.json",)
    assert manifest.interview_at.tzinfo is not None


def test_manifest_defaults_status_to_internal(tmp_path: Path) -> None:
    """未给 `status` 时默认 `internal`：案例是访谈经验，默认不对外发布。"""
    manifest = load_manifest(_write_manifest(tmp_path, _valid_manifest()))

    assert manifest.status == "internal"


# ---------------------------------------------------------------------------
# 审阅状态与具名审阅者（第 7 节）
# ---------------------------------------------------------------------------


def test_professional_requires_a_named_reviewer(tmp_path: Path) -> None:
    """`professional` 档缺 `reviewer` → 拒绝：无法追溯是谁审的。"""
    payload = _valid_manifest(review_status="professional", reviewer=None)

    with pytest.raises(CasePackageError, match="reviewer"):
        load_manifest(_write_manifest(tmp_path, payload))


@pytest.mark.parametrize("status", ["owner", "pending"])
def test_non_professional_must_not_carry_a_reviewer(tmp_path: Path, status: str) -> None:
    """`owner`/`pending` 档带 `reviewer` → 拒绝。

    这是公共案例库第 7 节的硬纪律：把「项目所有者核准」写成「已审阅」就是冒充专业认可。
    判别性：去掉 `load_manifest` 里那条对称校验，本用例失败。
    """
    payload = _valid_manifest(review_status=status, reviewer="某人")

    with pytest.raises(CasePackageError, match="reviewer"):
        load_manifest(_write_manifest(tmp_path, payload))


# ---------------------------------------------------------------------------
# interview_at：三个必答问题之一（第 1 节）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["2026-05-25", "2026/05/25 14:48", "不是时间"])
def test_interview_at_rejects_non_iso_or_naive_values(value: str) -> None:
    """非 ISO 8601 或缺时区偏移 → 拒绝。

    缺时区的访谈时间无法与「现在」比较，也无法跨时区解释（上游目录名带 +08:00），
    而「什么时候」是案例不得缺的三问之一——留空等于让该案例无法回答。
    """
    with pytest.raises(CasePackageError, match="interview_at"):
        parse_interview_at(value)


def test_interview_at_parses_offset_datetime() -> None:
    """带偏移的 ISO 8601 正确解析。"""
    parsed = parse_interview_at("2026-05-25T14:48:00+08:00")

    assert parsed.utcoffset() is not None
    assert parsed.astimezone(timezone.utc) == datetime(2026, 5, 25, 6, 48, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 卡片值域（第 4 节：值域不重写）
# ---------------------------------------------------------------------------


def test_card_accepts_the_upstream_shape() -> None:
    """上游形状的卡片通过校验（正向控制）。

    若这条失败，说明校验器比上游 `validate_l2.py` 更严——那会把原本合格的案例包
    拒之门外，而失败形态是「导入报缺字段」，很容易被当成上游数据问题。
    """
    assert validate_card(_valid_card(), card_label="c.json") == []


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("behavior_type", "焦虑"),
        ("severity_level", "很重"),
        ("setting", "商场"),
        ("parent_category", "情绪管理"),
        ("evidence_level", "GUESS"),
    ],
)
def test_card_rejects_out_of_domain_enums(field: str, bad_value: str) -> None:
    """枚举越界 → 报错（第 4 节「导入校验器直接复用 validate_l2.py 的约束」）。

    判别性：把 `validate_card` 的枚举校验删掉，本组用例失败。
    """
    errors = validate_card(_valid_card(**{field: bad_value}), card_label="c.json")

    assert any(field in e for e in errors), f"{field} 越界未被拒：{errors}"


def test_card_rejects_unknown_ebp_tag() -> None:
    """`ebp_tags` 不在 NCAEP 28 项内 → 报错。"""
    errors = validate_card(_valid_card(ebp_tags=["自创疗法(XX)"]), card_label="c.json")

    assert any("ebp_tags" in e for e in errors)


@pytest.mark.parametrize("missing", ["title", "scenario", "immediate_action", "medical_criteria", "caution_notes"])
def test_card_rejects_missing_or_empty_required_strings(missing: str) -> None:
    """必填字符串缺失或为空 → 报错（上游必填 14 项）。"""
    card = _valid_card()
    card[missing] = ""

    assert any(missing in e for e in validate_card(card, card_label="c.json"))


def test_card_rejects_empty_required_arrays() -> None:
    """必填数组为空 → 报错。"""
    assert any("ebp_tags" in e for e in validate_card(_valid_card(ebp_tags=[]), card_label="c.json"))
    assert any("age_range" in e for e in validate_card(_valid_card(age_range=[]), card_label="c.json"))


def test_card_rejects_non_boolean_is_template() -> None:
    """`is_template` 不是布尔 → 报错。"""
    assert any("is_template" in e for e in validate_card(_valid_card(is_template="false"), card_label="c.json"))


def test_card_allows_missing_optional_contraindications() -> None:
    """`contraindications` 可选：删掉它仍通过（上游把它列为可选字符串）。"""
    card = _valid_card()
    del card["contraindications"]

    assert validate_card(card, card_label="c.json") == []


def test_card_rejects_non_string_inferred_values() -> None:
    """`_inferred` 的值必须是字符串（推断理由），不是字符串即报错。"""
    errors = validate_card(_valid_card(_inferred={"age_range": 3}), card_label="c.json")

    assert any("_inferred.age_range" in e for e in errors)


def test_card_reports_not_a_dict() -> None:
    """根节点不是对象 → 明确报错。"""
    assert validate_card(["不是对象"], card_label="c.json") == ["c.json 根节点必须是 JSON 对象"]


def test_card_skips_enum_checks_when_required_fields_are_missing() -> None:
    """必填字段缺失时不做枚举校验。

    否则一个缺失字段会连带刷出一堆误导性的越界报错，掩盖真正的首个问题。
    """
    card = _valid_card()
    del card["title"]

    errors = validate_card(card, card_label="c.json")

    assert len(errors) == 1
    assert "title" in errors[0]


def test_domain_constants_are_non_empty_and_disjoint_from_each_other() -> None:
    """值域常量本身有内容——防止「集合为空导致所有值都被拒」的退化。"""
    assert len(BEHAVIOR_TYPES) == 6
    assert len(SEVERITY_LEVELS) == 3
    assert len(SETTINGS) == 5
    assert len(PARENT_CATEGORIES) == 6
    assert len(VALID_EBP_TAGS) == 28


# ---------------------------------------------------------------------------
# 推断字段与嵌入文本（第 4 节、RAG 策略第 1.3 节）
# ---------------------------------------------------------------------------


def test_inferred_field_names_lists_every_inferred_key() -> None:
    """`_inferred` 的每个键都进 `inferred_fields`（第 4 节）。"""
    names = inferred_field_names({"title": "t", "_inferred": {"age_range": "r", "behavior_type": "r2"}})

    assert names == ["age_range", "behavior_type"]


def test_inferred_field_names_is_empty_without_inferred_block() -> None:
    """没有 `_inferred` 时为空清单——不编造推断标记。"""
    assert inferred_field_names({"title": "t"}) == []
    assert inferred_field_names({"title": "t", "_inferred": "不是对象"}) == []


def test_embedding_text_joins_fields_with_names() -> None:
    """嵌入文本保留字段边界（「字段名：值」逐行拼接）。"""
    text = build_card_embedding_text(_valid_card())

    assert "title：虚构卡片标题" in text
    assert "immediate_action：1. 动作一。" in text


def test_embedding_text_excludes_inferred_and_identifiers() -> None:
    """`_inferred` 与标识字段不参与嵌入（第 1.3 节）。

    判别性：把 `CARD_NON_EMBEDDED_FIELDS` 清空，本用例失败。
    """
    card = _valid_card()
    text = build_card_embedding_text(card)

    assert "_inferred" not in text
    assert "虚构推断理由" not in text, "推断依据不应驱动命中"
    assert "card_id" not in text
    assert "raw_id" not in text


def test_embedding_text_keeps_high_risk_fields() -> None:
    """高风险字段**参与**嵌入（第 1.3 节）。

    不嵌入它们的话，应急查询反而命不中对应卡片，分层支持策略就落空了。
    """
    text = build_card_embedding_text(_valid_card())

    assert "medical_criteria" in text
    assert "contraindications" in text
    assert "caution_notes" in text


def test_embedding_text_renders_booleans_as_meaningful_chinese() -> None:
    """布尔渲染成中文取值而不是 `False`（对中文查询有语义贡献）。"""
    text = build_card_embedding_text(_valid_card(is_template=False))

    assert "is_template：否" in text
