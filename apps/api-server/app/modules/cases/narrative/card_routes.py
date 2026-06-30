"""L2 卡片层 — HTTP 路由。

Route prefix: /api/v1/cards
- GET /{card_id}   — 获取单张 L2 卡片详情
- PUT /{card_id}   — 更新 L2 卡片（专家微调）
- POST /{card_id}/submit — 提交单张卡片审核
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.auth_dependencies import get_db_session
from ..exceptions import CardNotFoundError, CaseStatusError
from ..types import CardId
from .service import NarrativeManagementService, card_to_response

router = APIRouter(prefix="/api/v1/cards", tags=["cards"])

_card_service = NarrativeManagementService()


@router.get("/{card_id}", status_code=status.HTTP_200_OK)
async def get_card_endpoint(
    card_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """获取单张 L2 卡片完整详情。"""
    try:
        entity = await _card_service.get_card(CardId(card_id), db)
    except CardNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "CARD_NOT_FOUND", "message": str(exc)})
    return card_to_response(entity)


@router.put("/{card_id}", status_code=status.HTTP_200_OK)
async def update_card_endpoint(
    card_id: str,
    update_data: dict[str, Any] = Body(..., description="卡片部分更新字段"),
    db: AsyncSession = Depends(get_db_session),
):
    """更新 L2 卡片（仅 draft/rejected 状态可编辑）。"""
    try:
        entity = await _card_service.update_card(CardId(card_id), update_data, db)
    except CardNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "CARD_NOT_FOUND", "message": str(exc)})
    except CaseStatusError as exc:
        raise HTTPException(status_code=409, detail={"code": "CARD_STATUS_CONFLICT", "message": str(exc)})
    return card_to_response(entity)


@router.post("/{card_id}/submit", status_code=status.HTTP_200_OK)
async def submit_card_endpoint(
    card_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """提交单张 L2 卡片审核（draft → pending_review）。"""
    try:
        entity = await _card_service.submit_card(CardId(card_id), db)
    except CardNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "CARD_NOT_FOUND", "message": str(exc)})
    except CaseStatusError as exc:
        raise HTTPException(status_code=409, detail={"code": "CARD_STATUS_CONFLICT", "message": str(exc)})
    return card_to_response(entity)


__all__ = ["router"]
