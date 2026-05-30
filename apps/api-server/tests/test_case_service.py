"""CASE-01 案例服务 — create_case / submit_case / get_case / PII 检测 单元测试。

使用 mock Repository + AsyncSession 验证 CaseManagementService 业务编排逻辑。
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest import mock

import pytest
from fastapi import HTTPException

from py_db.models.case_model import Case
from py_security import RegexPiiDetector
from py_schemas.cases import CaseCreateRequest, CaseUpdate
from py_schemas.enums.case_enums import CaseStatus

from app.modules.cases.case_mgmt.service import CaseManagementService
from app.modules.cases.types import CaseId


def _mock_case(**overrides) -> mock.MagicMock:
    now = datetime.now(timezone.utc)
    defaults = {
        "case_id": "CASE-2026-0001",
        "title": "测试案例",
        "narrative": "叙事内容",
        "source_type": "专家撰写",
        "author_id": "user-1",
        "behavior_type": "自伤",
        "age_range_min": 3, "age_range_max": 12,
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
        "excluded_population": None,
        "attachment_refs": None,
        "review_comment": None,
        "status": CaseStatus.DRAFT,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    c = mock.MagicMock(spec=Case)
    for k, v in defaults.items():
        setattr(c, k, v)
    return c


def _valid_create_data():
    return CaseCreateRequest(
        title="测试案例",
        behavior_type="自伤",
        severity="重度",
        scene="家庭",
        immediate_action="立即干预",
        comforting_phrase="安抚话术",
        observation_metrics="观察指标",
        medical_criteria="就医标准",
        evidence_level="机构经验总结",
    )


@pytest.fixture
def session():
    return mock.AsyncMock()


@pytest.fixture
def repo():
    r = mock.AsyncMock()
    r.generate_case_id.return_value = "CASE-2026-0042"
    r.create.return_value = _mock_case(case_id="CASE-2026-0042")
    r.find_by_case_id.return_value = _mock_case()
    r.find_by_id_with_version.return_value = _mock_case()
    r.update_case_with_version.return_value = _mock_case()
    r.update_status.return_value = _mock_case(status=CaseStatus.PENDING_REVIEW)
    return r


@pytest.fixture
def user():
    return {"sub": "user-1", "roles": ["expert"]}


@pytest.fixture
def svc():
    return CaseManagementService()


# ---- create_case ----


class TestCreateCase:
    @pytest.mark.asyncio
    async def test_create_success(self, svc, session, repo, user):
        request = _valid_create_data()
        response = await svc.create_case(
            request=request, current_user=user, session=session, case_repo=repo,
        )
        assert response.case_id == "CASE-2026-0042"
        assert response.status == "draft"

    @pytest.mark.asyncio
    async def test_create_missing_four_stage_field(self, svc, session, repo, user):
        request = _valid_create_data()
        request.medical_criteria = ""
        with pytest.raises(HTTPException) as exc:
            await svc.create_case(
                request=request, current_user=user, session=session, case_repo=repo,
            )
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_create_db_failure(self, svc, session, repo, user):
        repo.create.side_effect = RuntimeError("DB down")
        request = _valid_create_data()
        with pytest.raises(HTTPException) as exc:
            await svc.create_case(
                request=request, current_user=user, session=session, case_repo=repo,
            )
        assert exc.value.status_code == 503


# ---- get_case ----


class TestGetCase:
    @pytest.mark.asyncio
    async def test_get_own_draft(self, svc, session, repo, user):
        case = _mock_case(status=CaseStatus.DRAFT, author_id="user-1")
        repo.find_by_case_id.return_value = case
        response = await svc.get_case(
            case_id=CaseId("CASE-2026-0001"), current_user=user,
            session=session, case_repo=repo,
        )
        assert response.is_owner is True

    @pytest.mark.asyncio
    async def test_get_other_draft_returns_404(self, svc, session, repo, user):
        case = _mock_case(status=CaseStatus.DRAFT, author_id="other-user")
        repo.find_by_case_id.return_value = case
        with pytest.raises(HTTPException) as exc:
            await svc.get_case(
                case_id=CaseId("CASE-2026-0001"), current_user=user,
                session=session, case_repo=repo,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_approved_by_anyone(self, svc, session, repo, user):
        case = _mock_case(status=CaseStatus.APPROVED, author_id="other-user")
        repo.find_by_case_id.return_value = case
        response = await svc.get_case(
            case_id=CaseId("CASE-2026-0001"), current_user=user,
            session=session, case_repo=repo,
        )
        assert response.is_owner is False

    @pytest.mark.asyncio
    async def test_not_found(self, svc, session, repo, user):
        repo.find_by_case_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await svc.get_case(
                case_id=CaseId("CASE-2026-9999"), current_user=user,
                session=session, case_repo=repo,
            )
        assert exc.value.status_code == 404


# ---- submit_case ----


class TestSubmitCase:
    @pytest.mark.asyncio
    async def test_submit_success(self, svc, session, repo, user):
        case = _mock_case(status=CaseStatus.DRAFT)
        repo.find_by_case_id.return_value = case
        updated = _mock_case(status=CaseStatus.PENDING_REVIEW)
        repo.update_status.return_value = updated
        svc._pii_detector.detect = mock.MagicMock(return_value=mock.MagicMock(has_pii=False, warnings=[]))
        response = await svc.submit_case(
            case_id=CaseId("CASE-2026-0001"), current_user=user,
            session=session, case_repo=repo,
        )
        assert response.status == "pending_review"

    @pytest.mark.asyncio
    async def test_submit_not_draft(self, svc, session, repo, user):
        case = _mock_case(status=CaseStatus.APPROVED)
        repo.find_by_case_id.return_value = case
        with pytest.raises(HTTPException) as exc:
            await svc.submit_case(
                case_id=CaseId("CASE-2026-0001"), current_user=user,
                session=session, case_repo=repo,
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_submit_not_found(self, svc, session, repo, user):
        repo.find_by_case_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await svc.submit_case(
                case_id=CaseId("CASE-2026-9999"), current_user=user,
                session=session, case_repo=repo,
            )
        assert exc.value.status_code == 404


# ---- PII 检测 ----


class TestDetectPii:
    def test_no_pii(self):
        detector = RegexPiiDetector()
        result = detector.detect("abc 123 !@#")
        assert result.has_pii is False

    def test_has_pii(self):
        detector = RegexPiiDetector()
        result = detector.detect("联系13800138000")
        assert result.has_pii is True
