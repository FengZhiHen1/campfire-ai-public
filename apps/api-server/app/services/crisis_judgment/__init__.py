"""危机分级判定模块 (CSLT-01).

为 csLT-08（咨询编排逻辑）提供三层递进危机等级判定服务。
判定流程：前置行为类型选择 -> 规则引擎关键词匹配 -> LLM 精调复审。

对外暴露的公共接口：
    judge_crisis(request, config) -> CrisisJudgmentResult
"""

from __future__ import annotations

from .enums import BehaviorTypeCategory, CrisisLevel
from .models import CrisisJudgmentRequest, CrisisJudgmentResult, JudgmentLayerResult
from .service import judge_crisis

__all__ = [
    "judge_crisis",
    "CrisisJudgmentRequest",
    "CrisisJudgmentResult",
    "JudgmentLayerResult",
    "CrisisLevel",
    "BehaviorTypeCategory",
]
