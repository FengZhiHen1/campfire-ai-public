"""CASE-01 案例录入管理 + CASE-03 审核工作流 — Pydantic Schema 单元测试。

覆盖 CaseCreateRequest、CaseUpdate、CaseResponse、CaseListItem、
PiiWarning、PiiDetectionResult、PaginatedResponse、ReviewRequest、
CheckItem、AiReviewSummary、CaseReviewResponse、ReviewQueueItem。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from py_schemas.cases import (
    AiReviewSummary,
    CaseCreateRequest,
    CaseListItem,
    CaseResponse,
    CaseUpdate,
    CheckItem,
    PiiDetectionResult,
    PiiWarning,
    ReviewAuditAction,
    ReviewQueueItem,
    ReviewRequest,
)
from py_schemas.enums.case_enums import BehaviorType, CaseStatus


# ===========================================================================
# helpers
# ===========================================================================


def _valid_create_data(**overrides):
    data = {
        "title": "测试案例",
        "behavior_type": "自伤",
        "severity": "重度",
        "scene": "家庭",
        "immediate_action": "立即阻止",
        "comforting_phrase": "没关系",
        "observation_metrics": "观察情绪",
        "medical_criteria": "出现伤口立即就医",
        "evidence_level": "机构经验总结",
    }
    data.update(overrides)
    return data


# ===========================================================================
# CaseCreateRequest
# ===========================================================================


class TestCaseCreateRequest:
    def test_valid_minimal(self):
        req = CaseCreateRequest(**_valid_create_data())
        assert req.title == "测试案例"
        assert req.behavior_type == BehaviorType.SELF_INJURY

    def test_title_too_long(self):
        with pytest.raises(ValidationError):
            CaseCreateRequest(**_valid_create_data(title="a" * 101))

    def test_missing_required_fields(self):
        required = ["title", "behavior_type", "severity", "scene", "immediate_action",
                    "comforting_phrase", "observation_metrics", "medical_criteria", "evidence_level"]
        for field in required:
            data = _valid_create_data()
            del data[field]
            with pytest.raises(ValidationError, match=field):
                CaseCreateRequest(**data)

    def test_immediate_action_empty_string(self):
        with pytest.raises(ValidationError):
            CaseCreateRequest(**_valid_create_data(immediate_action=""))

    def test_age_range_valid(self):
        req = CaseCreateRequest(**_valid_create_data(age_range=[3, 12]))
        assert req.age_range == [3, 12]

    def test_age_range_start_gt_end(self):
        with pytest.raises(ValidationError) as exc:
            CaseCreateRequest(**_valid_create_data(age_range=[12, 3]))
        assert "起始值不能大于结束值" in str(exc.value)

    def test_age_range_out_of_bounds(self):
        with pytest.raises(ValidationError):
            CaseCreateRequest(**_valid_create_data(age_range=[-1, 10]))

    def test_age_range_wrong_size(self):
        with pytest.raises(ValidationError):
            CaseCreateRequest(**_valid_create_data(age_range=[3]))

    def test_ebp_labels_empty(self):
        with pytest.raises(ValidationError) as exc:
            CaseCreateRequest(**_valid_create_data(ebp_labels=[]))
        assert "至少需要包含一个标签" in str(exc.value)

    def test_ebp_labels_valid(self):
        req = CaseCreateRequest(**_valid_create_data(ebp_labels=["强化", "消退"]))
        assert req.ebp_labels == ["强化", "消退"]

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            CaseCreateRequest(**_valid_create_data(), unknown="field")

    def test_is_template_default(self):
        req = CaseCreateRequest(**_valid_create_data())
        assert req.is_template is False

    def test_narrative_default(self):
        req = CaseCreateRequest(**_valid_create_data())
        assert req.narrative == ""


# ===========================================================================
# CaseUpdate
# ===========================================================================


class TestCaseUpdate:
    def test_valid_minimal(self):
        now = datetime.now(timezone.utc)
        req = CaseUpdate(updated_at=now)
        assert req.updated_at == now
        assert req.title is None

    def test_missing_updated_at(self):
        with pytest.raises(ValidationError):
            CaseUpdate()

    def test_partial_update_fields(self):
        now = datetime.now(timezone.utc)
        req = CaseUpdate(title="新标题", updated_at=now)
        assert req.title == "新标题"
        assert req.behavior_type is None

    def test_age_range_validation(self):
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError):
            CaseUpdate(age_range=[12, 3], updated_at=now)

    def test_extra_fields_forbidden(self):
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError):
            CaseUpdate(updated_at=now, extra="bad")


# ===========================================================================
# PiiWarning / PiiDetectionResult
# ===========================================================================


class TestPiiWarning:
    def test_valid(self):
        w = PiiWarning(pii_type="手机号码", detected_text="13800138000", position_start=10, position_end=21)
        assert w.pii_type == "手机号码"
        assert w.position_start == 10


class TestPiiDetectionResult:
    def test_has_pii_true(self):
        w = PiiWarning(pii_type="手机号码", detected_text="13800138000", position_start=0, position_end=11)
        result = PiiDetectionResult(has_pii=True, warnings=[w])
        assert result.has_pii is True
        assert len(result.warnings) == 1

    def test_has_pii_false(self):
        result = PiiDetectionResult(has_pii=False, warnings=[])
        assert result.has_pii is False


# ===========================================================================
# CaseResponse / CaseListItem
# ===========================================================================


class TestCaseResponse:
    def test_minimal_valid(self):
        now = datetime.now(timezone.utc)
        resp = CaseResponse(
            case_id="CASE-2026-0001",
            status=CaseStatus.DRAFT,
            title="测试",
            narrative="",
            source_type="专家撰写",
            author_id="user-1",
            behavior_type="自伤",
            age_range=[3, 12],
            severity="重度",
            scene="家庭",
            ebp_labels=["强化"],
            family_category="环境调整",
            immediate_action="动作",
            comforting_phrase="话术",
            observation_metrics="指标",
            medical_criteria="标准",
            evidence_level="机构经验总结",
            contraindications="注意",
            is_template=False,
            created_at=now,
            updated_at=now,
        )
        assert resp.case_id == "CASE-2026-0001"


class TestCaseListItem:
    def test_valid(self):
        now = datetime.now(timezone.utc)
        item = CaseListItem(
            case_id="CASE-2026-0001",
            title="测试",
            status="draft",
            source_type="专家撰写",
            behavior_type="自伤",
            severity="轻度",
            scene="学校",
            author_id="user-1",
            evidence_level="NCAEP循证实践",
            age_range="3-6岁",
            is_template=False,
            created_at=now,
            updated_at=now,
        )
        assert item.case_id == "CASE-2026-0001"


# ===========================================================================
# ReviewRequest / CheckItem / AiReviewSummary
# ===========================================================================


class TestReviewRequest:
    def test_valid_approved(self):
        req = ReviewRequest(decision="approved")
        assert req.decision == "approved"
        assert req.pii_override_confirmed is False

    def test_valid_rejected(self):
        req = ReviewRequest(decision="rejected")
        assert req.decision == "rejected"

    def test_invalid_decision(self):
        with pytest.raises(ValidationError):
            ReviewRequest(decision="pending")


class TestCheckItem:
    def test_valid_pass(self):
        item = CheckItem(status="pass", is_hard_gate=True)
        assert item.status == "pass"

    def test_valid_fail(self):
        item = CheckItem(status="fail", details=["缺少字段"], is_hard_gate=True)
        assert item.details == ["缺少字段"]

    def test_invalid_status(self):
        with pytest.raises(ValidationError):
            CheckItem(status="unknown", is_hard_gate=False)


class TestAiReviewSummary:
    def test_valid(self):
        fmt = CheckItem(status="pass", is_hard_gate=True)
        pii = CheckItem(status="pass", is_hard_gate=True)
        rf = CheckItem(status="pass", is_hard_gate=False)
        ebp = CheckItem(status="pass", is_hard_gate=False)
        summary = AiReviewSummary(
            format_check=fmt,
            pii_check=pii,
            required_fields_check=rf,
            ebp_consistency_check=ebp,
            overall="pass",
        )
        assert summary.overall == "pass"

    def test_hard_block(self):
        fmt = CheckItem(status="fail", details=["格式错误"], is_hard_gate=True)
        pii = CheckItem(status="pass", is_hard_gate=True)
        rf = CheckItem(status="pass", is_hard_gate=False)
        ebp = CheckItem(status="annotated", is_hard_gate=False)
        summary = AiReviewSummary(
            format_check=fmt, pii_check=pii,
            required_fields_check=rf, ebp_consistency_check=ebp,
            overall="hard_block",
        )
        assert summary.overall == "hard_block"


class TestReviewQueueItem:
    def test_valid(self):
        now = datetime.now(timezone.utc)
        item = ReviewQueueItem(
            case_id="CASE-2026-0001",
            title="测试",
            author_name="张三",
            behavior_type="自伤",
            submitted_at=now,
            ai_review_overall="annotated",
            deadline=now,
            timeout_status="normal",
        )
        assert item.timeout_status == "normal"


class TestReviewAuditAction:
    def test_all_actions(self):
        assert ReviewAuditAction.SUBMITTED == "submitted"
        assert ReviewAuditAction.APPROVED == "approved"
        assert ReviewAuditAction.REJECTED == "rejected"
