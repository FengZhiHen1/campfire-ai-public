"""CSLT-01 危机分级判定 — 内部数据模型 + 共享模型重导出。

对外契约模型（CrisisJudgmentRequest / CrisisJudgmentResult / JudgmentLayerResult）
的正式定义位于 py_schemas.crisis。

本模块保留仅 Pipeline 内部使用的类型：
    PatientProfileSnapshot 患者档案快照（内部占位，PROF-02 尚未落地）
    JudgmentContext        Pipeline 运行时上下文（内部使用）
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from py_schemas.crisis import (
    CrisisJudgmentRequest,
    CrisisJudgmentResult,
    JudgmentLayerResult,
)
from py_schemas.enums.crisis_enums import CrisisLevel


# ============================================================================
# PatientProfileSnapshot（内部类型，非对外契约）
# ============================================================================


class PatientProfileSnapshot(BaseModel):
    """患者档案上下文快照 —— 由 PROF-02 注入。

    PROF-02 尚未落地，当前为占位定义。
    实际类型由 PROF-02 在未来定义完整 Schema，CSLT-01 仅消费不定义。
    """

    model_config = ConfigDict(extra="forbid")

    diagnosis_type: str | None = Field(
        default=None,
        description="诊断类型，如 'ASD'、'ADHD'",
    )
    historical_behavior_tags: list[str] = Field(
        default_factory=list,
        description="历史行为标签列表，如 ['self_injury', 'aggression']。档案叠加规则的数据源",
    )
    recent_event_records: list[dict[str, Any]] = Field(
        default_factory=list,
        description="最近事件记录列表，上限 5 条。每条记录含 event_type、occurred_at 等字段",
    )


# ============================================================================
# JudgmentContext（Pipeline 运行时上下文，内部使用）
# ============================================================================


class JudgmentContext(BaseModel):
    """Pipeline 运行时上下文，在层间传递判定状态。

    不对外暴露，仅 CrisisJudgmentPipeline 内部使用。
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    request: CrisisJudgmentRequest
    sources: list[JudgmentLayerResult] = Field(
        default_factory=list,
        description="各判定层的裁决结论列表",
    )
    level: CrisisLevel | None = Field(
        default=None,
        description="当前累积的危机等级",
    )
    block_deep: bool = Field(
        default=False,
        description="阻断深度回答标记",
    )
    manual_review_flag: bool = Field(
        default=False,
        description="人工复核标记",
    )
    review_confidence: float | None = Field(
        default=None,
        description="LLM 复审置信度",
    )
    skip_remaining: bool = Field(
        default=False,
        description="跳过后续判定层标记",
    )
    degradation_note: str | None = Field(
        default=None,
        description="降级标注",
    )


__all__ = [
    "CrisisJudgmentRequest",
    "CrisisJudgmentResult",
    "JudgmentLayerResult",
    "PatientProfileSnapshot",
    "JudgmentContext",
]
