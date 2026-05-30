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

import asyncio
import math
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.anonymous_user import get_anonymous_user
from app.core.dependencies.auth_dependencies import _get_session_factory, get_db_session
from py_db.models.case_narrative import CaseNarrative
from py_logger import logger
from ..exceptions import NarrativeNotFoundError
from .service import (
    NarrativeManagementService,
    ExtractionResponse,
    NarrativeDetailResponse,
    card_to_response,
    narrative_to_list_item,
    narrative_to_response,
)
from ..types import NarrativeId
from py_schemas.narratives import (
    NarrativeCreateRequest,
    NarrativeUpdate,
    NarrativeResponse,
    NarrativeListItem,
)
from py_schemas.cases import PaginatedResponse

router = APIRouter(prefix="/api/v1/narratives", tags=["narratives"])

_narrative_service = NarrativeManagementService()


def _handle_narrative_error(exc: NarrativeNotFoundError) -> None:
    """将叙事业务异常映射为 HTTPException。"""
    raise HTTPException(status_code=404, detail={"code": "NARRATIVE_NOT_FOUND", "message": str(exc)})


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
    try:
        entity = await _narrative_service.get_narrative(
            NarrativeId(narrative_id), anonymous_user, db,
        )
    except NarrativeNotFoundError as exc:
        _handle_narrative_error(exc)
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
    try:
        entity = await _narrative_service.update_narrative(
            NarrativeId(narrative_id), request.title, request.narrative, anonymous_user, db,
        )
    except NarrativeNotFoundError as exc:
        _handle_narrative_error(exc)
    return narrative_to_response(entity)


@router.post("/{narrative_id}/submit", response_model=NarrativeResponse)
async def submit_narrative_endpoint(
    narrative_id: str,
    anonymous_user: dict = Depends(get_anonymous_user),
    db: AsyncSession = Depends(get_db_session),
):
    try:
        entity = await _narrative_service.submit_narrative(
            NarrativeId(narrative_id), anonymous_user, db,
        )
    except NarrativeNotFoundError as exc:
        _handle_narrative_error(exc)
    return narrative_to_response(entity)


@router.post("/{narrative_id}/extract")
async def extract_narrative_endpoint(
    narrative_id: str,
    anonymous_user: dict = Depends(get_anonymous_user),
    db: AsyncSession = Depends(get_db_session),
):
    """LLM 提取 L2 卡片（幂等 + 异步）。

    状态机：
    - pending → 启动后台提取，返回 202 extracting
    - extracting → 返回 202（前端继续轮询）
    - extracted → 返回 200 + 已有卡片（秒返）
    - failed → 重试提取，返回 202
    """
    try:
        entity = await _narrative_service.get_narrative(
            NarrativeId(narrative_id), anonymous_user, db,
        )
    except NarrativeNotFoundError as exc:
        _handle_narrative_error(exc)

    current_status = entity.extraction_status

    # 已提取：直接返回缓存卡片
    if current_status == "extracted" and entity.derived_card_ids:
        cards = await _narrative_service._do_get_cards_by_narrative(
            NarrativeId(narrative_id), db,
        )
        return {
            "narrative_id": narrative_id,
            "card_count": len(cards),
            "cards": [
                card_to_response(c, is_owner=True, current_user_id=anonymous_user.get("sub", ""))
                for c in cards
            ],
        }

    # 提取中：告知前端继续等
    if current_status == "extracting":
        return JSONResponse(
            status_code=202,
            content={"status": "extracting", "narrative_id": narrative_id},
        )

    # pending 或 failed：启动后台提取
    narrative_text = entity.narrative
    entity.extraction_status = "extracting"
    await db.commit()

    asyncio.create_task(
        _run_extraction_background(narrative_id, narrative_text, anonymous_user.get("sub", ""))
    )

    return JSONResponse(
        status_code=202,
        content={"status": "extracting", "narrative_id": narrative_id},
    )


async def _run_extraction_background(
    narrative_id: str,
    narrative_text: str,
    user_id: str,
) -> None:
    """后台执行 LLM 提取，独立 DB 会话。"""
    from ..extraction.service import ExtractionService

    session_factory = _get_session_factory()
    async with session_factory() as bg_db:
        try:
            extraction_service = ExtractionService()
            cards = await extraction_service.extract_cards_from_narrative(
                narrative_text=narrative_text,
                narrative_id=NarrativeId(narrative_id),
                db=bg_db,
            )
            # 更新叙事状态为 extracted
            result = await bg_db.execute(
                select(CaseNarrative).where(
                    CaseNarrative.narrative_id == _uuid.UUID(narrative_id),
                )
            )
            nar = result.scalars().first()
            if nar:
                nar.extraction_status = "extracted"
                nar.derived_card_ids = [str(c.card_id) for c in cards]
                await bg_db.commit()
            logger.info(
                service="api-server",
                message="extraction_background_done",
                extra={"narrative_id": narrative_id, "card_count": len(cards)},
            )
        except Exception:
            # 提取失败：回写状态
            try:
                result = await bg_db.execute(
                    select(CaseNarrative).where(
                        CaseNarrative.narrative_id == _uuid.UUID(narrative_id),
                    )
                )
                nar = result.scalars().first()
                if nar:
                    nar.extraction_status = "failed"
                    await bg_db.commit()
            except Exception:
                pass
            logger.exception(
                service="api-server",
                message="extraction_background_failed",
                extra={"narrative_id": narrative_id},
            )


__all__ = ["router"]
