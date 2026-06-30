"""app.modules.crisis — 危机分级判定模块 (CSLT-01)。

提供两层危机等级判定服务：
1. 前置行为类型选择 — 高危类型（自伤/攻击）命中直接判重度
2. 规则引擎关键词匹配 — AC 自动机扫描 + 否定词过滤 + 档案叠加规则

LLM 精调复审已从默认阻塞链路中移除，以降低咨询首字节延迟。
如需后台审计，可单独导入 llm_review_layer.py 中的 LLMReviewLayer。

核心类：
  - CrisisJudgmentPipeline: 危机分级判定管线契约（ABC 模板方法骨架，crisis_contract.py）
  - CrisisJudgmentPipelineImpl: 实现 CrisisJudgmentPipeline 契约（pipeline.py）
  - JudgmentLayer: 单层判定接口契约（crisis_contract.py）
  - PreSelectionLayer: 前置行为类型判定层实现（pre_selection_layer.py）
  - RuleEngineLayer: 规则引擎关键词匹配层实现（rule_engine_layer.py）
  - KeywordMatcher: 关键词匹配器 Protocol 接口（protocols.py）

外部接口：
  - judge_crisis(request, config) -> CrisisJudgmentResult
  - CrisisJudgmentRequest: 判定请求模型
  - CrisisJudgmentResult: 判定结果模型
  - CrisisLevel: 危机等级枚举 (mild / moderate / severe)
  - BehaviorTypeCategory: 行为类型分类枚举

Usage:
    from app.modules.crisis import judge_crisis
    from app.modules.crisis import (
        CrisisJudgmentRequest,
        CrisisJudgmentResult,
        BehaviorTypeCategory,
    )

    request = CrisisJudgmentRequest(
        behavior_type_selection=[BehaviorTypeCategory.SELF_INJURY],
        behavior_description="患者从下午3点开始持续撞头...",
    )
    result = await judge_crisis(request)
    print(result.final_level)  # 'severe'
"""

from __future__ import annotations

from .crisis_contract import CrisisJudgmentPipeline, JudgmentLayer
from .enums import BehaviorTypeCategory, CrisisLevel
from .exceptions import (
    CrisisJudgmentError,
    KeywordDictLoadError,
    LLMReviewTimeoutError,
)
from .models import CrisisJudgmentRequest, CrisisJudgmentResult, JudgmentLayerResult
from .pipeline import CrisisJudgmentPipelineImpl
from .protocols import KeywordMatcher
from .service import judge_crisis

__all__ = [
    # 服务入口
    "judge_crisis",
    # 契约类
    "CrisisJudgmentPipeline",
    "CrisisJudgmentPipelineImpl",
    "JudgmentLayer",
    "KeywordMatcher",
    # 数据模型
    "CrisisJudgmentRequest",
    "CrisisJudgmentResult",
    "JudgmentLayerResult",
    # 枚举
    "CrisisLevel",
    "BehaviorTypeCategory",
    # 异常
    "CrisisJudgmentError",
    "LLMReviewTimeoutError",
    "KeywordDictLoadError",
]
