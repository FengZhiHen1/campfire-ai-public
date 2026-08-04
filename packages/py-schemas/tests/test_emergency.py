"""应急域契约单元测试（ADR-009 时刻分层目标态）。

覆盖：行为桶枚举（统一枚举对齐 + UI 标签映射 + 红线桶集合）、
红线判定契约、桶选择/阶段回答请求校验、四段式输出契约、SSE 事件族。
"""

from __future__ import annotations

import pytest
from py_schemas.crisis import RedlineGateRequest, RedlineGateResult
from py_schemas.emergency import (
    ConsultStreamCreateRequest,
    EmergencyPlan,
    SafetyCardDto,
)
from py_schemas.enums import (
    REDLINE_BUCKETS,
    BehaviorBucket,
    CrisisStage,
    FallbackSignal,
    GateResult,
    MeltdownType,
    TurnType,
)
from py_schemas.streaming import ResultEvent, SseEventType
from pydantic import ValidationError

# ===========================================================================
# 行为桶枚举
# ===========================================================================


class TestBehaviorBucket:
    def test_nine_buckets_aligned_with_profile_enum(self):
        """九桶与档案统一行为类型枚举对齐（ADR-010 第 7 条）。"""
        assert {b.value for b in BehaviorBucket} == {
            "情绪崩溃", "刻板行为", "自伤", "攻击", "走失",
            "用药相关", "社交退缩", "多动", "其他",
        }

    def test_ui_labels(self):
        """UI 标签映射：情绪哭闹/刻板升级/用药（家属认知友好）。"""
        assert BehaviorBucket.MELTDOWN.ui_label == "情绪哭闹"
        assert BehaviorBucket.STEREOTYPY.ui_label == "刻板升级"
        assert BehaviorBucket.MEDICATION.ui_label == "用药"
        assert BehaviorBucket.SELF_INJURY.ui_label == "自伤"

    def test_redline_buckets(self):
        """红线桶：自伤/攻击/走失/用药——点选即命中红线。"""
        assert REDLINE_BUCKETS == frozenset(
            {
                BehaviorBucket.SELF_INJURY,
                BehaviorBucket.AGGRESSION,
                BehaviorBucket.ELOPEMENT,
                BehaviorBucket.MEDICATION,
            }
        )

    def test_stage_and_meltdown_enums(self):
        assert CrisisStage.PEAK == "高峰"
        assert MeltdownType.MELTDOWN == "meltdown"
        assert TurnType.INITIAL_PLAN == "initial_plan"
        assert FallbackSignal.RETRIEVAL_INSUFFICIENT == "retrieval_insufficient"


# ===========================================================================
# 红线判定契约
# ===========================================================================


class TestRedlineGateContract:
    def test_request_all_optional_but_bucket(self):
        req = RedlineGateRequest(bucket=BehaviorBucket.SELF_INJURY)
        assert req.bucket == BehaviorBucket.SELF_INJURY

    def test_result_contract(self):
        result = RedlineGateResult(gate_result=GateResult.REDLINE, gate_trigger="BUCKET_SELF_INJURY")
        assert result.gate_result == GateResult.REDLINE
        passed = RedlineGateResult(gate_result=GateResult.PASS)
        assert passed.gate_trigger is None


# ===========================================================================
# 创建/推进请求
# ===========================================================================


class TestConsultStreamCreateRequest:
    def test_new_session_requires_bucket(self):
        with pytest.raises(ValidationError):
            ConsultStreamCreateRequest()

    def test_new_session_with_bucket(self):
        req = ConsultStreamCreateRequest(bucket=BehaviorBucket.MELTDOWN)
        assert req.bucket == BehaviorBucket.MELTDOWN

    def test_existing_session_requires_answer_or_text(self):
        import uuid

        sid = uuid.uuid4()
        with pytest.raises(ValidationError):
            ConsultStreamCreateRequest(session_id=sid)
        req = ConsultStreamCreateRequest(session_id=sid, stage_answer="能")
        assert req.stage_answer == "能"

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ConsultStreamCreateRequest(bucket=BehaviorBucket.MELTDOWN, behavior_description="旧字段")


# ===========================================================================
# 四段式输出契约
# ===========================================================================


class TestEmergencyPlan:
    def test_valid_plan(self):
        plan = EmergencyPlan(
            immediate_action="将孩子带离当前环境",
            soothing_script="妈妈在这里",
            observation="观察呼吸与面色",
            medical_judgment="出现自伤行为立即就医",
        )
        assert plan.disclaimer  # 免责声明固定文案默认注入
        assert plan.sources == []

    def test_missing_section_rejected(self):
        """四段缺一不可（就医判断标准为强制段落）。"""
        with pytest.raises(ValidationError):
            EmergencyPlan(
                immediate_action="x",
                soothing_script="x",
                observation="x",
                # medical_judgment 缺失
            )

    def test_empty_section_rejected(self):
        with pytest.raises(ValidationError):
            EmergencyPlan(
                immediate_action="",
                soothing_script="x",
                observation="x",
                medical_judgment="x",
            )


class TestSafetyCardDto:
    def test_personalized_flag(self):
        card = SafetyCardDto(
            card_id="c-1",
            bucket=BehaviorBucket.MELTDOWN,
            stage=CrisisStage.TRIGGER,
            title="情绪哭闹·触发期",
            content="移走周围危险物品",
            personalized=True,
        )
        assert card.personalized is True
        assert card.variant == "normal"


# ===========================================================================
# SSE 事件族
# ===========================================================================


class TestSseEventTypes:
    def test_unified_and_emergency_events(self):
        assert SseEventType.CHUNK == "chunk"
        assert SseEventType.RESULT == "result"
        assert SseEventType.DONE == "done"
        assert SseEventType.ERROR == "error"
        assert SseEventType.HEARTBEAT == "heartbeat"
        # 应急面消息事件
        assert SseEventType.SAFETY_CARD == "safety_card"
        assert SseEventType.STAGE_QUESTION == "stage_question"
        assert SseEventType.REDLINE_GUIDE == "redline_guide"
        assert SseEventType.FALLBACK_NOTICE == "fallback_notice"

    def test_result_event_contract_carrier(self):
        evt = ResultEvent(contract="EmergencyPlan", payload={"immediate_action": "x"})
        assert evt.contract == "EmergencyPlan"
