"""事件服务——双模式记录（ADR-010 第 4 条）。

- 一键打点：仅 behavior_type + 自动时间戳（is_quick_log=true）
- 事后补全：其余字段全可选，补全后 is_quick_log 转 false
- 隐私：事件数据按 profile_id 物理隔离，绝不入向量索引
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from py_db.models.profiles import EventLog
from py_db.repositories.profile_repository import EventLogRepository
from py_schemas.enums import RecordedByRole
from py_schemas.profiles import (
    EventCompleteRequest,
    EventCreateRequest,
    EventResponse,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.profiles.exceptions import EventNotFoundError, ProfileForbiddenError
from app.modules.profiles.guard import ProfileAccessContext

# 单档案事件容量上限（数据模型 §4：超出自动归档最早记录）
_MAX_EVENTS_PER_PROFILE = 500


def _to_response(event: EventLog) -> EventResponse:
    return EventResponse(
        event_id=str(event.event_id),
        profile_id=str(event.profile_id),
        recorded_by=str(event.recorded_by) if event.recorded_by else "",
        recorded_by_role=event.recorded_by_role,
        event_time=event.event_time.isoformat(),
        is_quick_log=event.is_quick_log,
        behavior_type=event.behavior_type,
        behavior_form=event.behavior_form,
        intensity=event.intensity,
        duration=event.duration,
        setting=event.setting,
        activity=event.activity,
        people_present=event.people_present,
        physical_state=event.physical_state,
        antecedent_category=event.antecedent_category,
        trigger_description=event.trigger_description,
        consequence=event.consequence,
        reaction=event.reaction,
        outcome=event.outcome,
        function_hypothesis=event.function_hypothesis,
        manifestation=event.manifestation,
        note=event.note,
        tags=event.tags,
        created_at=event.created_at.isoformat(),
    )


class EventService:
    """事件服务。"""

    def __init__(self, event_repo: EventLogRepository) -> None:
        self._event_repo = event_repo

    async def quick_log(
        self,
        session: AsyncSession,
        viewer: ProfileAccessContext,
        user_id: str,
        request: EventCreateRequest,
    ) -> EventResponse:
        """一键打点（家属/受邀志愿者）。"""
        if not viewer.can_create_event:
            raise ProfileForbiddenError("老师/专家不直接新增事件，请使用专业评估")

        event_time = datetime.fromisoformat(request.event_time) if request.event_time else datetime.now(timezone.utc)
        role = RecordedByRole.PARENT if viewer.is_owner else RecordedByRole.VOLUNTEER

        event = EventLog(
            profile_id=viewer.profile.profile_id,
            recorded_by=uuid.UUID(user_id),
            recorded_by_role=role,
            event_time=event_time,
            is_quick_log=True,
            behavior_type=request.behavior_type,
        )
        created = await self._event_repo.create(session, event)
        await session.commit()
        return _to_response(created)

    async def complete(
        self,
        session: AsyncSession,
        viewer: ProfileAccessContext,
        event_id: str,
        request: EventCompleteRequest,
    ) -> EventResponse:
        """事后补全（仅家属——隐私矩阵：修改/删除 Event 仅家属本人）。"""
        if not viewer.is_owner:
            raise ProfileForbiddenError("仅家属可补全事件")

        try:
            eid = uuid.UUID(event_id)
        except ValueError:
            raise EventNotFoundError() from None

        event = await self._event_repo.find_by_id(session, eid)
        if event is None or event.profile_id != viewer.profile.profile_id:
            raise EventNotFoundError()

        data = request.model_dump(exclude_unset=True)
        for field_name, value in data.items():
            if value is not None and hasattr(event, field_name):
                setattr(event, field_name, value)
        event.is_quick_log = False
        await session.commit()
        return _to_response(event)

    async def list_events(
        self,
        session: AsyncSession,
        viewer: ProfileAccessContext,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EventResponse]:
        """事件时间线（家属/关联者均可查看）。"""
        events = await self._event_repo.list_by_profile(
            session, viewer.profile.profile_id, limit=limit, offset=offset
        )
        return [_to_response(e) for e in events]


__all__ = ["EventService"]
