"""档案域仓储（ADR-010 目标态）。

Profile / EventLog / ProfessionalNote / ProfileAccess 的持久化操作。
隐私纪律：所有查询按 profile_id 物理隔离（隐私与权限 §1.2）。
"""

from __future__ import annotations

import uuid

from py_schemas.enums import AccessStatus, Outcome
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from py_db.base_repository import BaseRepository
from py_db.models.profiles import EventLog, ProfessionalNote, Profile, ProfileAccess


class ProfileRepository(BaseRepository[Profile]):
    """档案仓储。"""

    model = Profile

    async def get_by_id(
        self,
        session: AsyncSession,
        profile_id: uuid.UUID,
    ) -> Profile | None:
        """按 ID 查询档案。"""

        async def _query() -> Profile | None:
            stmt: Select = select(self.model).where(self.model.profile_id == profile_id)
            result = await session.execute(stmt)
            return result.scalars().first()

        return await self._execute_with_retry(session, "get_by_id", _query)

    async def list_by_caregiver(
        self,
        session: AsyncSession,
        caregiver_id: uuid.UUID,
    ) -> list[Profile]:
        """家属名下档案列表。"""

        async def _query() -> list[Profile]:
            stmt: Select = (
                select(self.model)
                .where(self.model.caregiver_id == caregiver_id)
                .order_by(self.model.is_default.desc(), self.model.created_at.desc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

        return await self._execute_with_retry(session, "list_by_caregiver", _query)


class EventLogRepository(BaseRepository[EventLog]):
    """事件仓储（时间线查询供趋势复盘与槽位推导兜底）。"""

    model = EventLog

    async def list_by_profile(
        self,
        session: AsyncSession,
        profile_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EventLog]:
        """按档案查询事件时间线（发生时间倒序）。"""

        async def _query() -> list[EventLog]:
            stmt: Select = (
                select(self.model)
                .where(self.model.profile_id == profile_id)
                .order_by(self.model.event_time.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

        return await self._execute_with_retry(session, "list_by_profile", _query)

    async def find_latest_by_outcome(
        self,
        session: AsyncSession,
        profile_id: uuid.UUID,
        outcome: Outcome,
    ) -> EventLog | None:
        """最近一条指定效果的事件（槽位推导兜底：outcome=有效/无效）。"""

        async def _query() -> EventLog | None:
            stmt: Select = (
                select(self.model)
                .where(self.model.profile_id == profile_id)
                .where(self.model.outcome == outcome)
                .order_by(self.model.event_time.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            return result.scalars().first()

        return await self._execute_with_retry(session, "find_latest_by_outcome", _query)


class ProfessionalNoteRepository(BaseRepository[ProfessionalNote]):
    """专业评估仓储。"""

    model = ProfessionalNote

    async def list_by_event(
        self,
        session: AsyncSession,
        event_id: uuid.UUID,
    ) -> list[ProfessionalNote]:
        """事件挂载的专业评估列表。"""

        async def _query() -> list[ProfessionalNote]:
            stmt: Select = (
                select(self.model)
                .where(self.model.event_id == event_id)
                .order_by(self.model.created_at.desc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

        return await self._execute_with_retry(session, "list_by_event", _query)


class ProfileAccessRepository(BaseRepository[ProfileAccess]):
    """档案关联仓储。"""

    model = ProfileAccess

    async def find_active(
        self,
        session: AsyncSession,
        profile_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ProfileAccess | None:
        """查询活跃关联（访问控制判定入口）。"""

        async def _query() -> ProfileAccess | None:
            stmt: Select = (
                select(self.model)
                .where(self.model.profile_id == profile_id)
                .where(self.model.user_id == user_id)
                .where(self.model.status == AccessStatus.ACTIVE)
            )
            result = await session.execute(stmt)
            return result.scalars().first()

        return await self._execute_with_retry(session, "find_active", _query)

    async def list_by_profile(
        self,
        session: AsyncSession,
        profile_id: uuid.UUID,
    ) -> list[ProfileAccess]:
        """档案的关联列表（含已解除）。"""

        async def _query() -> list[ProfileAccess]:
            stmt: Select = (
                select(self.model)
                .where(self.model.profile_id == profile_id)
                .order_by(self.model.created_at.desc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

        return await self._execute_with_retry(session, "list_by_profile", _query)

    async def list_by_user(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[ProfileAccess]:
        """用户的活跃关联档案列表（受邀协作方视角）。"""

        async def _query() -> list[ProfileAccess]:
            stmt: Select = (
                select(self.model)
                .where(self.model.user_id == user_id)
                .where(self.model.status == AccessStatus.ACTIVE)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

        return await self._execute_with_retry(session, "list_by_user", _query)


__all__ = [
    "ProfileRepository",
    "EventLogRepository",
    "ProfessionalNoteRepository",
    "ProfileAccessRepository",
]
