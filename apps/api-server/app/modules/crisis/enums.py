"""CSLT-01 危机分级判定 — 枚举兼容性重导出。

CrisisLevel 和 BehaviorTypeCategory 的正式定义位于 py_schemas.enums.crisis_enums。
HIGH_RISK_TYPES frozenset 为本模块私有的辅助常量。
"""

from __future__ import annotations

from py_schemas.enums.crisis_enums import BehaviorTypeCategory, CrisisLevel

# 高危类型集合 —— 供 PreSelectionLayer 快速查找
HIGH_RISK_TYPES: frozenset[BehaviorTypeCategory] = frozenset({
    BehaviorTypeCategory.SELF_INJURY,
    BehaviorTypeCategory.AGGRESSION,
    BehaviorTypeCategory.ELOPEMENT,
    BehaviorTypeCategory.MEDICATION,
})

__all__ = ["CrisisLevel", "BehaviorTypeCategory", "HIGH_RISK_TYPES"]
