"""PROF-03 事件记录管理 — 契约实现。

继承 BaseEventService ABC，填充 _do_ 钩子。
按契约模板方法：路由 → @final 公共入口（前置校验） → _do_ 钩子（数据操作） → 后置校验。
"""

from __future__ import annotations

import math
from uuid import UUID

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

from app.modules.profiles._constants import DEFAULT_RECORDED_BY_ROLE
from app.modules.profiles.events_contract import BaseEventService


class EventServiceImpl(BaseEventService):
    """PROF-03 事件记录管理服务实现。

    继承 BaseEventService，仅覆写 _do_ 钩子方法。
    将原模块级函数重构为契约驱动的类结构。
    """

    def __init__(
        self,
        event_repository: EventRepository | None = None,
        profile_repository: ProfileRepository | None = None,
    ) -> None:
        super().__init__(
            event_repository=event_repository or EventRepository(session_factory=None),
            profile_repository=profile_repository or ProfileRepository(session_factory=None),
        )

    # ------------------------------------------------------------------
    # _do_ 钩子 — 列表
    # ------------------------------------------------------------------

    async def _do_list_events(
        self,
        profile_id: UUID,
        page: int,
        page_size: int,
        session: AsyncSession,
    ) -> PaginatedResponse[EventListItem]:
        events, total = await self._event_repo.list_by_profile(
            session,
            profile_id=profile_id,
            page=page,
            page_size=page_size,
        )
        items = [self._orm_to_list_item(e) for e in events]
        total_pages = math.ceil(total / page_size) if total > 0 else 0

        return PaginatedResponse[EventListItem](
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    # ------------------------------------------------------------------
    # _do_ 钩子 — 创建
    # ------------------------------------------------------------------

    async def _do_create_event(
        self,
        profile_id: UUID,
        user_id: UUID,
        input_data: EventCreate,
        session: AsyncSession,
    ) -> EventResponse:
        event = EventLog(
            profile_id=profile_id,
            recorded_by=user_id,
            recorded_by_role=DEFAULT_RECORDED_BY_ROLE,
            event_time=input_data.event_time,
            behavior_type=input_data.behavior_type.value,
            severity_level=input_data.severity_level.value,
            setting=input_data.setting.value if input_data.setting else None,
            trigger_description=input_data.trigger_description,
            manifestation=input_data.manifestation,
            intervention_tried=input_data.intervention_tried,
            intervention_result=input_data.intervention_result,
            tags=input_data.tags,
        )

        created = await self._event_repo.create(session, event)
        logger.info(
            "event_service",
            "事件创建成功",
            extra={"event_id": str(created.event_id), "profile_id": str(profile_id)},
        )
        return self._orm_to_response(created)

    # ------------------------------------------------------------------
    # _do_ 钩子 — 详情
    # ------------------------------------------------------------------

    async def _do_get_event(
        self,
        event_id: UUID,
        profile_id: UUID,
        session: AsyncSession,
    ) -> EventResponse | None:
        event = await self._event_repo.get_by_id(session, event_id, profile_id)
        if event is None:
            return None
        return self._orm_to_response(event)

    # ------------------------------------------------------------------
    # _do_ 钩子 — 更新
    # ------------------------------------------------------------------

    async def _do_update_event(
        self,
        event_id: UUID,
        profile_id: UUID,
        input_data: EventUpdate,
        session: AsyncSession,
    ) -> EventResponse | None:
        update_dict = input_data.model_dump(exclude_unset=True)

        if "behavior_type" in update_dict and update_dict["behavior_type"] is not None:
            update_dict["behavior_type"] = update_dict["behavior_type"].value
        if "severity_level" in update_dict and update_dict["severity_level"] is not None:
            update_dict["severity_level"] = update_dict["severity_level"].value
        if "setting" in update_dict and update_dict["setting"] is not None:
            update_dict["setting"] = update_dict["setting"].value

        updated = await self._event_repo.update_event(session, event_id, profile_id, update_dict)
        if updated is None:
            return None
        return self._orm_to_response(updated)

    # ------------------------------------------------------------------
    # _do_ 钩子 — 删除
    # ------------------------------------------------------------------

    async def _do_delete_event(
        self,
        event_id: UUID,
        profile_id: UUID,
        session: AsyncSession,
    ) -> bool:
        success = await self._event_repo.delete_event(session, event_id, profile_id)
        if success:
            logger.info(
                "event_service",
                "事件已删除",
                extra={"event_id": str(event_id), "profile_id": str(profile_id)},
            )
        return success

    # ------------------------------------------------------------------
    # ORM 转换辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _orm_to_response(event: EventLog) -> EventResponse:
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

    @staticmethod
    def _orm_to_list_item(event: EventLog) -> EventListItem:
        return EventListItem(
            event_id=event.event_id,
            event_time=event.event_time,
            behavior_type=event.behavior_type,
            severity_level=event.severity_level,
            has_professional_note=event.is_professional,
            created_at=event.created_at,
        )


__all__ = ["EventServiceImpl"]
