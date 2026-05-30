"""L1 原始叙事层 — FastAPI 路由。

- POST /api/v1/narratives — 创建 L1 叙事
- GET /api/v1/narratives — 列表
- GET /api/v1/narratives/{id} — 详情
- PUT /api/v1/narratives/{id} — 编辑
- POST /api/v1/narratives/{id}/submit — 提交审核
- POST /api/v1/narratives/{id}/extract — LLM 提取 L2 卡片
"""

from __future__ import annotations

from typing import Any, Dict, Optional
import math

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.anonymous_user import get_anonymous_user
from app.core.dependencies.auth_dependencies import get_db_session
from app.modules.cases.narrative_service import (
    create_narrative,
    get_narrative,
    list_narratives,
    update_narrative,
    submit_narrative,
    get_cards_by_narrative,
    narrative_to_response,
    card_to_response,
)
from py_schemas.narratives import (
    NarrativeCreateRequest,
    NarrativeResponse,
    NarrativeListItem,
    NarrativeUpdate,
)
from py_schemas.cards import CardResponse

router = APIRouter(prefix="/api/v1/narratives", tags=["narratives"])


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_narrative_endpoint(
    request: NarrativeCreateRequest,
    anonymous_user: dict = Depends(get_anonymous_user),
    db: AsyncSession = Depends(get_db_session),
):
    entity = await create_narrative(
        title=request.title,
        narrative=request.narrative,
        source_type=request.source_type,
        current_user=anonymous_user,
        session=db,
    )
    return narrative_to_response(entity)


@router.get("", response_model=dict)
async def list_narratives_endpoint(
    scope: str = Query(default="public"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=100),
    anonymous_user: dict = Depends(get_anonymous_user),
    db: AsyncSession = Depends(get_db_session),
):
    items, total = await list_narratives(
        scope=scope, current_user=anonymous_user, session=db,
        page=page, page_size=page_size,
    )
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    return {
        "items": [narrative_to_response(n) for n in items],
        "total": total, "page": page, "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/{narrative_id}", response_model=dict)
async def get_narrative_endpoint(
    narrative_id: str,
    anonymous_user: dict = Depends(get_anonymous_user),
    db: AsyncSession = Depends(get_db_session),
):
    entity = await get_narrative(narrative_id, anonymous_user, db)
    cards = await get_cards_by_narrative(narrative_id, db)
    result = narrative_to_response(entity, card_count=len(cards))
    result["cards"] = [
        card_to_response(c, is_owner=(str(c.narrative_id) == entity.author_id),
                         current_user_id=anonymous_user.get("sub", ""))
        for c in cards
    ]
    return result


@router.put("/{narrative_id}", response_model=dict)
async def update_narrative_endpoint(
    narrative_id: str,
    request: NarrativeUpdate,
    anonymous_user: dict = Depends(get_anonymous_user),
    db: AsyncSession = Depends(get_db_session),
):
    entity = await update_narrative(
        narrative_id, request.title, request.narrative, anonymous_user, db,
    )
    return narrative_to_response(entity)


@router.post("/{narrative_id}/submit", response_model=dict)
async def submit_narrative_endpoint(
    narrative_id: str,
    anonymous_user: dict = Depends(get_anonymous_user),
    db: AsyncSession = Depends(get_db_session),
):
    entity = await submit_narrative(narrative_id, anonymous_user, db)
    return narrative_to_response(entity)


@router.post("/{narrative_id}/extract", response_model=dict)
async def extract_narrative_endpoint(
    narrative_id: str,
    anonymous_user: dict = Depends(get_anonymous_user),
    db: AsyncSession = Depends(get_db_session),
):
    """LLM 提取：从 L1 叙事生成 L2 卡片。"""
    # 先获取叙事，验证权限
    entity = await get_narrative(narrative_id, anonymous_user, db)
    if entity.status != "draft":
        return {"error": "仅草稿状态的叙事可触发提取"}

    # 调用 LLM 提取
    from app.modules.cases.case_extraction.extractor import extract_cards_from_narrative
    cards = await extract_cards_from_narrative(
        narrative_text=entity.narrative,
        narrative_id=narrative_id,
        db=db,
    )

    # 更新叙事 derived_card_ids
    cids = [str(c.card_id) for c in cards]
    entity.derived_card_ids = cids
    await db.commit()

    return {
        "narrative_id": narrative_id,
        "card_count": len(cards),
        "cards": [
            card_to_response(c, is_owner=True, current_user_id=anonymous_user.get("sub", ""))
            for c in cards
        ],
    }


__all__ = ["router"]
