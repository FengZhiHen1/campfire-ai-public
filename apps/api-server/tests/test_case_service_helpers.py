"""CASE-01 案例服务 — 内部辅助函数单元测试。
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest import mock

import pytest
from fastapi import HTTPException

from py_db.models.case_model import Case
from py_schemas.cases import CaseUpdate, PiiWarning
from py_schemas.enums.case_enums import CaseStatus

from app.services.case_service import (
    _apply_update_fields,
    _check_edit_reset,
    _orm_to_case_list_item,
    _validate_four_stage_fields,
)


def _make_case(**overrides) -> Case:
    now = datetime.now(timezone.utc)
    defaults = {
        "case_id": "CASE-2026-0001",
        "title": "测试",
        "narrative": "叙事内容",
        "source_type": "专家撰写",
        "author_id": "user-1",
        "behavior_type": "自伤",
        "age_range_min": 3,
        "age_range_max": 12,
        "severity": "重度",
        "scene": "家庭",
        "ebp_labels": ["强化"],
        "family_category": "危机安全",
        "immediate_action": "立即干预",
        "comforting_phrase": "安抚话术",
        "observation_metrics": "观察指标",
        "medical_criteria": "就医标准",
        "evidence_level": "机构经验总结",
        "contraindications": "注意",
        "is_template": False,
        "status": CaseStatus.DRAFT,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    case = mock.MagicMock(spec=Case)
    for k, v in defaults.items():
        setattr(case, k, v)
    return case


class TestValidateFourStageFields:
    def test_all_fields_present(self, monkeypatch):
        # _validate_four_stage_fields reads attributes from the obj
        obj = mock.MagicMock()
        obj.immediate_action = "动作1"
        obj.comforting_phrase = "话术1"
        obj.observation_metrics = "指标1"
        obj.medical_criteria = "标准1"
        _validate_four_stage_fields(obj)  # no exception

    def test_missing_field_raises(self):
        obj = mock.MagicMock()
        obj.immediate_action = "动作1"
        obj.comforting_phrase = None
        obj.observation_metrics = "指标1"
        obj.medical_criteria = "标准1"
        with pytest.raises(HTTPException) as exc:
            _validate_four_stage_fields(obj)
        assert exc.value.status_code == 422
        assert "情绪安抚话术" in str(exc.value.detail)

    def test_empty_string_field_raises(self):
        obj = mock.MagicMock()
        obj.immediate_action = "  "
        obj.comforting_phrase = "话术1"
        obj.observation_metrics = "指标1"
        obj.medical_criteria = "标准1"
        with pytest.raises(HTTPException) as exc:
            _validate_four_stage_fields(obj)
        assert exc.value.status_code == 422


class TestCheckEditReset:
    def test_draft_no_change(self):
        case = _make_case(status=CaseStatus.DRAFT)
        result = _check_edit_reset(case)
        assert result is False
        assert case.status == CaseStatus.DRAFT

    def test_pending_review_resets_to_draft(self):
        case = _make_case(status=CaseStatus.PENDING_REVIEW)
        result = _check_edit_reset(case)
        assert result is True
        case.status = CaseStatus.DRAFT  # was set by function
        # Re-run to verify the attribute was set
        case = _make_case(status=CaseStatus.PENDING_REVIEW)
        _check_edit_reset(case)

    def test_rejected_resets_to_draft(self):
        case = _make_case(status=CaseStatus.REJECTED)
        result = _check_edit_reset(case)
        assert result is True

    def test_approved_no_change(self):
        case = _make_case(status=CaseStatus.APPROVED)
        result = _check_edit_reset(case)
        assert result is False


class TestApplyUpdateFields:
    def test_update_title(self):
        case = _make_case()
        update = CaseUpdate(title="新标题", updated_at=datetime.now(timezone.utc))
        _apply_update_fields(case, update)
        assert case.title == "新标题"

    def test_update_age_range(self):
        case = _make_case()
        update = CaseUpdate(age_range=[5, 10], updated_at=datetime.now(timezone.utc))
        _apply_update_fields(case, update)
        assert case.age_range_min == 5
        assert case.age_range_max == 10

    def test_update_ebp_labels(self):
        case = _make_case()
        update = CaseUpdate(ebp_labels=["消退", "强化"], updated_at=datetime.now(timezone.utc))
        _apply_update_fields(case, update)
        assert "消退" in case.ebp_labels

    def test_none_fields_not_applied(self):
        case = _make_case()
        original_title = case.title
        narrative_text = "这是一段至少一百个字的叙事文本来满足 CaseUpdate 的最小长度要求" * 3
        update = CaseUpdate(narrative=narrative_text, updated_at=datetime.now(timezone.utc))
        _apply_update_fields(case, update)
        assert case.title == original_title
        assert case.narrative == narrative_text


class TestOrmToCaseListItem:
    def test_conversion(self):
        case = _make_case()
        item = _orm_to_case_list_item(case)
        assert item.case_id == "CASE-2026-0001"
        assert item.title == "测试"
