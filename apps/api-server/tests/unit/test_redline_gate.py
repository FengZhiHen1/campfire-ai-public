"""红线安全门单元测试（ADR-008 二元判定，零 LLM）。

覆盖红线安全门 §三 全部判定规则：
- 桶分流：自伤/攻击/走失/用药直接命中
- 关键词硬拦截：高危词命中
- 否定词过滤：「没有/不会/以前」+ 高危词 → 排除
- 档案叠加：历史自伤/攻击 + 「又/再次/还是」→ 命中
- 输出契约：gate_result / gate_trigger 正确性

安全底线：本测试套件不依赖任何模型 mock（判定为纯规则）。
"""

from __future__ import annotations

import pytest
from app.modules.crisis.redline_gate import RedlineGate
from py_schemas.crisis import RedlineGateRequest
from py_schemas.enums import BehaviorBucket, GateResult

# 内置默认词库（机制 §3.2 示例词）
DEFAULT_KEYWORDS = [
    ("撞墙", "KW_SELF_HARM_001"),
    ("撞头", "KW_SELF_HARM_002"),
    ("咬手", "KW_SELF_HARM_003"),
    ("抓破", "KW_SELF_HARM_004"),
    ("打别人", "KW_AGGRESSION_001"),
    ("跑出去", "KW_ELOPEMENT_001"),
    ("吞药", "KW_MEDICATION_001"),
    ("割腕", "KW_SELF_HARM_005"),
]

NEGATIONS = ["没有", "不会", "以前"]


def _gate() -> RedlineGate:
    return RedlineGate(keywords=DEFAULT_KEYWORDS, negations=NEGATIONS)


class TestBucketRouting:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bucket,expected_trigger",
        [
            (BehaviorBucket.SELF_INJURY, "BUCKET_SELF_INJURY"),
            (BehaviorBucket.AGGRESSION, "BUCKET_AGGRESSION"),
            (BehaviorBucket.ELOPEMENT, "BUCKET_ELOPEMENT"),
            (BehaviorBucket.MEDICATION, "BUCKET_MEDICATION"),
        ],
    )
    async def test_redline_buckets_hit(self, bucket, expected_trigger):
        result = await _gate().evaluate(RedlineGateRequest(bucket=bucket), profile_has_harm_history=None)
        assert result.gate_result == GateResult.REDLINE
        assert result.gate_trigger == expected_trigger

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bucket",
        [BehaviorBucket.MELTDOWN, BehaviorBucket.STEREOTYPY, BehaviorBucket.OTHER],
    )
    async def test_non_redline_buckets_pass(self, bucket):
        result = await _gate().evaluate(RedlineGateRequest(bucket=bucket), profile_has_harm_history=None)
        assert result.gate_result == GateResult.PASS
        assert result.gate_trigger is None


class TestKeywordInterception:
    @pytest.mark.asyncio
    async def test_keyword_hit(self):
        result = await _gate().evaluate(
            RedlineGateRequest(text="他一直在撞头，停不下来"),
            profile_has_harm_history=None,
        )
        assert result.gate_result == GateResult.REDLINE
        assert result.gate_trigger == "KW_SELF_HARM_002"

    @pytest.mark.asyncio
    async def test_keyword_with_negation_passes(self):
        """否定过滤：「没有撞头」不命中。"""
        result = await _gate().evaluate(
            RedlineGateRequest(text="他没有撞头，只是哭闹"),
            profile_has_harm_history=None,
        )
        assert result.gate_result == GateResult.PASS

    @pytest.mark.asyncio
    async def test_past_tense_negation_passes(self):
        result = await _gate().evaluate(
            RedlineGateRequest(text="以前会撞墙，现在不会了"),
            profile_has_harm_history=None,
        )
        assert result.gate_result == GateResult.PASS

    @pytest.mark.asyncio
    async def test_keyword_after_negation_scope_still_hits(self):
        """否定词仅覆盖其紧邻窗口——窗口外的命中仍然生效。"""
        result = await _gate().evaluate(
            RedlineGateRequest(text="以前不这样，但今天他突然开始撞头而且抓破了手臂"),
            profile_has_harm_history=None,
        )
        assert result.gate_result == GateResult.REDLINE

    @pytest.mark.asyncio
    async def test_no_text_passes(self):
        result = await _gate().evaluate(RedlineGateRequest(), profile_has_harm_history=None)
        assert result.gate_result == GateResult.PASS


class TestProfileRecurrence:
    @pytest.mark.asyncio
    async def test_recurrence_hits(self):
        """档案叠加：历史自伤/攻击 + 「又/再次/还是」→ 红线。"""
        result = await _gate().evaluate(
            RedlineGateRequest(text="他又开始哭闹了"),
            profile_has_harm_history=True,
        )
        assert result.gate_result == GateResult.REDLINE
        assert result.gate_trigger == "PROFILE_RECURRENCE"

    @pytest.mark.asyncio
    async def test_recurrence_without_history_passes(self):
        result = await _gate().evaluate(
            RedlineGateRequest(text="他又开始哭闹了"),
            profile_has_harm_history=False,
        )
        assert result.gate_result == GateResult.PASS

    @pytest.mark.asyncio
    async def test_recurrence_without_trigger_word_passes(self):
        result = await _gate().evaluate(
            RedlineGateRequest(text="他在哭闹"),
            profile_has_harm_history=True,
        )
        assert result.gate_result == GateResult.PASS

    @pytest.mark.asyncio
    async def test_recurrence_without_text_passes(self):
        result = await _gate().evaluate(
            RedlineGateRequest(bucket=BehaviorBucket.MELTDOWN),
            profile_has_harm_history=True,
        )
        assert result.gate_result == GateResult.PASS


class TestRulePriority:
    @pytest.mark.asyncio
    async def test_bucket_beats_keyword(self):
        """桶分流优先（规则链顺序：桶 → 关键词 → 档案叠加）。"""
        result = await _gate().evaluate(
            RedlineGateRequest(bucket=BehaviorBucket.SELF_INJURY, text="撞头"),
            profile_has_harm_history=True,
        )
        assert result.gate_trigger == "BUCKET_SELF_INJURY"
