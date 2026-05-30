"""L1 原始叙事层 — FastAPI 路由。

路由层仅做依赖注入和委托——所有业务逻辑在 NarrativeManagementService 中。

- POST /api/v1/narratives — 创建 L1 叙事
- GET /api/v1/narratives — 列表
- GET /api/v1/narratives/{id} — 详情
- PUT /api/v1/narratives/{id} — 编辑
- POST /api/v1/narratives/{id}/submit — 提交审核
- POST /api/v1/narratives/{id}/extract — LLM 提取 L2 卡片
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.anonymous_user import get_anonymous_user
from app.core.dependencies.auth_dependencies import get_db_session
from app.modules.cases.narrative_service import (
    NarrativeManagementService,
    ExtractionResponse,
    NarrativeDetailResponse,
    card_to_response,
    narrative_to_list_item,
    narrative_to_response,
)
from app.modules.cases.types import NarrativeId
from py_schemas.narratives import (
    NarrativeCreateRequest,
    NarrativeUpdate,
    NarrativeResponse,
    NarrativeListItem,
)
from py_schemas.cases import PaginatedResponse

router = APIRouter(prefix="/api/v1/narratives", tags=["narratives"])

_narrative_service = NarrativeManagementService()


@router.post("", response_model=NarrativeResponse, status_code=status.HTTP_201_CREATED)
async def create_narrative_endpoint(
    request: NarrativeCreateRequest,
    anonymous_user: dict = Depends(get_anonymous_user),
    db: AsyncSession = Depends(get_db_session),
):
    entity = await _narrative_service.create_narrative(
        title=request.title,
        narrative=request.narrative,
        source_type=request.source_type,
        current_user=anonymous_user,
        session=db,
    )
    return narrative_to_response(entity)


@router.get("", response_model=PaginatedResponse[NarrativeListItem])
async def list_narratives_endpoint(
    scope: str = Query(default="public"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=100),
    anonymous_user: dict = Depends(get_anonymous_user),
    db: AsyncSession = Depends(get_db_session),
):
    items, total = await _narrative_service.list_narratives(
        scope=scope, current_user=anonymous_user, session=db,
        page=page, page_size=page_size,
    )
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    return {
        "items": [narrative_to_list_item(n) for n in items],
        "total": total, "page": page, "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/{narrative_id}", response_model=NarrativeDetailResponse)
async def get_narrative_endpoint(
    narrative_id: str,
    anonymous_user: dict = Depends(get_anonymous_user),
    db: AsyncSession = Depends(get_db_session),
):
    entity = await _narrative_service.get_narrative(
        NarrativeId(narrative_id), anonymous_user, db,
    )
    cards = await _narrative_service.get_cards_by_narrative(NarrativeId(narrative_id), db)

    # 通过 narrative_to_response 转换，避免路由层直接访问 ORM 属性
    result = narrative_to_response(entity)
    result["card_count"] = len(cards)

    # is_owner: 判断当前用户是否为叙事作者
    is_owner = (result["author_id"] == anonymous_user.get("sub", ""))
    result["cards"] = [
        card_to_response(c, is_owner=is_owner,
                         current_user_id=anonymous_user.get("sub", ""))
        for c in cards
    ]
    return result


@router.put("/{narrative_id}", response_model=NarrativeResponse)
async def update_narrative_endpoint(
    narrative_id: str,
    request: NarrativeUpdate,
    anonymous_user: dict = Depends(get_anonymous_user),
    db: AsyncSession = Depends(get_db_session),
):
    entity = await _narrative_service.update_narrative(
        NarrativeId(narrative_id), request.title, request.narrative, anonymous_user, db,
    )
    return narrative_to_response(entity)


@router.post("/{narrative_id}/submit", response_model=NarrativeResponse)
async def submit_narrative_endpoint(
    narrative_id: str,
    anonymous_user: dict = Depends(get_anonymous_user),
    db: AsyncSession = Depends(get_db_session),
):
    entity = await _narrative_service.submit_narrative(
        NarrativeId(narrative_id), anonymous_user, db,
    )
    return narrative_to_response(entity)


@router.post("/{narrative_id}/extract", response_model=ExtractionResponse)
async def extract_narrative_endpoint(
    narrative_id: str,
    anonymous_user: dict = Depends(get_anonymous_user),
    db: AsyncSession = Depends(get_db_session),
):
    """LLM 提取：从 L1 叙事生成 L2 卡片。"""
    # 先获取叙事，验证权限
    entity = await _narrative_service.get_narrative(
        NarrativeId(narrative_id), anonymous_user, db,
    )

    # 通过 narrative_to_response 转换后读取状态，避免路由层直接访问 ORM 属性
    entity_dict = narrative_to_response(entity)
    if entity_dict["status"] != "draft":
        raise HTTPException(status_code=400, detail="仅草稿状态的叙事可触发提取")

    # 调用 LLM 提取
    from app.modules.cases.case_extraction.extractor import ExtractionService
    _extraction_service = ExtractionService()
    cards = await _extraction_service.extract_cards_from_narrative(
        narrative_text=entity_dict["narrative"],
        narrative_id=NarrativeId(narrative_id),
        db=db,
    )

    # 更新叙事 derived_card_ids（需要 ORM 对象进行写入操作）
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
