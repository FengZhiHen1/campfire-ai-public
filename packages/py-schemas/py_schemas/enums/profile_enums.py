# @contract
"""档案域枚举定义（ADR-010 档案四层与 ABC 标准化目标态）。

事实源：docs/技术设计/机制/个性化档案库/数据模型.md §1。
- 行为类型统一枚举复用 BehaviorBucket（应急桶为其直接子集）
- ABC 事件结构化枚举：强度 4 级 / 前事分类 / 身体状态 / 后果反应 / 功能假设预留
"""

from __future__ import annotations

from enum import StrEnum


class IntensityLevel(StrEnum):
    """事件强度 4 级（ADR-010 破坏性变更：替代旧 3 级轻/中/重）。"""

    LOW = "低"
    MEDIUM = "中"
    HIGH = "高"
    SEVERE = "严重"


class AntecedentCategory(StrEnum):
    """前事预置分类（A.4 结构化 ABC 的 A）。"""

    INSTRUCTION = "给指令"
    TRANSITION = "转换"
    DENIED = "被拒绝"
    SENSORY = "感觉刺激"
    SOCIAL = "社交"
    ROUTINE_CHANGE = "常规改变"
    PHYSICAL_DISCOMFORT = "躯体不适"
    UNKNOWN = "不明"


class PhysicalState(StrEnum):
    """身体状态（多选）。"""

    HUNGRY = "饿"
    TIRED = "困"
    SICK = "病"
    MENSTRUAL = "生理期"
    NONE = "无"


class EventSetting(StrEnum):
    """发生场景（含工作场所/托养机构——全生命周期覆盖）。"""

    HOME = "家庭"
    SCHOOL = "学校"
    PUBLIC = "公共场合"
    INSTITUTION = "机构"
    WORKPLACE = "工作场所"
    CARE_FACILITY = "托养机构"


class Outcome(StrEnum):
    """干预效果结构标记（应急注入加权与槽位推导兜底依据）。"""

    EFFECTIVE = "有效"
    PARTIAL = "部分有效"
    INEFFECTIVE = "无效"


class FunctionHypothesis(StrEnum):
    """功能假设（QABF 预留枚举，填表交互延至 M5）。"""

    ATTENTION = "注意"
    ESCAPE = "逃避"
    TANGIBLE = "实物"
    AUTOMATIC = "自动强化"
    PHYSICAL = "躯体不适"


class Comorbidity(StrEnum):
    """精神共病（多选）。"""

    ANXIETY = "焦虑"
    DEPRESSION = "抑郁"
    ADHD = "ADHD"
    EPILEPSY = "癫痫"
    OTHER = "其他"
    NONE = "无"
    UNKNOWN = "不详"


class CommunicationMethod(StrEnum):
    """沟通方式（语言水平 + AAC/视觉支持，多选）。"""

    NO_LANGUAGE = "无语言"
    SINGLE_WORD = "单字词"
    SHORT_PHRASES = "短句"
    CONVERSATIONAL = "可对话"
    AAC = "AAC 辅助沟通"
    VISUAL_SUPPORT = "视觉提示卡"


class AccessRole(StrEnum):
    """档案关联角色（ProfileAccess.role——受邀协作方）。"""

    TEACHER = "teacher"
    EXPERT = "expert"
    VOLUNTEER = "volunteer"


class AccessStatus(StrEnum):
    """关联状态（家属可随时单方面解除，立即失去访问入口）。"""

    ACTIVE = "active"
    REVOKED = "revoked"


class RecordedByRole(StrEnum):
    """事件记录人角色（老师/专家不直接新增事件，以 Professional Note 挂载）。"""

    PARENT = "parent"
    VOLUNTEER = "volunteer"


class EvidenceBasis(StrEnum):
    """专业评估依据。"""

    NCAEP = "NCAEP EBP"
    INSTITUTIONAL = "机构经验"
    CASE_OBSERVATION = "个案观察"


__all__ = [
    "IntensityLevel",
    "AntecedentCategory",
    "PhysicalState",
    "EventSetting",
    "Outcome",
    "FunctionHypothesis",
    "Comorbidity",
    "CommunicationMethod",
    "AccessRole",
    "AccessStatus",
    "RecordedByRole",
    "EvidenceBasis",
]
