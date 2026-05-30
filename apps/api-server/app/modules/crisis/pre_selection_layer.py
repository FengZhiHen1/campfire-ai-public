"""CSLT-01 危机分级判定 — PreSelectionLayer 前置行为类型判定层。

检查 behavior_type_selection 中是否包含高危类型。若命中任意高危类型
（SELF_INJURY / AGGRESSION / ELOPEMENT / MEDICATION），直接判定为重度，
跳过后续所有判定层（规则引擎和 LLM 复审）。
"""

from __future__ import annotations

from .enums import (
    HIGH_RISK_TYPES,
    BehaviorTypeCategory,
    CrisisLevel,
)
from .layer import JudgmentLayer
from .models import (
    CrisisJudgmentRequest,
    JudgmentLayerResult,
)


class PreSelectionLayer(JudgmentLayer):
    """前置行为类型判定层。

    前置选择命中高危后，Pipeline 直接输出 severe 并跳过后续两层。
    此为安全底线 —— 任何情况下不可让规则引擎或 LLM 复审覆盖前置判定的重度结论。
    """

    async def judge(self, request: CrisisJudgmentRequest) -> JudgmentLayerResult:
        """执行前置行为类型判定。

        遍历 behavior_type_selection，若任意元素命中高危集合，
        则返回 level=severe。

        Args:
            request: 危机分级判定请求。

        Returns:
            前置选择层的判定结果。
        """
        checked_types: list[str] = [t.value for t in request.behavior_type_selection]
        high_risk_hit: bool = any(
            t in HIGH_RISK_TYPES for t in request.behavior_type_selection
        )

        if high_risk_hit:
            return JudgmentLayerResult(
                layer_name="PreSelectionLayer",
                level=CrisisLevel.SEVERE,
                trigger_rule_id=None,
                details={
                    "checked_types": checked_types,
                    "high_risk_hit": True,
                },
            )

        return JudgmentLayerResult(
            layer_name="PreSelectionLayer",
            level=None,
            trigger_rule_id=None,
            details={
                "checked_types": checked_types,
                "high_risk_hit": False,
            },
        )
