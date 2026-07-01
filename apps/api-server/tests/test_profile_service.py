"""PROF-01 档案管理 Service — 单元测试。

使用 mock ProfileRepository + AsyncSession 验证 ProfileServiceImpl 业务逻辑。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest import mock
from uuid import uuid4

import pytest
from app.modules.profiles.exceptions import (
    ProfileNotFoundError,
)
from app.modules.profiles.profile_service import ProfileServiceImpl
from py_db.models.profiles import Profile
from py_schemas.profiles import (
    DiagnosisType,
    ProfileBehaviorType,
    ProfileCreate,
    ProfileUpdate,
)


def _mock_profile(**overrides) -> mock.MagicMock:
    now = datetime.now(timezone.utc)
    uid = uuid4()
    pid = uuid4()
    defaults = {
        "profile_id": pid,
        "caregiver_id": uid,
        "nickname": "小明",
        "birth_date": date(2019, 3, 15),
        "diagnosis_type": DiagnosisType.ASD,
        "primary_behavior": ProfileBehaviorType.STEREOTYPED,
        "language_level": None,
        "sensory_features": [],
        "triggers": [],
        "medication_notes": None,
        "is_default": True,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    p = mock.MagicMock(spec=Profile)
    for k, v in defaults.items():
        setattr(p, k, v)
    return p


@pytest.fixture
def repo():
    r = mock.AsyncMock()
    r.list_by_caregiver.return_value = ([_mock_profile()], 1)
    r.get_by_id.return_value = _mock_profile()
    r.get_default.return_value = _mock_profile()
    r.count_active_by_caregiver.return_value = 1
    r.create.return_value = _mock_profile()
    r.set_default.return_value = _mock_profile()
    r.delete.return_value = True
    r.find_next_default_candidate.return_value = _mock_profile()
    return r


@pytest.fixture
def session():
    return mock.AsyncMock()


@pytest.fixture
def svc(repo) -> ProfileServiceImpl:
    return ProfileServiceImpl(repository=repo)


@pytest.fixture
def caregiver_id():
    return uuid4()


class TestListProfiles:
    @pytest.mark.asyncio
    async def test_list_returns_items(self, svc, caregiver_id, session):
        items, total = await svc.list_profiles(caregiver_id, session)
        assert total == 1
        assert len(items) == 1

    @pytest.mark.asyncio
    async def test_list_pagination(self, svc, caregiver_id, session, repo):
        repo.list_by_caregiver.return_value = ([_mock_profile()], 5)
        items, total = await svc.list_profiles(caregiver_id, session, page=2, page_size=2)
        assert total == 5


class TestGetProfile:
    @pytest.mark.asyncio
    async def test_get_by_id(self, svc, caregiver_id, session):
        result = await svc.get_profile(uuid4(), caregiver_id, session)
        assert result is not None
        assert result.nickname == "小明"

    @pytest.mark.asyncio
    async def test_not_found(self, svc, caregiver_id, session, repo):
        repo.get_by_id.return_value = None
        with pytest.raises(ProfileNotFoundError):
            await svc.get_profile(uuid4(), caregiver_id, session)


class TestCreateProfile:
    @pytest.mark.asyncio
    async def test_create_success(self, svc, caregiver_id, session, repo):
        repo.count_active_by_caregiver.return_value = 1
        data = ProfileCreate(
            birth_date=date(2019, 3, 15),
            diagnosis_type="ASD",
            primary_behavior="刻板行为",
        )
        result = await svc.create_profile(caregiver_id, data, session)
        assert result is not None

    @pytest.mark.asyncio
    async def test_first_profile_becomes_default(self, svc, caregiver_id, session, repo):
        repo.count_active_by_caregiver.return_value = 0
        data = ProfileCreate(
            birth_date=date(2019, 3, 15),
            diagnosis_type="ASD",
            primary_behavior="刻板行为",
        )
        await svc.create_profile(caregiver_id, data, session)
        repo.set_default.assert_called_once()


class TestUpdateProfile:
    @pytest.mark.asyncio
    async def test_update_success(self, svc, caregiver_id, session):
        data = ProfileUpdate(nickname="新昵称")
        result = await svc.update_profile(uuid4(), caregiver_id, data, session)
        assert result is not None

    @pytest.mark.asyncio
    async def test_not_found(self, svc, caregiver_id, session, repo):
        repo.get_by_id.return_value = None
        data = ProfileUpdate(nickname="新昵称")
        with pytest.raises(ProfileNotFoundError):
            await svc.update_profile(uuid4(), caregiver_id, data, session)


class TestDeleteProfile:
    @pytest.mark.asyncio
    async def test_delete_success(self, svc, caregiver_id, session):
        await svc.delete_profile(uuid4(), caregiver_id, session)
        session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_delete_default_promotes_next(self, svc, caregiver_id, session, repo):
        repo.get_by_id.return_value = _mock_profile(is_default=True)
        await svc.delete_profile(uuid4(), caregiver_id, session)
        repo.find_next_default_candidate.assert_called_once()


class TestCalcAgeRange:
    def test_null_returns_18_plus(self):
        result = ProfileServiceImpl._calc_age_range(None)
        assert result == "18+"

    def test_age_5_returns_4_6(self):
        birth = date.today().replace(year=date.today().year - 5)
        result = ProfileServiceImpl._calc_age_range(birth)
        assert result == "4-6"

    def test_age_0_returns_0_3(self):
        birth = date.today()
        result = ProfileServiceImpl._calc_age_range(birth)
        assert result == "0-3"
