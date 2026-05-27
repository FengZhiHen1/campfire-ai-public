"""CSLT-01 危机分级判定 — MERGE_MATRIX 二维查找表。

定义"宁升勿降"合并策略的 7x3 二维查找表。
行索引 = 规则引擎等级，列索引 = LLM 复审等级。
"""

from __future__ import annotations

from .enums import CrisisLevel

# ---------------------------------------------------------------------------
# MERGE_MATRIX 二维查找表
# ---------------------------------------------------------------------------
# 行（第一维）：规则引擎判定等级
# 列（第二维）：LLM 复审判定等级
# 值：最终合并等级
#
# 核心策略——"宁升勿降"：
#   severe + any      = severe（任何一层判重度即为重度）
#   moderate + severe = severe（LLM 可升级规则引擎等级）
#   severe + mild     = severe（LLM 不可降级规则引擎等级）
#   mild + null       = mild （规则引擎未命中且 LLM 跳过/超时）
#
# 键值编码：
#   "severe"    → 2
#   "moderate"  → 1
#   "mild"      → 0
#   None/跳过    → 不参与合并（在代码中特殊处理）
# ---------------------------------------------------------------------------

_LEVEL_ORDER: dict[str, int] = {
    CrisisLevel.MILD.value: 0,
    CrisisLevel.MODERATE.value: 1,
    CrisisLevel.SEVERE.value: 2,
}

# 构建 3x3 矩阵：MERGE_MATRIX[rule_idx][llm_idx] = result_level
# 使用 int 索引而非字符串键以实现 O(1) 查找
_MATRIX: list[list[str]] = [
    # LLM: mild, moderate, severe
    ["mild", "moderate", "severe"],  # RuleEngine: mild
    ["moderate", "moderate", "severe"],  # RuleEngine: moderate
    ["severe", "severe", "severe"],  # RuleEngine: severe
]


def lookup(
    rule_level: CrisisLevel | None,
    llm_level: CrisisLevel | None,
) -> CrisisLevel:
    """执行二维查找表合并。

    按"宁升勿降"策略合并规则引擎和 LLM 复审的判定等级。
    None 等级（该层未命中/跳过/降级）在查找前被映射为 mild。

    Args:
        rule_level: 规则引擎判定的等级，None 表示未命中或跳过。
        llm_level: LLM 复审判定的等级，None 表示未命中、跳过或超时。

    Returns:
        合并后的最终危机等级。

    Raises:
        KeyError: 不应出现的组合（代码 bug 保护）。
    """
    rule_idx = _LEVEL_ORDER.get(
        rule_level.value if rule_level else "mild", 0
    )
    llm_idx = _LEVEL_ORDER.get(
        llm_level.value if llm_level else "mild", 0
    )

    try:
        result = _MATRIX[rule_idx][llm_idx]
        return CrisisLevel(result)
    except (IndexError, ValueError) as exc:
        raise KeyError(
            f"Unexpected MERGE_MATRIX combination: "
            f"rule={rule_level!r}, llm={llm_level!r}"
        ) from exc
