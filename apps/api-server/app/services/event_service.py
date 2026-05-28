"""PROF-03 事件记录管理 — Service 层。

提供事件记录的 CRUD 业务逻辑编排。
所有方法通过 AsyncSession 参数化，不持有会话状态。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.models.profiles import EventLog
from py_db.repositories.event_repository import EventRepository
from py_db.repositories.profile_repository import ProfileRepository
from py_logger import logger
from py_schemas.cases import PaginatedResponse
from py_schemas.profiles import (
    EventCreate,
    EventListItem,
    EventResponse,
    EventUpdate,
)


def _orm_to_event_response(event: EventLog) -> EventResponse:
    """将 EventLog ORM 实例转换为 EventResponse。"""
    return EventResponse(
        event_id=event.event_id,
        profile_id=event.profile_id,
        recorded_by=event.recorded_by,
        recorded_by_role=event.recorded_by_role,
        event_time=event.event_time,
        behavior_type=event.behavior_type,
        severity_level=event.severity_level,
        setting=event.setting,
        trigger_description=event.trigger_description,
        manifestation=event.manifestation,
        intervention_tried=event.intervention_tried,
        intervention_result=event.intervention_result,
        is_professional=event.is_professional,
        tags=event.tags,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def _orm_to_event_list_item(event: EventLog) -> EventListItem:
    """将 EventLog ORM 实例转换为 EventListItem。"""
    return EventListItem(
        event_id=event.event_id,
        event_time=event.event_time,
        behavior_type=event.behavior_type,
        severity_level=event.severity_level,
        has_professional_note=event.is_professional,
        created_at=event.created_at,
    )


async def list_events(
    profile_id: UUID,
    page: int,
    page_size: int,
    session: AsyncSession,
    event_repo: EventRepository,
    profile_repo: ProfileRepository,
) -> PaginatedResponse[EventListItem]:
    """查询指定档案的事件列表（分页）。

    Args:
        profile_id: 所属档案 UUID。
        page: 页码（从 1 开始）。
        page_size: 每页条数。
        session: 活动数据库会话。
        event_repo: EventRepository 实例。
        profile_repo: ProfileRepository 实例。

    Returns:
        PaginatedResponse[EventListItem]: 分页事件列表。

    Raises:
        HTTPException(404): 档案不存在。
    """
    profile = await profile_repo.get_by_id(session, profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="档案不存在",
        )

    events, total = await event_repo.list_by_profile(
        session,
        profile_id=profile_id,
        page=page,
        page_size=page_size,
    )

    items = [_orm_to_event_list_item(e) for e in events]
    total_pages = math.ceil(total / page_size) if total > 0 else 0

    return PaginatedResponse[EventListItem](
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


async def create_event(
    profile_id: UUID,
    user_id: UUID,
    input_data: EventCreate,
    session: AsyncSession,
    event_repo: EventRepository,
    profile_repo: ProfileRepository,
) -> EventResponse:
    """为指定档案创建新事件记录。

    Args:
        profile_id: 所属档案 UUID。
        user_id: 记录人用户 UUID。
        input_data: 事件创建请求体。
        session: 活动数据库会话。
        event_repo: EventRepository 实例。
        profile_repo: ProfileRepository 实例。

    Returns:
        EventResponse: 创建成功的事件详情。

    Raises:
        HTTPException(404): 档案不存在。
        HTTPException(400): 事件时间超出 30 天追溯期。
    """
    profile = await profile_repo.get_by_id(session, profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="档案不存在",
        )

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    event_time = input_data.event_time
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    if event_time < cutoff:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持补录最近 30 天内的事件",
        )

    event = EventLog(
        profile_id=profile_id,
        recorded_by=user_id,
        recorded_by_role="parent",
        event_time=event_time,
        behavior_type=input_data.behavior_type.value,
        severity_level=input_data.severity_level.value,
        setting=input_data.setting.value if input_data.setting else None,
        trigger_description=input_data.trigger_description,
        manifestation=input_data.manifestation,
        intervention_tried=input_data.intervention_tried,
        intervention_result=input_data.intervention_result,
        tags=input_data.tags,
    )

    created = await event_repo.create(session, event)
    logger.info(
        "event_service",
        f"事件创建成功: event_id={created.event_id}",
        extra={"profile_id": str(profile_id)},
    )
    return _orm_to_event_response(created)


async def get_event(
    event_id: UUID,
    profile_id: UUID,
    session: AsyncSession,
    event_repo: EventRepository,
) -> EventResponse:
    """查询单条事件详情。

    Args:
        event_id: 事件 UUID。
        profile_id: 所属档案 UUID（用于数据隔离校验）。
        session: 活动数据库会话。
        event_repo: EventRepository 实例。

    Returns:
        EventResponse: 事件详情。

    Raises:
        HTTPException(404): 事件不存在。
    """
    event = await event_repo.get_by_id(session, event_id, profile_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="事件不存在",
        )
    return _orm_to_event_response(event)


async def update_event(
    event_id: UUID,
    profile_id: UUID,
    input_data: EventUpdate,
    session: AsyncSession,
    event_repo: EventRepository,
) -> EventResponse:
    """更新事件记录（Merge Patch 语义）。

    Args:
        event_id: 事件 UUID。
        profile_id: 所属档案 UUID。
        input_data: 事件更新请求体（仅提供的字段会被更新）。
        session: 活动数据库会话。
        event_repo: EventRepository 实例。

    Returns:
        EventResponse: 更新后的事件详情。

    Raises:
        HTTPException(404): 事件不存在。
    """
    update_dict = input_data.model_dump(exclude_unset=True)

    # 枚举值需转换为字符串
    if "behavior_type" in update_dict and update_dict["behavior_type"] is not None:
        update_dict["behavior_type"] = update_dict["behavior_type"].value
    if "severity_level" in update_dict and update_dict["severity_level"] is not None:
        update_dict["severity_level"] = update_dict["severity_level"].value
    if "setting" in update_dict and update_dict["setting"] is not None:
        update_dict["setting"] = update_dict["setting"].value

    updated = await event_repo.update(session, event_id, profile_id, update_dict)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="事件不存在",
        )
    return _orm_to_event_response(updated)


async def delete_event(
    event_id: UUID,
    profile_id: UUID,
    session: AsyncSession,
    event_repo: EventRepository,
) -> None:
    """删除指定事件记录。

    Args:
        event_id: 事件 UUID。
        profile_id: 所属档案 UUID。
        session: 活动数据库会话。
        event_repo: EventRepository 实例。

    Raises:
        HTTPException(404): 事件不存在。
    """
    deleted = await event_repo.delete(session, event_id, profile_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="事件不存在",
        )


__all__ = [
    "list_events",
    "create_event",
    "get_event",
    "update_event",
    "delete_event",
]
