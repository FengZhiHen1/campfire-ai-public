"""应急咨询会话仓储（ADR-009 目标态）。

ConsultationSession / Consultation / ConsultationLog 的持久化操作。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from py_db.base_repository import BaseRepository
from py_db.models.consultation import Consultation, ConsultationLog, ConsultationSession


class ConsultationSessionRepository(BaseRepository[ConsultationSession]):
    """应急咨询会话仓储。"""

    model = ConsultationSession

    async def list_by_user(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ConsultationSession]:
        """按用户查询会话列表（创建时间倒序）。"""

        async def _query() -> list[ConsultationSession]:
            stmt: Select = (
                select(self.model)
                .where(self.model.user_id == user_id)
                .order_by(self.model.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

        return await self._execute_with_retry(session, "list_by_user", _query)


class ConsultationRepository(BaseRepository[Consultation]):
    """咨询轮次仓储。"""

    model = Consultation

    async def list_by_session(
        self,
        session: AsyncSession,
        session_id: uuid.UUID,
    ) -> list[Consultation]:
        """按会话查询全部轮次（创建时间升序）。"""

        async def _query() -> list[Consultation]:
            stmt: Select = (
                select(self.model)
                .where(self.model.session_id == session_id)
                .order_by(self.model.created_at.asc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

        return await self._execute_with_retry(session, "list_by_session", _query)

    async def count_followups(
        self,
        session: AsyncSession,
        session_id: uuid.UUID,
    ) -> int:
        """追问轮次计数（连续追问超阈值兜底信号判定用）。"""

        async def _query() -> int:
            from sqlalchemy import func

            stmt = (
                select(func.count())
                .select_from(self.model)
                .where(self.model.session_id == session_id)
                .where(self.model.turn_type == "followup")
            )
            result = await session.execute(stmt)
            return int(result.scalar_one())

        return await self._execute_with_retry(session, "count_followups", _query)


class ConsultationLogRepository(BaseRepository[ConsultationLog]):
    """咨询日志仓储（含红线事件）。"""

    model = ConsultationLog


__all__ = [
    "ConsultationSessionRepository",
    "ConsultationRepository",
    "ConsultationLogRepository",
]
