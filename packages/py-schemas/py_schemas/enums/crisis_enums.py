# @contract
"""CSLT-01 危机分级判定 — 枚举定义。

所有枚举值与 docs/contracts/CSLT-01/ 下的 JSON Schema 契约一致。
枚举值使用字符串类型，可直接存数据库和序列化。

契约引用：
- CrisisLevel: docs/contracts/CSLT-01/CrisisLevel.json
- BehaviorTypeCategory: docs/contracts/CSLT-01/BehaviorTypeCategory.json
"""

from __future__ import annotations

from enum import StrEnum


class CrisisLevel(StrEnum):
    """危机等级枚举。

    三个等级分别对应：
        mild:     轻度（建议观察）
        moderate: 中度（需干预）
        severe:  重度（需紧急响应）
    """

    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


class BehaviorTypeCategory(StrEnum):
    """行为类型分类枚举。

    用于前置行为类型选择（多选），共 7 类预设选项。
    高危类型（命中即判定重度）：
        SELF_INJURY      自伤
        AGGRESSION       攻击
        ELOPEMENT        走失
        MEDICATION       用药

    非高危类型：
        EMOTIONAL_MELTDOWN 情绪崩溃
        STEREOTYPY         刻板行为
        OTHER              其他
    """

    # ---- 高危类型 ----
    SELF_INJURY = "SELF_INJURY"
    AGGRESSION = "AGGRESSION"
    ELOPEMENT = "ELOPEMENT"
    MEDICATION = "MEDICATION"

    # ---- 非高危类型 ----
    EMOTIONAL_MELTDOWN = "EMOTIONAL_MELTDOWN"
    STEREOTYPY = "STEREOTYPY"
    OTHER = "OTHER"
