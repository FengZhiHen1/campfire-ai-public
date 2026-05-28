"""PROF-01 档案管理 + PROF-03 事件记录 + PROF-05 隐私控制 — Pydantic Schema 单元测试。

覆盖 ProfileCreate、ProfileUpdate、ProfileResponse、ProfileListItem、
EventCreate、EventUpdate、EventResponse、EventListItem、
AccessRequest、AccessDecision、枚举类型、calculate_age_range。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from py_schemas.profiles import (
    AccessDecision,
    AccessOperation,
    AccessRequest,
    AgeRange,
    DiagnosisType,
    EventCreate,
    EventListItem,
    EventResponse,
    EventSetting,
    EventUpdate,
    LanguageLevel,
    ProfileBehaviorType,
    ProfileCreate,
    ProfileListItem,
    ProfileResponse,
    ProfileUpdate,
    SensoryFeature,
    SeverityLevel,
    Trigger,
    VisibleScope,
    calculate_age_range,
)


# ===========================================================================
# Enums
# ===========================================================================


class TestAccessOperation:
    def test_all_ops(self):
        assert AccessOperation.VIEW == "view"
        assert AccessOperation.CREATE == "create"
        assert AccessOperation.UPDATE == "update"
        assert AccessOperation.DELETE == "delete"
        assert AccessOperation.SUPPLEMENT_ASSESSMENT == "supplement_assessment"
        assert AccessOperation.UNLINK == "unlink"


class TestVisibleScope:
    def test_all_scopes(self):
        assert VisibleScope.ALL_FIELDS == "all_fields"
        assert VisibleScope.METADATA_ONLY == "metadata_only"
        assert VisibleScope.NOTHING == "none"


class TestDiagnosisType:
    def test_all(self):
        assert DiagnosisType.ASD == "ASD"
        assert DiagnosisType.SUSPECTED_ASD == "疑似ASD"
        assert DiagnosisType.OTHER_DEVELOPMENTAL_DISORDER == "其他发育障碍"


class TestProfileBehaviorType:
    def test_all(self):
        assert ProfileBehaviorType.STEREOTYPED == "刻板行为"
        assert ProfileBehaviorType.MELTDOWN == "情绪崩溃"
        assert ProfileBehaviorType.SELF_INJURY == "自伤行为"
        assert ProfileBehaviorType.AGGRESSION == "攻击行为"


# ===========================================================================
# AccessRequest / AccessDecision
# ===========================================================================


class TestAccessRequest:
    def test_valid(self):
        uid = uuid4()
        pid = uuid4()
        req = AccessRequest(
            operation=AccessOperation.VIEW,
            target_profile_id=pid,
            requester_id=uid,
            requester_role="family",
        )
        assert req.operation == AccessOperation.VIEW

    def test_invalid_role_pattern(self):
        with pytest.raises(ValidationError):
            AccessRequest(
                operation=AccessOperation.VIEW,
                target_profile_id=uuid4(),
                requester_id=uuid4(),
                requester_role="super_admin",
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            AccessRequest(
                operation=AccessOperation.VIEW,
                target_profile_id=uuid4(),
                requester_id=uuid4(),
                requester_role="family",
                extra="bad",
            )


class TestAccessDecision:
    def test_allowed(self):
        d = AccessDecision(allowed=True, visible_scope=VisibleScope.ALL_FIELDS)
        assert d.allowed is True
        assert d.denial_reason is None

    def test_denied(self):
        d = AccessDecision(allowed=False, visible_scope=VisibleScope.NOTHING, denial_reason="数据不存在")
        assert d.allowed is False
        assert d.denial_reason == "数据不存在"


# ===========================================================================
# ProfileCreate
# ===========================================================================


def _valid_profile_data(**overrides):
    data = {
        "birth_date": date(2019, 3, 15),
        "diagnosis_type": "ASD",
        "primary_behavior": "刻板行为",
    }
    data.update(overrides)
    return data


class TestProfileCreate:
    def test_valid_minimal(self):
        req = ProfileCreate(**_valid_profile_data())
        assert req.diagnosis_type == DiagnosisType.ASD
        assert req.sensory_features == []

    def test_missing_birth_date(self):
        with pytest.raises(ValidationError):
            ProfileCreate(diagnosis_type="ASD", primary_behavior="刻板行为")

    def test_future_birth_date(self):
        with pytest.raises(ValidationError):
            ProfileCreate(birth_date=date(2099, 1, 1), diagnosis_type="ASD", primary_behavior="刻板行为")

    def test_invalid_diagnosis_type(self):
        with pytest.raises(ValidationError):
            ProfileCreate(**_valid_profile_data(diagnosis_type="INVALID"))

    def test_with_sensory_features(self):
        req = ProfileCreate(
            **_valid_profile_data(
                sensory_features=["听觉敏感", "触觉敏感"],
                triggers=["噪音", "环境变化"],
            )
        )
        assert len(req.sensory_features) == 2
        assert len(req.triggers) == 2

    def test_sensory_features_too_many(self):
        with pytest.raises(ValidationError):
            ProfileCreate(**_valid_profile_data(sensory_features=["听觉敏感"] * 7))

    def test_nickname_too_long(self):
        with pytest.raises(ValidationError):
            ProfileCreate(**_valid_profile_data(nickname="a" * 11))

    def test_medication_notes_too_long(self):
        with pytest.raises(ValidationError):
            ProfileCreate(**_valid_profile_data(medication_notes="a" * 201))

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ProfileCreate(**_valid_profile_data(), extra="bad")


# ===========================================================================
# ProfileUpdate
# ===========================================================================


class TestProfileUpdate:
    def test_all_none(self):
        req = ProfileUpdate()
        assert req.nickname is None
        assert req.birth_date is None

    def test_partial_update(self):
        req = ProfileUpdate(nickname="小明")
        assert req.nickname == "小明"

    def test_future_birth_date(self):
        with pytest.raises(ValidationError):
            ProfileUpdate(birth_date=date(2099, 1, 1))

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ProfileUpdate(extra="bad")


# ===========================================================================
# ProfileResponse / ProfileListItem
# ===========================================================================


class TestProfileResponse:
    def test_valid(self):
        uid = uuid4()
        now = datetime.now(timezone.utc)
        resp = ProfileResponse(
            profile_id=uuid4(),
            birth_date=date(2019, 3, 15),
            age_range=AgeRange.AGE_7_12,
            diagnosis_type=DiagnosisType.ASD,
            primary_behavior=ProfileBehaviorType.STEREOTYPED,
            sensory_features=[SensoryFeature.AUDITORY_SENSITIVE],
            triggers=[Trigger.NOISE],
            is_default=True,
            caregiver_id=uid,
            created_at=now,
            updated_at=now,
        )
        assert resp.age_range == AgeRange.AGE_7_12


class TestProfileListItem:
    def test_valid(self):
        uid = uuid4()
        item = ProfileListItem(
            profile_id=uid,
            age_range=AgeRange.AGE_7_12,
            diagnosis_type=DiagnosisType.ASD,
            primary_behavior=ProfileBehaviorType.STEREOTYPED,
            is_default=True,
        )
        assert item.is_default is True


# ===========================================================================
# EventCreate / EventUpdate / EventResponse / EventListItem
# ===========================================================================


class TestEventCreate:
    def test_valid(self):
        req = EventCreate(
            event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            behavior_type=ProfileBehaviorType.MELTDOWN,
            severity_level=SeverityLevel.MODERATE,
            trigger_description="噪音触发",
            manifestation="哭闹不止",
            intervention_tried="安抚",
            intervention_result="逐渐平静",
        )
        assert req.behavior_type == ProfileBehaviorType.MELTDOWN

    def test_future_event_time(self):
        with pytest.raises(ValidationError):
            EventCreate(
                event_time=datetime(2099, 1, 1, tzinfo=timezone.utc),
                behavior_type=ProfileBehaviorType.MELTDOWN,
                severity_level=SeverityLevel.MODERATE,
                trigger_description="x", manifestation="x",
                intervention_tried="x", intervention_result="x",
            )

    def test_tags_too_many(self):
        with pytest.raises(ValidationError):
            EventCreate(
                event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                behavior_type=ProfileBehaviorType.MELTDOWN,
                severity_level=SeverityLevel.MODERATE,
                trigger_description="x", manifestation="x",
                intervention_tried="x", intervention_result="x",
                tags=["t1", "t2", "t3", "t4", "t5", "t6"],
            )

    def test_tag_empty_string(self):
        with pytest.raises(ValidationError):
            EventCreate(
                event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                behavior_type=ProfileBehaviorType.MELTDOWN,
                severity_level=SeverityLevel.MODERATE,
                trigger_description="x", manifestation="x",
                intervention_tried="x", intervention_result="x",
                tags=["  "],
            )

    def test_field_max_length(self):
        too_long = "x" * 2001
        with pytest.raises(ValidationError):
            EventCreate(
                event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                behavior_type=ProfileBehaviorType.MELTDOWN,
                severity_level=SeverityLevel.MODERATE,
                trigger_description=too_long,
                manifestation="x", intervention_tried="x", intervention_result="x",
            )


class TestEventUpdate:
    def test_partial(self):
        req = EventUpdate(trigger_description="新的触发描述")
        assert req.trigger_description == "新的触发描述"
        assert req.manifestation is None


class TestEventResponse:
    def test_valid(self):
        uid = uuid4()
        now = datetime.now(timezone.utc)
        resp = EventResponse(
            event_id=uid,
            profile_id=uid,
            recorded_by=uid,
            recorded_by_role="parent",
            event_time=now,
            behavior_type="情绪崩溃",
            severity_level="中",
            trigger_description="描述",
            manifestation="表现",
            intervention_tried="干预",
            intervention_result="结果",
            created_at=now,
            updated_at=now,
        )
        assert resp.is_professional is False


class TestEventListItem:
    def test_valid(self):
        uid = uuid4()
        now = datetime.now(timezone.utc)
        item = EventListItem(
            event_id=uid,
            event_time=now,
            behavior_type="情绪崩溃",
            severity_level="中",
            has_professional_note=False,
            created_at=now,
        )
        assert item.has_professional_note is False


# ===========================================================================
# calculate_age_range
# ===========================================================================


class TestCalculateAgeRange:
    def test_0_3(self):
        today = date.today()
        birth = date(today.year - 2, today.month, min(today.day, 28))
        assert calculate_age_range(birth) == AgeRange.AGE_0_3

    def test_4_6(self):
        today = date.today()
        birth = date(today.year - 5, today.month, min(today.day, 28))
        assert calculate_age_range(birth) == AgeRange.AGE_4_6

    def test_7_12(self):
        today = date.today()
        birth = date(today.year - 10, today.month, min(today.day, 28))
        assert calculate_age_range(birth) == AgeRange.AGE_7_12

    def test_13_18(self):
        today = date.today()
        birth = date(today.year - 15, today.month, min(today.day, 28))
        assert calculate_age_range(birth) == AgeRange.AGE_13_18

    def test_18_plus(self):
        today = date.today()
        birth = date(today.year - 25, today.month, min(today.day, 28))
        assert calculate_age_range(birth) == AgeRange.AGE_18_PLUS
