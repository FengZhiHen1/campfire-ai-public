"""L1 原始叙事层 — Pydantic 数据模型。

Narratives 是案例系统的第一层：原始干预故事的通用化叙事。
与 L2 结构化卡片 (cards.py) 形成一对多关系 —— 一个叙事可衍生多张干预卡片。

契约引用：
- NarrativeCreateRequest: docs/contracts/CASE-01/NarrativeCreateRequest.json
- NarrativeResponse: docs/contracts/CASE-01/NarrativeResponse.json
- NarrativeListItem: docs/contracts/CASE-01/NarrativeListItem.json
- NarrativeUpdate: docs/contracts/CASE-01/NarrativeUpdate.json
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from py_schemas.enums.case_enums import CaseStatus


class NarrativeCreateRequest(BaseModel):
    """L1 叙事创建请求。

    提交一个去个性化的原始干预故事，作为后续提取 L2 卡片的素材。
    """

    title: str = Field(..., min_length=1, max_length=100)
    narrative: str = Field(..., min_length=1, max_length=5000)
    source_type: str = Field(..., description="专家撰写/机构脱敏/工单沉淀")

    model_config = {"extra": "forbid"}


class NarrativeResponse(BaseModel):
    """L1 叙事详情响应。

    包含叙事全量字段以及衍生卡片引用列表。
    """

    narrative_id: str
    title: str
    narrative: str
    source_type: str
    author_id: str
    status: CaseStatus
    review_comment: Optional[str] = None
    derived_card_ids: Optional[List[str]] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"extra": "forbid"}


class NarrativeListItem(BaseModel):
    """L1 叙事列表条目。

    用于叙事管理列表展示，仅包含摘要字段以支持高效列表查询。
    """

    narrative_id: str
    title: str
    source_type: str
    author_id: str
    status: str
    card_count: int = 0
    created_at: datetime

    model_config = {"extra": "forbid"}


class NarrativeUpdate(BaseModel):
    """L1 叙事部分更新请求。

    所有业务字段均为可选（partial update）。
    """

    title: Optional[str] = None
    narrative: Optional[str] = None

    model_config = {"extra": "forbid"}


__all__ = [
    "NarrativeCreateRequest",
    "NarrativeResponse",
    "NarrativeListItem",
    "NarrativeUpdate",
]
