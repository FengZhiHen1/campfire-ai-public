"""PROF-03 事件记录管理 — API 路由。

提供事件记录的 CRUD 端点，挂载于 /api/v1/profiles 前缀下。

端点：
- GET  /{profile_id}/events           — 事件列表（分页）
- POST /{profile_id}/events           — 创建事件
- GET  /{profile_id}/events/{event_id} — 事件详情
- PUT  /{profile_id}/events/{event_id} — 更新事件
- DELETE /{profile_id}/events/{event_id} — 删除事件
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.anonymous_user import get_anonymous_user
from app.core.dependencies.auth_dependencies import (
    get_db_session,
    get_event_repository,
    get_profile_repository,
)
from app.modules.profiles.event_service import (
    create_event,
    delete_event,
    get_event,
    list_events,
    update_event,
)
from py_db.repositories.event_repository import EventRepository
from py_db.repositories.profile_repository import ProfileRepository
from py_schemas.cases import PaginatedResponse
from py_schemas.profiles import EventCreate, EventListItem, EventResponse, EventUpdate

router = APIRouter(prefix="/api/v1/profiles", tags=["events"])


def _extract_user_id(anonymous_user: dict) -> UUID:
    """从匿名用户字典中提取用户 UUID。"""
    user_id_str: str = anonymous_user.get("sub", anonymous_user.get("user_id", ""))
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无法解析用户标识",
        )
    try:
        return UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户标识格式无效",
        )


# ===========================================================================
# GET /{profile_id}/events — 事件列表
# ===========================================================================


@router.get(
    "/{profile_id}/events",
    status_code=status.HTTP_200_OK,
    summary="获取事件列表",
    response_model=PaginatedResponse[EventListItem],
)
async def list_events_endpoint(
    profile_id: UUID,
    page: int = Query(default=1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
    event_repo: EventRepository = Depends(get_event_repository),
    profile_repo: ProfileRepository = Depends(get_profile_repository),
) -> PaginatedResponse[EventListItem]:
    """事件列表端点。"""
    caregiver_id = _extract_user_id(anonymous_user)
    return await list_events(
        profile_id=profile_id,
        caregiver_id=caregiver_id,
        page=page,
        page_size=page_size,
        session=session,
        event_repo=event_repo,
        profile_repo=profile_repo,
    )


# ===========================================================================
# POST /{profile_id}/events — 创建事件
# ===========================================================================


@router.post(
    "/{profile_id}/events",
    status_code=status.HTTP_201_CREATED,
    summary="创建事件",
    response_model=EventResponse,
    responses={
        201: {"description": "事件创建成功"},
        400: {"description": "事件时间超出 30 天追溯期"},
        404: {"description": "档案不存在"},
    },
)
async def create_event_endpoint(
    profile_id: UUID,
    input_data: EventCreate,
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
    event_repo: EventRepository = Depends(get_event_repository),
    profile_repo: ProfileRepository = Depends(get_profile_repository),
) -> EventResponse:
    """创建事件端点。"""
    user_id = _extract_user_id(anonymous_user)
    return await create_event(
        profile_id=profile_id,
        user_id=user_id,
        input_data=input_data,
        session=session,
        event_repo=event_repo,
        profile_repo=profile_repo,
    )


# ===========================================================================
# GET /{profile_id}/events/{event_id} — 事件详情
# ===========================================================================


@router.get(
    "/{profile_id}/events/{event_id}",
    status_code=status.HTTP_200_OK,
    summary="获取事件详情",
    response_model=EventResponse,
    responses={
        200: {"description": "成功返回事件详情"},
        404: {"description": "事件不存在"},
    },
)
async def get_event_endpoint(
    profile_id: UUID,
    event_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    event_repo: EventRepository = Depends(get_event_repository),
) -> EventResponse:
    """事件详情端点。"""
    return await get_event(
        event_id=event_id,
        profile_id=profile_id,
        session=session,
        event_repo=event_repo,
    )


# ===========================================================================
# PUT /{profile_id}/events/{event_id} — 更新事件
# ===========================================================================


@router.put(
    "/{profile_id}/events/{event_id}",
    status_code=status.HTTP_200_OK,
    summary="更新事件",
    response_model=EventResponse,
    responses={
        200: {"description": "事件更新成功"},
        404: {"description": "事件不存在"},
    },
)
async def update_event_endpoint(
    profile_id: UUID,
    event_id: UUID,
    input_data: EventUpdate,
    session: AsyncSession = Depends(get_db_session),
    event_repo: EventRepository = Depends(get_event_repository),
) -> EventResponse:
    """更新事件端点。"""
    return await update_event(
        event_id=event_id,
        profile_id=profile_id,
        input_data=input_data,
        session=session,
        event_repo=event_repo,
    )


# ===========================================================================
# DELETE /{profile_id}/events/{event_id} — 删除事件
# ===========================================================================


@router.delete(
    "/{profile_id}/events/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除事件",
    responses={
        204: {"description": "删除成功"},
        404: {"description": "事件不存在"},
    },
)
async def delete_event_endpoint(
    profile_id: UUID,
    event_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    event_repo: EventRepository = Depends(get_event_repository),
) -> None:
    """删除事件端点。"""
    await delete_event(
        event_id=event_id,
        profile_id=profile_id,
        session=session,
        event_repo=event_repo,
    )


__all__ = ["router"]
