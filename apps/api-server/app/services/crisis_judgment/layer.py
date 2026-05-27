"""CSLT-01 危机分级判定 — JudgmentLayer 抽象基类。

定义所有判定层必须实现的接口。三个具体实现：
    PreSelectionLayer   前置行为类型判定
    RuleEngineLayer     规则引擎关键词匹配
    LLMReviewLayer      LLM 精调复审
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import (
    CrisisJudgmentRequest,
    JudgmentLayerResult,
)


class JudgmentLayer(ABC):
    """判定层抽象基类。

    所有判定层必须实现 judge() 方法，接收完整的 CrisisJudgmentRequest，
    返回该层的判定结果 JudgmentLayerResult。
    """

    @abstractmethod
    async def judge(self, request: CrisisJudgmentRequest) -> JudgmentLayerResult:
        """执行本层的判定逻辑。

        Args:
            request: 完整的危机分级判定请求。

        Returns:
            本层的判定结果，包含层标识、等级、触发规则编号和详情。
        """
        ...
