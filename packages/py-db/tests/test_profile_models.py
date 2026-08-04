"""档案四层 ORM 模型单元测试（ADR-010 目标态）。

覆盖：Profile（身份基础+危机预案字段组）、EventLog（ABC 结构）、
ProfessionalNote、ProfileAccess（替代 TeacherLink）。
"""

from __future__ import annotations

from py_db.models.profiles import EventLog, ProfessionalNote, Profile, ProfileAccess
from py_schemas.enums import (
    AccessRole,
    AccessStatus,
    AntecedentCategory,
    BehaviorBucket,
    IntensityLevel,
    Outcome,
    RecordedByRole,
)


class TestProfileModel:
    def test_identity_layer_columns(self):
        cols = {c.name for c in Profile.__table__.columns}
        # 身份基础层
        assert {
            "profile_id", "caregiver_id", "nickname", "birth_date",
            "diagnosis_type", "primary_behavior", "comorbidities",
            "sensory_profile", "triggers", "is_default",
        } <= cols

    def test_crisis_plan_layer_columns(self):
        cols = {c.name for c in Profile.__table__.columns}
        # 危机预案层（应急槽位唯一来源）
        assert {
            "physical_description", "familiar_places", "water_risk",
            "soothing_items", "avoid_list", "communication_methods",
            "emergency_contacts", "medication_notes",
        } <= cols

    def test_abolished_columns_removed(self):
        """旧字段废除（language_level/medication 归位危机预案层）。"""
        cols = {c.name for c in Profile.__table__.columns}
        assert "language_level" not in cols

    def test_primary_behavior_unified_enum(self):
        """primary_behavior 与应急桶共用统一枚举（ADR-010 第 7 条）。"""
        assert Profile.__table__.c.primary_behavior.type.enum_class is BehaviorBucket


class TestEventLogModel:
    def test_abc_columns(self):
        """ABC 结构化字段齐全。"""
        cols = {c.name for c in EventLog.__table__.columns}
        assert {
            "event_id", "profile_id", "recorded_by", "recorded_by_role",
            "event_time", "is_quick_log", "behavior_type", "behavior_form",
            "intensity", "duration", "setting", "activity", "people_present",
            "physical_state", "antecedent_category", "trigger_description",
            "consequence", "reaction", "outcome", "function_hypothesis",
            "manifestation", "note", "tags", "created_at",
        } <= cols

    def test_abolished_columns(self):
        """旧自由文本必填字段废除（intervention_tried/intervention_result/severity_level）。"""
        cols = {c.name for c in EventLog.__table__.columns}
        assert "intervention_tried" not in cols
        assert "intervention_result" not in cols
        assert "severity_level" not in cols

    def test_behavior_type_unified_enum(self):
        assert EventLog.__table__.c.behavior_type.type.enum_class is BehaviorBucket


class TestProfessionalNoteModel:
    def test_columns(self):
        cols = {c.name for c in ProfessionalNote.__table__.columns}
        assert {
            "note_id", "event_id", "author_id", "assessment",
            "recommended_action", "evidence_basis", "function_hypothesis", "created_at",
        } <= cols

    def test_event_fk(self):
        fks = list(ProfessionalNote.__table__.c.event_id.foreign_keys)
        assert fks[0].column.table.name == "event_logs"


class TestProfileAccessModel:
    def test_columns(self):
        cols = {c.name for c in ProfileAccess.__table__.columns}
        assert {
            "access_id", "profile_id", "user_id", "role",
            "status", "created_by", "created_at", "revoked_at",
        } <= cols

    def test_enums(self):
        assert ProfileAccess.__table__.c.role.type.enum_class is AccessRole
        assert ProfileAccess.__table__.c.status.type.enum_class is AccessStatus


class TestEnumValues:
    def test_intensity_four_levels(self):
        assert {e.value for e in IntensityLevel} == {"低", "中", "高", "严重"}

    def test_antecedent_categories(self):
        assert AntecedentCategory.INSTRUCTION == "给指令"
        assert len(AntecedentCategory) == 8

    def test_recorded_by_role(self):
        assert RecordedByRole.PARENT == "parent"
        assert RecordedByRole.VOLUNTEER == "volunteer"

    def test_outcome(self):
        assert Outcome.EFFECTIVE == "有效"
