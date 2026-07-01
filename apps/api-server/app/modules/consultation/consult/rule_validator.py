"""CSLT-05 置信度后校验 — 规则校验器。

对方案全文执行结构完整性和来源引用覆盖率两维度的确定量化校验。
不依赖外部服务，纯文本分析，O(n) 复杂度。

计分逻辑（参见落地规范 §1.5 步骤 5）：
- 结构完整性（50%）：扫描四个预设段落标题的存在性
- 来源引用覆盖率（50%）：提取 [N] 引用标记并校验有效性

最终分数归一化到 0-1 区间。
"""

from __future__ import annotations

import re

# ===========================================================================
# 常量
# ===========================================================================

# 四段式段落标题（CSLT-03 System Prompt 约束的输出格式）
_SECTION_HEADERS: tuple[str, str, str, str] = (
    "### 一、即时安全干预动作",
    "### 二、情绪安抚话术",
    "### 三、后续观察指标",
    "### 四、就医判断标准",
)

# 引用标记正则：[N] 格式，N 为正整数
_CITATION_PATTERN: re.Pattern[str] = re.compile(r"\[(\d+)\]")

# 引用覆盖率目标阈值：当覆盖率 >= 0.8 时得满分
_CITATION_COVERAGE_TARGET: float = 0.8

# 规则的各维度权重
_STRUCTURE_WEIGHT: float = 0.5
_CITATION_WEIGHT: float = 0.5


# ===========================================================================
# RuleValidator
# ===========================================================================


class RuleValidator:
    """规则校验器。

    提供对应急方案文本的确定性量化评估——结构完整性 + 来源引用覆盖率。
    不做外部服务调用，所有计算在进程内完成。

    Usage:
        validator = RuleValidator()
        score = validator.compute_rule_score(plan_text, source_list)
    """

    def compute_rule_score(
        self,
        plan_text: str,
        source_list: list[str],
    ) -> float:
        """计算规则校验的复合分数。

        结构完整性（50%）+ 来源引用覆盖率（50%），归一化到 0-1。

        若 plan_text 为空字符串，返回 0.0 而非抛出异常。

        Args:
            plan_text: 方案全文。
            source_list: 来源引用清单。

        Returns:
            float: 规则校验分数，0.0-1.0 区间。
        """
        # 边界：空文本
        if not plan_text:
            return 0.0

        # 维度 1：结构完整性
        structure_score: float = self._compute_structure_score(plan_text)

        # 维度 2：来源引用覆盖率
        citation_score: float = self._compute_citation_score(plan_text, source_list)

        # 复合评分并归一化
        raw_score: float = structure_score * _STRUCTURE_WEIGHT + citation_score * _CITATION_WEIGHT
        return round(max(0.0, min(1.0, raw_score)), 4)

    # ------------------------------------------------------------------
    # 维度 1：结构完整性
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_structure_score(plan_text: str) -> float:
        """计算四段式结构完整性得分。

        扫描 plan_text 是否包含四个预定义段落标题。
        每缺失一个段落扣除 25 分。
        得分 = (包含的段落数 / 4)。

        Args:
            plan_text: 方案全文。

        Returns:
            float: 结构完整性得分，0.0-1.0 区间。
        """
        included: int = 0
        for header in _SECTION_HEADERS:
            if header in plan_text:
                included += 1
        return included / 4.0

    # ------------------------------------------------------------------
    # 维度 2：来源引用覆盖率
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_citation_score(
        plan_text: str,
        source_list: list[str],
    ) -> float:
        """计算来源引用覆盖率得分。

        提取 plan_text 中所有 [N] 格式的引用标记。
        有效引用：N 为正整数且在 [1, len(source_list)] 范围内。
        覆盖率 = 去重有效引用数 / max(len(source_list), 1)。
        得分 = min(覆盖率 / 0.8, 1.0)。

        Args:
            plan_text: 方案全文。
            source_list: 来源引用清单。

        Returns:
            float: 来源引用覆盖率得分，0.0-1.0 区间。
        """
        # 提取所有 [N] 引用中的 N 值
        matches: list[str] = _CITATION_PATTERN.findall(plan_text)
        if not matches:
            return 0.0

        max_index: int = max(len(source_list), 1)

        # 去重并统计有效引用数
        valid_citations: set[int] = set()
        for num_str in matches:
            try:
                n = int(num_str)
            except ValueError:
                continue
            if 1 <= n <= max_index:
                valid_citations.add(n)

        # 覆盖率
        coverage: float = len(valid_citations) / max_index
        # 达到 80% 覆盖率即满分
        return min(coverage / _CITATION_COVERAGE_TARGET, 1.0)


# ===========================================================================
# 模块级便捷函数
# ===========================================================================


def compute_rule_score(
    plan_text: str,
    source_list: list[str],
) -> float:
    """计算规则校验分数（模块级便捷函数）。

    等价于 RuleValidator().compute_rule_score(plan_text, source_list)。

    Args:
        plan_text: 方案全文。
        source_list: 来源引用清单。

    Returns:
        float: 规则校验分数，0.0-1.0 区间。
    """
    validator = RuleValidator()
    return validator.compute_rule_score(plan_text, source_list)


__all__ = [
    "RuleValidator",
    "compute_rule_score",
]
