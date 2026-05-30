"""PROF-03 事件记录管理 — API 路由。

端点（挂载于 /api/v1/profiles 前缀下）:
- GET    /{profile_id}/events              — 事件列表（分页）
- POST   /{profile_id}/events              — 创建事件
- GET    /{profile_id}/events/{event_id}    — 事件详情
- PUT    /{profile_id}/events/{event_id}    — 更新事件
- DELETE /{profile_id}/events/{event_id}    — 删除事件
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.anonymous_user import get_anonymous_user
from app.core.dependencies.auth_dependencies import (
    get_db_session,
    get_event_repository,
    get_profile_repository,
)
from app.modules.profiles._exception_mapping import map_domain_error
from app.modules.profiles._user_utils import extract_user_id
from app.modules.profiles.event_service import EventServiceImpl
from app.modules.profiles.exceptions import ProfileDomainError
from py_db.repositories.event_repository import EventRepository
from py_db.repositories.profile_repository import ProfileRepository
from py_schemas.cases import PaginatedResponse
from py_schemas.profiles import EventCreate, EventListItem, EventResponse, EventUpdate

router = APIRouter(prefix="/api/v1/profiles", tags=["events"])


def _get_event_service(
    event_repo: EventRepository = Depends(get_event_repository),
    profile_repo: ProfileRepository = Depends(get_profile_repository),
) -> EventServiceImpl:
    """依赖注入：构造 EventServiceImpl 实例。"""
    return EventServiceImpl(
        event_repository=event_repo,
        profile_repository=profile_repo,
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
    event_service: EventServiceImpl = Depends(_get_event_service),
) -> PaginatedResponse[EventListItem]:
    caregiver_id = extract_user_id(anonymous_user)
    try:
        return await event_service.list_events(
            profile_id=profile_id,
            caregiver_id=caregiver_id,
            page=page,
            page_size=page_size,
            session=session,
        )
    except ProfileDomainError as exc:
        raise map_domain_error(exc)


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
    event_service: EventServiceImpl = Depends(_get_event_service),
) -> EventResponse:
    caregiver_id = extract_user_id(anonymous_user)
    try:
        return await event_service.create_event(
            profile_id=profile_id,
            user_id=caregiver_id,
            input_data=input_data,
            session=session,
        )
    except ProfileDomainError as exc:
        raise map_domain_error(exc)


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
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
    event_service: EventServiceImpl = Depends(_get_event_service),
) -> EventResponse:
    caregiver_id = extract_user_id(anonymous_user)
    try:
        return await event_service.get_event(
            event_id=event_id,
            profile_id=profile_id,
            caregiver_id=caregiver_id,
            session=session,
        )
    except ProfileDomainError as exc:
        raise map_domain_error(exc)


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
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
    event_service: EventServiceImpl = Depends(_get_event_service),
) -> EventResponse:
    caregiver_id = extract_user_id(anonymous_user)
    try:
        return await event_service.update_event(
            event_id=event_id,
            profile_id=profile_id,
            caregiver_id=caregiver_id,
            input_data=input_data,
            session=session,
        )
    except ProfileDomainError as exc:
        raise map_domain_error(exc)


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
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
    event_service: EventServiceImpl = Depends(_get_event_service),
) -> None:
    caregiver_id = extract_user_id(anonymous_user)
    try:
        await event_service.delete_event(
            event_id=event_id,
            profile_id=profile_id,
            caregiver_id=caregiver_id,
            session=session,
        )
    except ProfileDomainError as exc:
        raise map_domain_error(exc)


__all__ = ["router"]
