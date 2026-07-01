"""CSLT-05 置信度校验 + 应急咨询 — Pydantic Schema 单元测试。

覆盖 ConfidenceValidationInput、ConfidenceValidationOutput、
LLMAssessmentResult、ValidationVerdict、ConsultStartRequest、ConsultStartResponse。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from py_schemas.consult.confidence import (
    ConfidenceValidationInput,
    ConfidenceValidationOutput,
    LLMAssessmentResult,
    ValidationVerdict,
)
from py_schemas.consult_start import ConsultStartRequest, ConsultStartResponse
from pydantic import ValidationError

# ===========================================================================
# ValidationVerdict
# ===========================================================================


class TestValidationVerdict:
    def test_all(self):
        assert ValidationVerdict.PASS == "PASS"
        assert ValidationVerdict.APPEND_WARNING == "APPEND_WARNING"
        assert ValidationVerdict.FORCE_BLOCK == "FORCE_BLOCK"


# ===========================================================================
# LLMAssessmentResult
# ===========================================================================


class TestLLMAssessmentResult:
    def test_valid(self):
        r = LLMAssessmentResult(
            citation_adequacy=0.85,
            logical_coherence=0.9,
            unsourced_claim_risk=0.1,
        )
        assert r.citation_adequacy == 0.85

    def test_score_out_of_range(self):
        with pytest.raises(ValidationError):
            LLMAssessmentResult(citation_adequacy=1.5, logical_coherence=0.9, unsourced_claim_risk=0.1)

    def test_negative_score(self):
        with pytest.raises(ValidationError):
            LLMAssessmentResult(citation_adequacy=-0.1, logical_coherence=0.9, unsourced_claim_risk=0.1)


# ===========================================================================
# ConfidenceValidationInput
# ===========================================================================


class TestConfidenceValidationInput:
    def test_valid(self):
        inp = ConfidenceValidationInput(
            plan_text="四段式方案文本",
            source_list=["案例来源1"],
            disclaimer="免责声明",
            crisis_level="mild",
            block_deep_response=False,
            behavior_description="患者行为描述",
            request_id=str(uuid4()),
        )
        assert inp.crisis_level == "mild"

    def test_empty_plan_text(self):
        with pytest.raises(ValidationError):
            ConfidenceValidationInput(
                plan_text="",
                source_list=["来源"],
                disclaimer="免责",
                crisis_level="mild",
                block_deep_response=False,
                behavior_description="描述",
                request_id=str(uuid4()),
            )

    def test_invalid_crisis_level(self):
        with pytest.raises(ValidationError):
            ConfidenceValidationInput(
                plan_text="文本",
                source_list=["来源"],
                disclaimer="免责",
                crisis_level="critical",
                block_deep_response=False,
                behavior_description="描述",
                request_id=str(uuid4()),
            )

    def test_default_high_risk_keyword(self):
        inp = ConfidenceValidationInput(
            plan_text="文本",
            source_list=["来源"],
            disclaimer="免责",
            crisis_level="mild",
            block_deep_response=False,
            behavior_description="描述",
            request_id=str(uuid4()),
        )
        assert inp.high_risk_keyword_hit is False


# ===========================================================================
# ConfidenceValidationOutput
# ===========================================================================


class TestConfidenceValidationOutput:
    def test_pass(self):
        out = ConfidenceValidationOutput(
            confidence_score=0.95,
            verdict=ValidationVerdict.PASS,
            modified_plan_text="方案全文",
            ticket_triggered=False,
            validation_time_ms=150.0,
        )
        assert out.verdict == ValidationVerdict.PASS
        assert out.ticket_triggered is False

    def test_force_block(self):
        out = ConfidenceValidationOutput(
            confidence_score=0.0,
            verdict=ValidationVerdict.FORCE_BLOCK,
            modified_plan_text="安全提示文本",
            ticket_triggered=True,
            validation_time_ms=50.0,
        )
        assert out.ticket_triggered is True


# ===========================================================================
# ConsultStartRequest / ConsultStartResponse
# ===========================================================================


class TestConsultStartRequest:
    def test_valid_minimal(self):
        req = ConsultStartRequest(behavior_description="孩子哭闹不止，不知道怎么办")
        assert req.profile_id is None
        assert req.behavior_type is None

    def test_empty_description(self):
        with pytest.raises(ValidationError):
            ConsultStartRequest(behavior_description="")

    def test_too_long_description(self):
        with pytest.raises(ValidationError):
            ConsultStartRequest(behavior_description="x" * 2001)

    def test_with_profile(self):
        req = ConsultStartRequest(
            behavior_description="描述",
            profile_id=uuid4(),
            behavior_type=["SELF_INJURY", "AGGRESSION"],
            emotion_level="重",
        )
        assert req.behavior_type == ["SELF_INJURY", "AGGRESSION"]

    def test_empty_behavior_type(self):
        with pytest.raises(ValidationError):
            ConsultStartRequest(behavior_description="描述", behavior_type=[])


class TestConsultStartResponse:
    def test_valid(self):
        resp = ConsultStartResponse(session_id="session-abc123")
        assert resp.session_id == "session-abc123"

    def test_missing_session_id(self):
        with pytest.raises(ValidationError):
            ConsultStartResponse()
