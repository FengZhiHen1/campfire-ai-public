# @contract
"""profiles 事件记录行为契约 — ABC 模板方法骨架。

模块: app.modules.profiles.events_contract
职责: 定义事件记录 CRUD 的业务编排契约。覆盖 PROF-03 的五个核心操作：
      列表查询、创建、详情查询、更新、删除。
      每个 @final 公共入口强制执行 前置校验 → _do_ 钩子 → 后置校验 三步流程，
      实现者只能覆写 _do_ 前缀的钩子方法。

数据来源:
  - py_db.repositories.event_repository.EventRepository: MUST — 事件持久化
  - py_db.repositories.profile_repository.ProfileRepository: MUST — 档案存在性校验
  - py_schemas.profiles (EventCreate, EventUpdate, EventResponse, EventListItem): MUST — 数据契约
  - py_logger: SHOULD — 结构化操作日志

边界:
  - 依赖: py_db, py_schemas, sqlalchemy (AsyncSession)
  - 被依赖: event_routes.py (FastAPI 路由层)

禁止行为:
  - 禁止在 @final 方法中直接调用 Repository 方法（必须走 _do_ 钩子）
  - 禁止在 _do_ 钩子中直接操作 FastAPI HTTPException
  - 禁止实现者覆写 @final 方法
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, final

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.profiles._profile_guard import ensure_profile_exists
from app.modules.profiles.exceptions import (
    EventNotFoundError,
    EventTimeOutOfRangeError,
)

if TYPE_CHECKING:
    from py_db.repositories.event_repository import EventRepository
    from py_db.repositories.profile_repository import ProfileRepository
    from py_schemas.cases import PaginatedResponse
    from py_schemas.profiles import (
        EventCreate,
        EventListItem,
        EventResponse,
        EventUpdate,
    )
    from uuid import UUID


class BaseEventService(ABC):
    """事件记录管理服务契约 — 业务编排层 ABC。

    实现者只能覆写 _do_ 前缀的钩子方法。
    """

    def __init__(
        self,
        event_repository: "EventRepository",
        profile_repository: "ProfileRepository",
    ) -> None:
        self._event_repo = event_repository
        self._profile_repo = profile_repository

    # ======================================================================
    # 事件列表 — PROF-03
    # ======================================================================

    @final
    async def list_events(
        self,
        profile_id: "UUID",
        caregiver_id: "UUID",
        page: int,
        page_size: int,
        session: AsyncSession,
    ) -> "PaginatedResponse[EventListItem]":
        """查询指定档案的事件列表（分页）。

        前置: profile_id 存在且归属 caregiver_id
        后置: 返回分页事件列表
        异常: ProfileNotFoundError
        """
        await ensure_profile_exists(self._profile_repo, profile_id, caregiver_id, session)
        return await self._do_list_events(profile_id, page, page_size, session)

    @abstractmethod
    async def _do_list_events(
        self,
        profile_id: "UUID",
        page: int,
        page_size: int,
        session: AsyncSession,
    ) -> "PaginatedResponse[EventListItem]":
        """执行事件列表查询。"""
        ...

    # ======================================================================
    # 创建事件 — PROF-03
    # ======================================================================

    @final
    async def create_event(
        self,
        profile_id: "UUID",
        user_id: "UUID",
        input_data: "EventCreate",
        session: AsyncSession,
    ) -> "EventResponse":
        """为指定档案创建新事件记录。

        前置: profile_id 存在且归属 user_id，event_time 在 30 天追溯期内
        后置: 返回新创建的 EventResponse
        异常: ProfileNotFoundError, EventTimeOutOfRangeError
        """
        await ensure_profile_exists(self._profile_repo, profile_id, user_id, session)
        self._validate_event_within_retrospective_window(input_data.event_time)
        result = await self._do_create_event(profile_id, user_id, input_data, session)
        if result is None:
            raise RuntimeError("创建事件返回 None")
        return result

    @abstractmethod
    async def _do_create_event(
        self,
        profile_id: "UUID",
        user_id: "UUID",
        input_data: "EventCreate",
        session: AsyncSession,
    ) -> "EventResponse":
        """执行事件创建。"""
        ...

    # ======================================================================
    # 事件详情 — PROF-03
    # ======================================================================

    @final
    async def get_event(
        self,
        event_id: "UUID",
        profile_id: "UUID",
        caregiver_id: "UUID",
        session: AsyncSession,
    ) -> "EventResponse":
        """查询单条事件详情。

        前置: profile_id 存在且归属 caregiver_id，event_id 存在
        后置: 返回 EventResponse
        异常: ProfileNotFoundError, EventNotFoundError
        """
        await ensure_profile_exists(self._profile_repo, profile_id, caregiver_id, session)
        result = await self._do_get_event(event_id, profile_id, session)
        if result is None:
            raise EventNotFoundError(str(event_id), str(profile_id))
        return result

    @abstractmethod
    async def _do_get_event(
        self,
        event_id: "UUID",
        profile_id: "UUID",
        session: AsyncSession,
    ) -> "EventResponse | None":
        """执行事件详情查询。"""
        ...

    # ======================================================================
    # 更新事件 — PROF-03
    # ======================================================================

    @final
    async def update_event(
        self,
        event_id: "UUID",
        profile_id: "UUID",
        caregiver_id: "UUID",
        input_data: "EventUpdate",
        session: AsyncSession,
    ) -> "EventResponse":
        """更新事件记录（Merge Patch 语义）。

        前置: profile_id 存在且归属 caregiver_id。
              若修改 event_time，需在 30 天追溯期内。
        异常: ProfileNotFoundError, EventNotFoundError, EventTimeOutOfRangeError
        """
        await ensure_profile_exists(self._profile_repo, profile_id, caregiver_id, session)
        # 若用户修改了 event_time，校验追溯期
        update_dict = input_data.model_dump(exclude_unset=True)
        new_event_time = update_dict.get("event_time")
        if new_event_time is not None:
            self._validate_event_within_retrospective_window(new_event_time)
        result = await self._do_update_event(event_id, profile_id, input_data, session)
        if result is None:
            raise EventNotFoundError(str(event_id), str(profile_id))
        return result

    @abstractmethod
    async def _do_update_event(
        self,
        event_id: "UUID",
        profile_id: "UUID",
        input_data: "EventUpdate",
        session: AsyncSession,
    ) -> "EventResponse | None":
        """执行事件更新。"""
        ...

    # ======================================================================
    # 删除事件 — PROF-03
    # ======================================================================

    @final
    async def delete_event(
        self,
        event_id: "UUID",
        profile_id: "UUID",
        caregiver_id: "UUID",
        session: AsyncSession,
    ) -> None:
        """删除指定事件记录。

        前置: profile_id 存在且归属 caregiver_id
        异常: ProfileNotFoundError, EventNotFoundError
        """
        await ensure_profile_exists(self._profile_repo, profile_id, caregiver_id, session)
        success = await self._do_delete_event(event_id, profile_id, session)
        if not success:
            raise EventNotFoundError(str(event_id), str(profile_id))

    @abstractmethod
    async def _do_delete_event(
        self,
        event_id: "UUID",
        profile_id: "UUID",
        session: AsyncSession,
    ) -> bool:
        """执行事件删除。返回 True 表示删除成功。"""
        ...

    # ======================================================================
    # 校验器
    # ======================================================================

    @staticmethod
    def _validate_event_within_retrospective_window(event_time: datetime) -> None:
        """校验事件时间在追溯期内。

        Raises:
            EventTimeOutOfRangeError: 事件超出追溯期。
        """
        from app.modules.profiles._constants import EVENT_RETROSPECTIVE_DAYS

        cutoff = datetime.now(timezone.utc) - timedelta(days=EVENT_RETROSPECTIVE_DAYS)
        et = event_time
        if et.tzinfo is None:
            et = et.replace(tzinfo=timezone.utc)
        if et < cutoff:
            raise EventTimeOutOfRangeError(et.isoformat(), EVENT_RETROSPECTIVE_DAYS)


__all__ = ["BaseEventService"]
