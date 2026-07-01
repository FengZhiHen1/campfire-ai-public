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
import datetime
import math
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from py_db.models.case_narrative import CaseNarrative
from py_logger import logger
from py_schemas.cases import PaginatedResponse
from py_schemas.narratives import (
    NarrativeCreateRequest,
    NarrativeListItem,
    NarrativeResponse,
    NarrativeUpdate,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.anonymous_user import get_anonymous_user
from app.core.dependencies.auth_dependencies import _get_session_factory, get_db_session

from ..exceptions import ExtractionError, NarrativeNotFoundError
from ..types import NarrativeId
from .service import (
    NarrativeDetailResponse,
    NarrativeManagementService,
    card_to_response,
    narrative_to_list_item,
    narrative_to_response,
)

router = APIRouter(prefix="/api/v1/narratives", tags=["narratives"])

_narrative_service = NarrativeManagementService()

# 保留后台提取任务的强引用，避免被 asyncio 垃圾回收；任务完成后通过 done 回调移除。
_extraction_tasks: set[asyncio.Task] = set()

# 提取任务过期时间：后台任务超过该时间仍未结束，视为孤儿任务，允许重新提取。
_EXTRACTION_STALE_AFTER_SECONDS = 600

_STALE_EXTRACTION_ERROR = "提取任务已超时或中断，请重试"


def _is_extraction_stale(entity: CaseNarrative) -> bool:
    """判断当前 extracting 状态是否已经过期（孤儿任务）。"""
    if entity.extraction_status != "extracting":
        return False
    updated_at = entity.updated_at
    if updated_at is None:
        return True
    elapsed = datetime.datetime.now(datetime.timezone.utc) - updated_at
    return elapsed.total_seconds() > _EXTRACTION_STALE_AFTER_SECONDS


async def _reset_stale_extraction(entity: CaseNarrative, db: AsyncSession) -> None:
    """将过期的 extracting 状态重置为 failed，并持久化错误信息。"""
    entity.extraction_status = "failed"
    entity.extraction_error = _STALE_EXTRACTION_ERROR
    await db.commit()
    logger.warning(
        service="api-server",
        message="extraction_stale_reset",
        extra={
            "narrative_id": str(entity.narrative_id),
            "updated_at": str(entity.updated_at),
        },
    )


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
        scope=scope,
        current_user=anonymous_user,
        session=db,
        page=page,
        page_size=page_size,
    )
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    return {
        "items": [narrative_to_list_item(n) for n in items],
        "total": total,
        "page": page,
        "page_size": page_size,
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
            NarrativeId(narrative_id),
            anonymous_user,
            db,
        )
    except NarrativeNotFoundError as exc:
        _handle_narrative_error(exc)

    # 处理过期的 extracting 状态，避免前端永远轮询一个已不存在的后台任务。
    if _is_extraction_stale(entity):
        await _reset_stale_extraction(entity, db)
        await db.refresh(entity)

    cards = await _narrative_service.get_cards_by_narrative(NarrativeId(narrative_id), db)

    # 通过 narrative_to_response 转换，避免路由层直接访问 ORM 属性
    result = narrative_to_response(entity)
    result["card_count"] = len(cards)

    # is_owner: 判断当前用户是否为叙事作者
    is_owner = result["author_id"] == anonymous_user.get("sub", "")
    result["cards"] = [
        card_to_response(c, is_owner=is_owner, current_user_id=anonymous_user.get("sub", "")) for c in cards
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
            NarrativeId(narrative_id),
            request.title,
            request.narrative,
            anonymous_user,
            db,
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
            NarrativeId(narrative_id),
            anonymous_user,
            db,
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
            NarrativeId(narrative_id),
            anonymous_user,
            db,
        )
    except NarrativeNotFoundError as exc:
        _handle_narrative_error(exc)

    # 如果 extracting 状态已经过期（孤儿任务），先重置为 failed，允许重新提取。
    if _is_extraction_stale(entity):
        await _reset_stale_extraction(entity, db)
        # 刷新 entity 以获取重置后的状态
        await db.refresh(entity)

    current_status = entity.extraction_status

    # 已提取：直接返回缓存卡片
    if current_status == "extracted" and entity.derived_card_ids:
        cards = await _narrative_service._do_get_cards_by_narrative(
            NarrativeId(narrative_id),
            db,
        )
        return {
            "narrative_id": narrative_id,
            "card_count": len(cards),
            "cards": [card_to_response(c, is_owner=True, current_user_id=anonymous_user.get("sub", "")) for c in cards],
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
    entity.extraction_error = None
    await db.commit()

    task = asyncio.create_task(_run_extraction_background(narrative_id, narrative_text, anonymous_user.get("sub", "")))
    _extraction_tasks.add(task)
    task.add_done_callback(_extraction_tasks.discard)

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
            if nar is None:
                logger.warning(
                    service="api-server",
                    message="extraction_background_narrative_missing",
                    extra={"narrative_id": narrative_id},
                )
                return

            # 防御性检查：如果状态已被其他任务/请求改变，则避免覆盖。
            if nar.extraction_status != "extracting":
                logger.warning(
                    service="api-server",
                    message="extraction_background_status_changed",
                    extra={
                        "narrative_id": narrative_id,
                        "current_status": nar.extraction_status,
                    },
                )
                return

            nar.extraction_status = "extracted"
            nar.extraction_error = None
            nar.derived_card_ids = [str(c.card_id) for c in cards]
            await bg_db.commit()
            logger.info(
                service="api-server",
                message="extraction_background_done",
                extra={"narrative_id": narrative_id, "card_count": len(cards)},
            )
        except Exception as exc:
            # 提取失败：回写状态并持久化失败原因
            error_message = _format_extraction_error(exc)
            try:
                result = await bg_db.execute(
                    select(CaseNarrative).where(
                        CaseNarrative.narrative_id == _uuid.UUID(narrative_id),
                    )
                )
                nar = result.scalars().first()
                if nar is None:
                    pass
                elif nar.extraction_status != "extracting":
                    # 状态已被其他任务/请求改变，避免覆盖。
                    logger.warning(
                        service="api-server",
                        message="extraction_background_failed_status_changed",
                        extra={
                            "narrative_id": narrative_id,
                            "current_status": nar.extraction_status,
                        },
                    )
                else:
                    nar.extraction_status = "failed"
                    nar.extraction_error = error_message
                    await bg_db.commit()
            except Exception:
                pass
            logger.error(
                service="api-server",
                message="extraction_background_failed",
                op_type="case_extraction",
                extra={"narrative_id": narrative_id, "error": error_message},
            )


def _format_extraction_error(exc: Exception) -> str:
    """将提取异常格式化为可持久化的错误描述。"""
    if isinstance(exc, ExtractionError):
        message = exc.reason[:2000]
        if exc.raw_output:
            message = f"{message}\n\n原始 LLM 输出:\n{exc.raw_output[:2000]}"
        return message
    return str(exc)[:2000]


__all__ = ["router"]
