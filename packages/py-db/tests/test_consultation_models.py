"""应急域 ORM 模型单元测试（ADR-009 时刻分层目标态）。

覆盖四表结构：consultation_sessions / consultations / safety_cards / consultation_logs。
"""

from __future__ import annotations

from py_db.models.consultation import (
    Consultation,
    ConsultationLog,
    ConsultationSession,
    SafetyCard,
)
from py_schemas.enums import (
    BehaviorBucket,
    CrisisStage,
    FallbackSignal,
    MeltdownType,
    TurnType,
)


class TestConsultationSessionModel:
    def test_columns(self):
        cols = {c.name for c in ConsultationSession.__table__.columns}
        assert {
            "id", "user_id", "profile_id", "bucket", "crisis_stage",
            "meltdown_type", "created_at",
        } <= cols

    def test_table_name(self):
        assert ConsultationSession.__tablename__ == "consultation_sessions"

    def test_bucket_enum(self):
        assert ConsultationSession.__table__.c.bucket.type.enum_class is BehaviorBucket


class TestConsultationModel:
    def test_columns(self):
        cols = {c.name for c in Consultation.__table__.columns}
        assert {
            "id", "session_id", "turn_type", "behavior_description",
            "retrieved_case_ids", "generated_plan", "reply_text",
            "confidence_score", "sources", "disclaimer_served", "created_at",
        } <= cols

    def test_session_fk_cascade(self):
        fks = list(Consultation.__table__.c.session_id.foreign_keys)
        assert fks[0].column.table.name == "consultation_sessions"

    def test_turn_type_enum(self):
        assert Consultation.__table__.c.turn_type.type.enum_class is TurnType


class TestSafetyCardModel:
    def test_columns(self):
        cols = {c.name for c in SafetyCard.__table__.columns}
        assert {
            "id", "bucket", "crisis_stage", "title", "card_template",
            "review_status", "version", "created_at", "updated_at",
        } <= cols

    def test_stage_nullable_for_general_card(self):
        """crisis_stage 空为通用桶卡（智能应急咨询 §八）。"""
        assert SafetyCard.__table__.c.crisis_stage.nullable is True

    def test_bucket_nullable_for_universal_card(self):
        """bucket 空为 0 输入通用安全卡。"""
        assert SafetyCard.__table__.c.bucket.nullable is True


class TestConsultationLogModel:
    def test_columns(self):
        cols = {c.name for c in ConsultationLog.__table__.columns}
        assert {"id", "session_id", "event_type", "payload", "created_at"} <= cols


class TestEnumIntegrity:
    def test_enums_importable(self):
        assert MeltdownType.MELTDOWN.value == "meltdown"
        assert FallbackSignal.REDLINE_HIT.value == "redline_hit"
        assert CrisisStage.TRIGGER.value == "触发"
