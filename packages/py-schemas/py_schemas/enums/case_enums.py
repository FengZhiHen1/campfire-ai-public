"""CASE-01 案例录入管理 — 枚举定义。

所有枚举值与 docs/contracts/CASE-01/ 下的 JSON Schema 契约一致。
枚举值使用字符串类型，可直接存数据库和序列化。

契约引用：
- CaseStatus: docs/contracts/CASE-01/CaseStatus.json
- SourceType: docs/contracts/CASE-01/SourceType.json
- BehaviorType: docs/contracts/CASE-01/BehaviorType.json
- SeverityLevel: docs/contracts/CASE-01/SeverityLevel.json
- SceneType: docs/contracts/CASE-01/SceneType.json
- EvidenceLevel: docs/contracts/CASE-01/EvidenceLevel.json
- FamilyDisplayCategory: docs/contracts/CASE-01/FamilyDisplayCategory.json
"""

from __future__ import annotations

from enum import StrEnum


class CaseStatus(StrEnum):
    """案例生命周期中的持久化状态。

    四个状态：
    - draft: 草稿（仅作者可见）
    - pending_review: 提交后进入审核流程
    - approved: 审核通过终态（由 CASE-03 管理）
    - rejected: 被审核驳回后可编辑重新提交

    approved 为 CASE-03 扩展的状态，CASE-01 设计文档 §1.4 已明确预留。
    """

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class SourceType(StrEnum):
    """案例的获取渠道标识。"""

    EXPERT_WRITTEN = "专家撰写"
    INSTITUTION_DESENSITIZED = "机构脱敏"
    TICKET_DEPOSIT = "工单沉淀"


class BehaviorType(StrEnum):
    """案例所涉及的核心行为问题分类。"""

    SELF_INJURY = "自伤"
    AGGRESSION = "攻击"
    STEREOTYPY = "刻板"
    ELOPEMENT = "逃跑"
    MELTDOWN = "情绪崩溃"
    OTHER = "其他"


class SeverityLevel(StrEnum):
    """案例对应的行为严重程度等级。"""

    MILD = "轻度"
    MODERATE = "中度"
    SEVERE = "重度"


class SceneType(StrEnum):
    """干预事件发生的环境场所分类。"""

    HOME = "家庭"
    SCHOOL = "学校"
    PUBLIC = "公共场合"
    INSTITUTION = "机构"
    ANY = "不限"


class EvidenceLevel(StrEnum):
    """案例干预方法的证据强度等级。"""

    NCAEP = "NCAEP循证实践"
    INSTITUTION_EXPERIENCE = "机构经验总结"
    CASE_OBSERVATION = "个案观察记录"


class FamilyDisplayCategory(StrEnum):
    """家属端展示大类枚举。"""

    ENVIRONMENT_ADJUSTMENT = "环境调整"
    COMMUNICATION_ALTERNATIVE = "沟通替代"
    BEHAVIOR_SHAPING = "行为塑造"
    CRISIS_SAFETY = "危机安全"
    SOCIAL_GUIDANCE = "社交引导"
    SELF_MANAGEMENT = "自我管理"


__all__ = [
    "CaseStatus",
    "SourceType",
    "BehaviorType",
    "SeverityLevel",
    "SceneType",
    "EvidenceLevel",
    "FamilyDisplayCategory",
]
