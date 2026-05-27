"""consult — 智能应急咨询服务模块。

为 CSLT-08 咨询编排逻辑提供完整的咨询服务能力：
- RAG 语义检索（CSLT-02）
- 应急方案生成（CSLT-03）
- 置信度后校验（CSLT-05）

对外暴露的公共接口：
    validate_confidence(input, background_tasks) -> ConfidenceValidationOutput
    compute_rule_score(plan_text, source_list) -> float
    KeywordScanner — AC 自动机关键词扫描器
    RuleValidator — 规则校验器
"""

from __future__ import annotations

from .confidence_validator import validate_confidence
from .keyword_scanner import KeywordScanner
from .rule_validator import RuleValidator, compute_rule_score

__all__ = [
    "validate_confidence",
    "compute_rule_score",
    "KeywordScanner",
    "RuleValidator",
]
