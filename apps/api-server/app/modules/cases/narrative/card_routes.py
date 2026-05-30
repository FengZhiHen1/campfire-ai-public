"""L2 卡片层 — HTTP 路由。

Route prefix: /api/v1/cards
- PUT /{card_id}   — 更新 L2 卡片（专家微调）
- POST /{card_id}/submit — 提交单张卡片审核
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.auth_dependencies import get_db_session
from ..types import CardId
from .service import NarrativeManagementService, card_to_response

router = APIRouter(prefix="/api/v1/cards", tags=["cards"])

_card_service = NarrativeManagementService()


@router.put("/{card_id}", status_code=status.HTTP_200_OK)
async def update_card_endpoint(
    card_id: str,
    update_data: dict[str, Any] = Body(..., description="卡片部分更新字段"),
    db: AsyncSession = Depends(get_db_session),
):
    """更新 L2 卡片（仅 draft/rejected 状态可编辑）。"""
    entity = await _card_service.update_card(CardId(card_id), update_data, db)
    return card_to_response(entity)


@router.post("/{card_id}/submit", status_code=status.HTTP_200_OK)
async def submit_card_endpoint(
    card_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """提交单张 L2 卡片审核（draft → pending_review）。"""
    entity = await _card_service.submit_card(CardId(card_id), db)
    return card_to_response(entity)


__all__ = ["router"]
