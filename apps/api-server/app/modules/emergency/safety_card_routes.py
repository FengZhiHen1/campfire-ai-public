"""安全卡管理路由（admin/expert 内容运营，M3 审核链路复用）。

端点：
- GET  /api/v1/safety-cards             — 列表（全量含未审核）
- POST /api/v1/safety-cards             — 创建（draft）
- PUT  /api/v1/safety-cards/{card_id}   — 更新（新版本，回到 pending_review）
- POST /api/v1/safety-cards/{card_id}/review — 审核操作（approve/reject/unlist）

审核状态机复用案例链路（draft/pending_review/approved/rejected）；
下架 = 退回 draft（不再供给——find_card 仅查 approved）。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from py_db.models.consultation import SafetyCard
from py_db.repositories.safety_card_repository import SafetyCardRepository
from py_schemas.auth import UserRole
from py_schemas.emergency import (
    SafetyCardManageItem,
    SafetyCardReviewRequest,
    SafetyCardUpsertRequest,
)
from py_schemas.enums.case_enums import CaseStatus
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.auth_dependencies import (
    CurrentUser,
    _get_session_factory,
    get_db_session,
    require_roles,
)

router = APIRouter(prefix="/api/v1/safety-cards", tags=["safety-cards"])

# 内容运营：expert（案例审核能力域）/ admin（平台管理）
_MANAGE_ROLES = (UserRole.EXPERT, UserRole.ADMIN)


def _get_repo() -> SafetyCardRepository:
    return SafetyCardRepository(session_factory=_get_session_factory())


def _to_item(card: SafetyCard) -> SafetyCardManageItem:
    return SafetyCardManageItem(
        card_id=str(card.id),
        bucket=card.bucket,
        stage=card.crisis_stage,
        title=card.title,
        card_template=card.card_template,
        review_status=card.review_status.value if hasattr(card.review_status, "value") else str(card.review_status),
        version=card.version,
        updated_at=card.updated_at.isoformat(),
    )


@router.get("", summary="安全卡列表（管理端）")
async def list_cards(
    _current_user: CurrentUser = Depends(require_roles(*_MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    repo = _get_repo()
    cards = await repo.list_all(db)
    return {"items": [_to_item(c).model_dump(mode="json") for c in cards], "total": len(cards)}


@router.post("", status_code=201, summary="创建安全卡（draft）")
async def create_card(
    request: SafetyCardUpsertRequest,
    _current_user: CurrentUser = Depends(require_roles(*_MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    repo = _get_repo()
    card = SafetyCard(
        bucket=request.bucket,
        crisis_stage=request.stage,
        title=request.title,
        card_template=request.card_template,
        review_status=CaseStatus.DRAFT,
        version=1,
    )
    created = await repo.create(db, card)
    await db.commit()
    return _to_item(created).model_dump(mode="json")


@router.put("/{card_id}", summary="更新安全卡（版本 +1，回到待审）")
async def update_card(
    card_id: str,
    request: SafetyCardUpsertRequest,
    _current_user: CurrentUser = Depends(require_roles(*_MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    repo = _get_repo()
    card = await repo.find_by_id(db, uuid.UUID(card_id))
    if card is None:
        raise HTTPException(status_code=404, detail="卡片不存在")
    card.bucket = request.bucket
    card.crisis_stage = request.stage
    card.title = request.title
    card.card_template = request.card_template
    card.version += 1
    card.review_status = CaseStatus.PENDING_REVIEW  # 内容变更须重新审核
    await db.commit()
    return _to_item(card).model_dump(mode="json")


@router.post("/{card_id}/review", summary="安全卡审核操作（approve/reject/unlist）")
async def review_card(
    card_id: str,
    request: SafetyCardReviewRequest,
    _current_user: CurrentUser = Depends(require_roles(*_MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    repo = _get_repo()
    card = await repo.find_by_id(db, uuid.UUID(card_id))
    if card is None:
        raise HTTPException(status_code=404, detail="卡片不存在")

    if request.action == "approve":
        card.review_status = CaseStatus.APPROVED
    elif request.action == "reject":
        card.review_status = CaseStatus.REJECTED
    elif request.action == "unlist":
        # 下架 = 退回草稿态（不再供给）
        card.review_status = CaseStatus.DRAFT
    await db.commit()
    return _to_item(card).model_dump(mode="json")


__all__ = ["router"]
