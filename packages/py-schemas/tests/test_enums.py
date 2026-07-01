"""CASE-01 案例枚举定义 — 单元测试。

测试 7 个案例相关枚举的值、成员数量和属性。
"""

from __future__ import annotations

from py_schemas.enums.case_enums import (
    BehaviorType,
    CaseStatus,
    EvidenceLevel,
    FamilyDisplayCategory,
    SceneType,
    SeverityLevel,
    SourceType,
)


class TestCaseStatus:
    def test_all_statuses_exist(self):
        assert CaseStatus.DRAFT == "draft"
        assert CaseStatus.PENDING_REVIEW == "pending_review"
        assert CaseStatus.APPROVED == "approved"
        assert CaseStatus.REJECTED == "rejected"

    def test_member_count(self):
        assert len(CaseStatus) == 4


class TestSourceType:
    def test_all_sources_exist(self):
        assert SourceType.EXPERT_WRITTEN == "专家撰写"
        assert SourceType.INSTITUTION_DESENSITIZED == "机构脱敏"
        assert SourceType.TICKET_DEPOSIT == "工单沉淀"


class TestBehaviorType:
    def test_all_behaviors_exist(self):
        assert BehaviorType.SELF_INJURY == "自伤"
        assert BehaviorType.AGGRESSION == "攻击"
        assert BehaviorType.STEREOTYPY == "刻板"
        assert BehaviorType.ELOPEMENT == "逃跑"
        assert BehaviorType.MELTDOWN == "情绪崩溃"
        assert BehaviorType.OTHER == "其他"

    def test_member_count(self):
        assert len(BehaviorType) == 6


class TestSeverityLevel:
    def test_all_levels_exist(self):
        assert SeverityLevel.MILD == "轻度"
        assert SeverityLevel.MODERATE == "中度"
        assert SeverityLevel.SEVERE == "重度"


class TestSceneType:
    def test_all_scenes_exist(self):
        assert SceneType.HOME == "家庭"
        assert SceneType.SCHOOL == "学校"
        assert SceneType.PUBLIC == "公共场合"
        assert SceneType.INSTITUTION == "机构"
        assert SceneType.ANY == "不限"


class TestEvidenceLevel:
    def test_all_levels_exist(self):
        assert EvidenceLevel.NCAEP == "NCAEP循证实践"
        assert EvidenceLevel.INSTITUTION_EXPERIENCE == "机构经验总结"
        assert EvidenceLevel.CASE_OBSERVATION == "个案观察记录"


class TestFamilyDisplayCategory:
    def test_all_categories_exist(self):
        assert FamilyDisplayCategory.ENVIRONMENT_ADJUSTMENT == "环境调整"
        assert FamilyDisplayCategory.COMMUNICATION_ALTERNATIVE == "沟通替代"
        assert FamilyDisplayCategory.BEHAVIOR_SHAPING == "行为塑造"
        assert FamilyDisplayCategory.CRISIS_SAFETY == "危机安全"
        assert FamilyDisplayCategory.SOCIAL_GUIDANCE == "社交引导"
        assert FamilyDisplayCategory.SELF_MANAGEMENT == "自我管理"


def test_ncaep_ebp_labels():
    from py_schemas.cases import NCAEP_EBP_LABELS

    assert isinstance(NCAEP_EBP_LABELS, set)
    assert "强化" in NCAEP_EBP_LABELS
    assert "消退" in NCAEP_EBP_LABELS
    assert "任务分析" in NCAEP_EBP_LABELS
    assert len(NCAEP_EBP_LABELS) >= 27
