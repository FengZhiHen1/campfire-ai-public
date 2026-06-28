"""CSLT-06 咨询历史管理 — Pydantic Schema 单元测试。

覆盖 ConsultationHistoryCreate、ConsultationHistoryListItem、
ConsultationHistoryDetail、GENERATION_DISCLAIMER_CONST。
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from py_schemas.consultation_history import (
    ConsultationHistoryCreate,
    ConsultationHistoryDetail,
    ConsultationHistoryListItem,
    GENERATION_DISCLAIMER_CONST,
)


DISCLAIMER = GENERATION_DISCLAIMER_CONST


def _valid_create_data(**overrides):
    data = {
        "request_id": uuid4(),
        "user_id": uuid4(),
        "crisis_level": "mild",
        "behavior_description": "孩子哭闹",
        "consultation_time": datetime.now(timezone.utc),
        "generated_plan": "方案内容",
        "source_list": ["来源1"],
        "disclaimer": DISCLAIMER,
        "generation_time_ms": 1200.0,
        "is_partial": False,
        "referenced_slice_ids": [uuid4()],
        "finish_reason": "COMPLETE",
        "ttft_ms": 200.0,
    }
    data.update(overrides)
    return data


class TestConsultationHistoryCreate:
    def test_valid_minimal(self):
        req = ConsultationHistoryCreate(**_valid_create_data())
        assert req.crisis_level == "mild"
        assert req.finish_reason == "COMPLETE"
        assert req.has_feedback is False

    def test_wrong_disclaimer(self):
        with pytest.raises(ValidationError):
            ConsultationHistoryCreate(**_valid_create_data(disclaimer="wrong disclaimer"))

    def test_empty_behavior_description(self):
        with pytest.raises(ValidationError):
            ConsultationHistoryCreate(**_valid_create_data(behavior_description=""))

    def test_too_long_description(self):
        with pytest.raises(ValidationError):
            ConsultationHistoryCreate(**_valid_create_data(behavior_description="x" * 2001))

    def test_negative_generation_time(self):
        with pytest.raises(ValidationError):
            ConsultationHistoryCreate(**_valid_create_data(generation_time_ms=-1.0))

    def test_invalid_crisis_level(self):
        with pytest.raises(ValidationError):
            ConsultationHistoryCreate(**_valid_create_data(crisis_level="critical"))

    def test_invalid_finish_reason(self):
        with pytest.raises(ValidationError):
            ConsultationHistoryCreate(**_valid_create_data(finish_reason="UNKNOWN"))

    def test_partial_result(self):
        req = ConsultationHistoryCreate(**_valid_create_data(is_partial=True, finish_reason="PARTIAL"))
        assert req.is_partial is True

    def test_all_finish_reasons(self):
        for reason in ("COMPLETE", "PARTIAL", "BLOCKED", "TIMEOUT", "ERROR"):
            req = ConsultationHistoryCreate(**_valid_create_data(finish_reason=reason))
            assert req.finish_reason == reason

    def test_plan_sections_default_empty(self):
        req = ConsultationHistoryCreate(**_valid_create_data())
        assert req.plan_sections == {}

    def test_plan_sections_preserved(self):
        sections = {
            "即时安全干预动作": ["第一步：确保安全"],
            "情绪安抚话术": ["\"没关系，我陪着你。\""],
            "后续观察指标": ["观察频率"],
            "就医判断标准": ["出现自伤时就医"],
        }
        req = ConsultationHistoryCreate(**_valid_create_data(plan_sections=sections))
        assert req.plan_sections == sections

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ConsultationHistoryCreate(**_valid_create_data(), extra="bad")


class TestConsultationHistoryListItem:
    def test_valid(self):
        uid = uuid4()
        now = datetime.now(timezone.utc)
        item = ConsultationHistoryListItem(
            id=uid,
            consultation_time=now,
            behavior_description="孩子哭闹",
            crisis_level="moderate",
            has_feedback=False,
        )
        assert item.crisis_level == "moderate"


class TestConsultationHistoryDetail:
    def test_valid(self):
        uid = uuid4()
        now = datetime.now(timezone.utc)
        detail = ConsultationHistoryDetail(
            id=uid,
            request_id=uid,
            user_id=uid,
            crisis_level="mild",
            behavior_description="描述",
            consultation_time=now,
            generated_plan="方案",
            source_list=["来源"],
            disclaimer=DISCLAIMER,
            generation_time_ms=1000.0,
            is_partial=False,
            referenced_slice_ids=[uid],
            finish_reason="COMPLETE",
            ttft_ms=200.0,
            has_feedback=False,
        )
        assert detail.id == uid


class TestDisclaimer:
    def test_constant_not_empty(self):
        assert len(GENERATION_DISCLAIMER_CONST) > 10

    def test_contains_key_phrases(self):
        assert "AI 生成" in GENERATION_DISCLAIMER_CONST
        assert "仅供参考" in GENERATION_DISCLAIMER_CONST
