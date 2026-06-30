"""CSLT-01 危机分级判定 — 简化合并策略。

当前危机判定仅包含两层：
  - PreSelectionLayer（前置行为类型判定）
  - RuleEngineLayer（关键词 + 档案叠加规则）

合并策略：
  - PreSelection 命中 severe → severe
  - RuleEngine 命中 severe → severe
  - RuleEngine 命中 moderate → moderate
  - 其余 → mild
"""

from __future__ import annotations

from .enums import CrisisLevel
from .models import JudgmentContext


def merge(context: JudgmentContext) -> CrisisLevel:
    """合并两层判定结果。

    任意一层判 severe 即为 severe；否则取 RuleEngine 的非空等级；
    都未命中则返回 mild。

    Args:
        context: Pipeline 运行时上下文，已包含 PreSelectionLayer 与 RuleEngineLayer 结果。

    Returns:
        最终危机等级。
    """
    pre_level: CrisisLevel | None = None
    rule_level: CrisisLevel | None = None

    for source in context.sources:
        if source.layer_name == "PreSelectionLayer":
            pre_level = source.level
        elif source.layer_name == "RuleEngineLayer":
            rule_level = source.level

    if pre_level == CrisisLevel.SEVERE or rule_level == CrisisLevel.SEVERE:
        return CrisisLevel.SEVERE
    if rule_level == CrisisLevel.MODERATE:
        return CrisisLevel.MODERATE
    if pre_level == CrisisLevel.MODERATE:
        return CrisisLevel.MODERATE
    return CrisisLevel.MILD


__all__ = ["merge"]
