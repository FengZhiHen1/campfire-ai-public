"""consult — 智能应急咨询服务子域（CSLT-05 置信度后校验）。

提供 3 大能力：
1. 关键词安检：AC 自动机 O(n) 零 LLM 调用高危关键词扫描
2. 置信度复合评分：LLM 自评估 50% + 规则校验 50%
3. 工单触发：高危场景自动创建工单（含指数退避重试）

核心类：
  - ConfidenceValidatorImpl: 实现 BaseConfidenceValidator 契约，置信度校验
  - KeywordScanner: AC 自动机关键词扫描器（单例，与 CSLT-01 共享词库）
  - RuleValidator: 规则校验器（结构完整性 + 来源引用覆盖率）

外部接口：
  - validate_confidence(input, background_tasks) -> ConfidenceValidationOutput
  - compute_rule_score(plan_text, source_list) -> float
  - KeywordScanner.get_instance() -> KeywordScanner

Usage:
    from app.modules.consultation.consult import validate_confidence, KeywordScanner, RuleValidator
"""

from __future__ import annotations

from .confidence_validator import ConfidenceValidatorImpl, validate_confidence
from .keyword_scanner import KeywordScanner
from .rule_validator import RuleValidator, compute_rule_score
from .validation_contract import BaseConfidenceValidator

__all__ = [
    # 契约
    "BaseConfidenceValidator",
    # 实现
    "ConfidenceValidatorImpl",
    # 实现接口
    "validate_confidence",
    "compute_rule_score",
    "KeywordScanner",
    "RuleValidator",
]
