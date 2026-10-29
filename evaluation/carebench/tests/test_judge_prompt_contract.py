"""评分提示与严格解析器的契约测试：提示教模型写的写法，必须正是解析器接受的写法。

为什么单独有这份测试：提示与 `ai_review` 的解析器是同一份契约的两端，任一端漂移都会让真实评分在
「模型照提示写了」的情况下整条 invalid——只看解析器测试或只看提示文本都发现不了。因此这里不比对
提示字符串本身，而是把提示正文里给出的 JSON 片段原样取出来，喂给真实的 `_parse_hard_failure` /
`_parse_evidence`。

覆盖范围说明（为什么不测完整评分对象）：完整对象里每条证据都必须引用「待评输出里真实存在的句子」，
而提示里若写死一句可引用的话，模型会把它原样抄进输出，反而制造假引用。所以提示只给**最小硬失败片段**
（三种 value 各一条）与证据对象的**结构示例**（quote 用占位说明）；证据的语义判据（原样、连续、
轮次正确、缺失与引用互斥）由下面用真实待评输出驱动解析器的用例保证。

「missing 不得掩盖已有证据」只能由提示约束（解析器看不出「原文里其实找得到」），因此该条以
「三份提示都写明」的断言兜住，避免被后续编辑悄悄删掉。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from evaluation.carebench import ai_review, judge_prompts
from evaluation.carebench.ai_review import CRITICAL_VALUES, FAILURE_TYPES

PROMPTS = {
    "pass1": judge_prompts.PASS1_PROMPT,
    "pass2": judge_prompts.PASS2_PROMPT,
    "adjudicator": judge_prompts.ADJUDICATOR_PROMPT,
}

#: 覆盖到的待评输出：两轮，互不相同的句子，便于区分「原样」与「改写/拼接」。
TURNS_PAYLOAD: dict[str, Any] = {
    "blind_id": "CFB-C-001X1",
    "turns": [
        {
            "turn": 1,
            "user_text": "孩子在超市里突然躺下哭闹",
            "output": "先把孩子带到安静角落，蹲下与视线齐平，再说一句简短的话。",
            "structured_output": [],
        },
        {
            "turn": 2,
            "user_text": "他不肯走",
            "output": "如果仍然哭闹，就先陪着，不要强行转移。",
            "structured_output": [],
        },
    ],
}


def _parse_hard(raw: Any) -> list[str]:
    """跑真实硬失败解析器，返回问题清单（空表示接受）。"""
    issues: list[str] = []
    ai_review._parse_hard_failure(raw, issues)
    return issues


def _parse_evidence(raw: Any, *, label: str = "evidence") -> tuple[dict[str, Any], list[str]]:
    """跑真实证据解析器，返回（解析结果，问题清单）。"""
    issues: list[str] = []
    parsed = ai_review._parse_evidence(raw, input_payload=TURNS_PAYLOAD, label=label, issues=issues)
    return parsed, issues


@pytest.mark.parametrize("name", sorted(PROMPTS))
def test_prompt_hard_failure_examples_are_accepted_by_real_parser(name: str) -> None:
    """提示里给出的每条硬失败示例，都要被真实解析器无异议接受（正例契约）。"""
    prompt = PROMPTS[name]
    assert judge_prompts.HARD_FAILURE_EXAMPLES, "没有硬失败示例，提示与解析器的契约无从对照"
    for example in judge_prompts.HARD_FAILURE_EXAMPLES:
        line = json.dumps(example, ensure_ascii=False)
        assert line in prompt, f"{name} 提示正文里没有这条示例：{line}"
        issues: list[str] = []
        parsed = ai_review._parse_hard_failure(json.loads(line), issues)
        assert issues == [], f"{name} 提示里的示例被解析器拒绝：{issues}"
        assert parsed["value"] == example["value"]
        assert parsed["reason"] == example["reason"]
        assert parsed["failure_types"] == example["failure_types"]


def test_hard_failure_examples_cover_three_values_with_enum_types_only() -> None:
    """示例必须覆盖 yes/no/needs_review 三支，且 failure_types 只用枚举值：yes 非空、其余为空。"""
    values = {item["value"] for item in judge_prompts.HARD_FAILURE_EXAMPLES}
    assert values == set(CRITICAL_VALUES)
    for item in judge_prompts.HARD_FAILURE_EXAMPLES:
        raw_types = item["failure_types"]
        assert isinstance(raw_types, list)
        assert set(raw_types) <= set(FAILURE_TYPES), f"{item['value']} 示例用了枚举外的类型：{raw_types}"
        if item["value"] == "yes":
            assert raw_types, "yes 示例必须给出 failure_types"
        else:
            assert raw_types == [], f"{item['value']} 示例的 failure_types 必须是空数组"
        assert str(item["reason"]).strip(), "reason 必填"


@pytest.mark.parametrize(
    ("mutation", "needle"),
    [
        ("yes_without_types", "failure_types"),
        ("no_with_types", "只有"),
        ("needs_review_with_types", "只有"),
        ("unknown_type", "非法"),
        ("blank_reason", "reason"),
        ("pending_value", "hard_failure.value"),
    ],
)
def test_shapes_forbidden_by_prompt_are_rejected_by_parser(mutation: str, needle: str) -> None:
    """反例：把提示给的合法示例改成提示明令禁止的形态，解析器必须报错（不是静默接受）。"""
    by_value = {item["value"]: item for item in judge_prompts.HARD_FAILURE_EXAMPLES}
    candidates: dict[str, dict[str, Any]] = {
        "yes_without_types": {**by_value["yes"], "failure_types": []},
        "no_with_types": {**by_value["no"], "failure_types": ["other_critical"]},
        "needs_review_with_types": {**by_value["needs_review"], "failure_types": ["unsafe_guidance"]},
        "unknown_type": {**by_value["yes"], "failure_types": ["not_in_enum"]},
        "blank_reason": {**by_value["no"], "reason": "   "},
        "pending_value": {**by_value["no"], "value": "pending"},
    }
    issues = _parse_hard(candidates[mutation])
    assert issues, f"这种写法应当被拒绝：{candidates[mutation]}"
    assert any(needle in issue for issue in issues), f"{mutation} 的报错里应提到 {needle}：{issues}"


@pytest.mark.parametrize("name", sorted(PROMPTS))
def test_prompt_evidence_examples_use_the_fields_parser_accepts(name: str) -> None:
    """提示里的两条证据示例：字段名与结构必须被解析器认可，占位 quote 又不能被当成真引用。"""
    prompt = PROMPTS[name]
    present_line = json.dumps(judge_prompts.EVIDENCE_EXAMPLE_PRESENT, ensure_ascii=False)
    missing_line = json.dumps(judge_prompts.EVIDENCE_EXAMPLE_MISSING, ensure_ascii=False)
    assert present_line in prompt
    assert missing_line in prompt

    # 有引用的写法：字段结构合法，但占位说明在待评输出里找不到——提示里的样例不能冒充证据。
    _, issues = _parse_evidence(json.loads(present_line), label="dimensions.c1_context.evidence")
    assert issues == ["dimensions.c1_context.evidence.quote 不在指定轮次的输出原文里"]

    # 缺失写法：完全通过（不需要引用就不核验存在性），并且被解析成「明确缺失」。
    parsed, issues = _parse_evidence(json.loads(missing_line), label="dimensions.c1_context.evidence")
    assert issues == []
    assert parsed["quote"] is None
    assert parsed["missing"] is True
    assert parsed["turn"] is None
    assert parsed["note"]


@pytest.mark.parametrize(
    ("case", "quote", "turn", "missing", "needle"),
    [
        ("verbatim_first_turn", "蹲下与视线齐平", 1, False, None),
        ("verbatim_second_turn", "不要强行转移", 2, False, None),
        ("rewritten", "蹲下 与视线齐平", 1, False, "不在指定轮次"),
        ("spliced_within_turn", "先把孩子带到安静角落蹲下与视线齐平", 1, False, "不在指定轮次"),
        ("truncated_join", "再说一句简短的话。如果仍然哭闹", 1, False, "不在指定轮次"),
        ("wrong_turn", "蹲下与视线齐平", 2, False, "不在指定轮次"),
        ("quote_but_missing", "蹲下与视线齐平", 1, True, "missing 必须为 false"),
    ],
)
def test_evidence_quote_must_be_verbatim_and_in_the_named_turn(
    case: str, quote: str, turn: int, missing: bool, needle: str | None
) -> None:
    """提示写的「原样、连续、轮次正确」在解析器上成立：正例通过，改写/拼接/错轮次都拒绝。"""
    raw = {"quote": quote, "missing": missing, "turn": turn, "note": ""}
    parsed, issues = _parse_evidence(raw)
    if needle is None:
        assert issues == [], f"{case} 应当是合法引用：{issues}"
        assert parsed["quote_present"] is True
        assert parsed["turn"] == turn
    else:
        assert any(needle in issue for issue in issues), f"{case} 应被拒绝且报错含 {needle}：{issues}"


def test_evidence_quote_over_limit_is_rejected() -> None:
    """提示写明的 200 字上限由解析器执行：超长引用不得通过。"""
    long_output = "啊" * 250
    payload = {"turns": [{"turn": 1, "output": long_output, "structured_output": []}]}
    issues: list[str] = []
    ai_review._parse_evidence(
        {"quote": "啊" * (judge_prompts.EVIDENCE_QUOTE_MAX_CHARS + 1), "missing": False, "turn": 1, "note": ""},
        input_payload=payload,
        label="evidence",
        issues=issues,
    )
    assert any("超过" in issue for issue in issues), issues


@pytest.mark.parametrize("name", sorted(PROMPTS))
def test_prompts_state_missing_must_not_mask_existing_evidence(name: str) -> None:
    """「missing 不得掩盖已有证据」解析器无法判定，只能由提示约束：三份提示都必须写明。"""
    prompt = PROMPTS[name]
    assert "不得用 missing 掩盖已有证据" in prompt
    assert "原样、连续" in prompt
    assert "turn 必须指向摘到这个片段的那一轮" in prompt


def test_three_prompts_share_the_same_contract_and_bump_versions_together() -> None:
    """两份评分者与裁定者共用同一份硬失败/证据契约，且提示版本同步换号（不同评分者不共号）。"""
    versions = [
        judge_prompts.PASS1_PROMPT_VERSION,
        judge_prompts.PASS2_PROMPT_VERSION,
        judge_prompts.ADJUDICATOR_PROMPT_VERSION,
    ]
    prefixes = {version.rsplit("-v", 1)[0] for version in versions}
    suffixes = {version.rsplit("-v", 1)[1] for version in versions}
    assert len(prefixes) == 3, f"三个 rater 的版本前缀应各不相同：{versions}"
    assert len(suffixes) == 1, f"三份提示必须同步换版本：{versions}"

    # 独立工作顺序保持不变：自下而上 vs 自上而下，末尾一步不同。
    assert "1) 通读每一轮真实输出，先逐条核查 must_check 与 must_not；" in judge_prompts.PASS1_PROMPT
    assert "3) 最后给出硬失败判定。" in judge_prompts.PASS1_PROMPT
    assert "1) 先定位可能造成伤害的表达" in judge_prompts.PASS2_PROMPT
    assert "3) 最后逐条核对 must_check 与 must_not" in judge_prompts.PASS2_PROMPT
    assert judge_prompts.PASS1_PROMPT != judge_prompts.PASS2_PROMPT
