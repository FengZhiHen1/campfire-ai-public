"""L2 结构化卡片层 — Pydantic 数据模型。

Cards 是案例系统的第二层：从 L1 叙事中提取的结构化干预卡片。
每张卡片包含四段式干预字段 (immediate_action/comforting_phrase/observation_metrics/medical_criteria)
以及 EBP 标签、家属大类等元数据。

与 L1 原始叙事 (narratives.py) 形成多对一关系 —— 一张叙事可衍生多张卡片。

契约引用：
- CardCreateRequest: docs/contracts/CASE-01/CardCreateRequest.json
- CardResponse: docs/contracts/CASE-01/CardResponse.json
- CardUpdate: docs/contracts/CASE-01/CardUpdate.json
- CardExtractionResult: docs/contracts/CASE-01/CardExtractionResult.json
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from py_schemas.cases import PaginatedResponse
from py_schemas.enums.case_enums import CaseStatus


class CardCreateRequest(BaseModel):
    """L2 卡片创建请求。

    包含四段式干预字段和 EBP 元数据。
    inferred_fields 由 LLM 提取流程自动填充，标记为 AI 推测字段。
    """

    title: str = Field(..., min_length=1, max_length=100)
    scenario: str = Field(..., min_length=1)
    behavior_type: str
    age_range: List[int] = Field(..., description="[min, max]")
    severity: str
    scene: str
    ebp_labels: List[str] = Field(default_factory=list)
    family_category: str
    immediate_action: str = Field(..., min_length=1)
    comforting_phrase: str = Field(..., min_length=1)
    observation_metrics: str = Field(..., min_length=1)
    medical_criteria: str = Field(..., min_length=1)
    evidence_level: str
    caution_notes: str = ""
    contraindications: str
    is_template: bool = False
    excluded_population: Optional[str] = None
    inferred_fields: Optional[Dict[str, Any]] = None

    model_config = {"extra": "forbid"}


class CardResponse(BaseModel):
    """L2 卡片详情响应。

    包含全量卡片字段以及审核状态和归属信息。
    """

    card_id: str
    narrative_id: str
    title: str
    scenario: str
    behavior_type: str
    age_range: List[int]
    severity: str
    scene: str
    ebp_labels: List[str]
    family_category: str
    immediate_action: str
    comforting_phrase: str
    observation_metrics: str
    medical_criteria: str
    evidence_level: str
    caution_notes: str
    contraindications: str
    is_template: bool
    excluded_population: Optional[str] = None
    attachment_refs: Optional[List[Any]] = None
    review_status: CaseStatus
    review_comment: Optional[str] = None
    inferred_fields: Optional[Dict[str, Any]] = None
    is_owner: Optional[bool] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"extra": "forbid"}


class CardUpdate(BaseModel):
    """L2 卡片部分更新请求（乐观锁）。

    所有业务字段均为可选（partial update）。
    updated_at 用于乐观锁并发控制。
    """

    title: Optional[str] = None
    scenario: Optional[str] = None
    behavior_type: Optional[str] = None
    age_range: Optional[List[int]] = None
    severity: Optional[str] = None
    scene: Optional[str] = None
    ebp_labels: Optional[List[str]] = None
    family_category: Optional[str] = None
    immediate_action: Optional[str] = None
    comforting_phrase: Optional[str] = None
    observation_metrics: Optional[str] = None
    medical_criteria: Optional[str] = None
    evidence_level: Optional[str] = None
    caution_notes: Optional[str] = None
    contraindications: Optional[str] = None
    excluded_population: Optional[str] = None
    inferred_fields: Optional[Dict[str, Any]] = None
    updated_at: Optional[str] = Field(
        default=None, description="乐观锁时间戳"
    )

    model_config = {"extra": "forbid"}


class CardExtractionResult(BaseModel):
    """LLM 提取结果包装。

    由 LLM 提取流程返回，包含从单篇叙事中提取的多张卡片。
    """

    cards: List[CardCreateRequest]

    model_config = {"extra": "forbid"}


__all__ = [
    "CardCreateRequest",
    "CardResponse",
    "CardUpdate",
    "CardExtractionResult",
]
