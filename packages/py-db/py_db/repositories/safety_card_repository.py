"""安全卡仓储（ADR-009 目标态）。

SafetyCard 的持久化操作：此刻安全层卡供给（bucket × stage 查询）、
管理端 CRUD（M3 审核链路复用）。
"""

from __future__ import annotations

from py_schemas.enums import BehaviorBucket, CrisisStage
from py_schemas.enums.case_enums import CaseStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from py_db.base_repository import BaseRepository
from py_db.models.consultation import SafetyCard


class SafetyCardRepository(BaseRepository[SafetyCard]):
    """安全卡仓储。

    供给语义：仅供给审核通过（approved）的卡片；
    bucket/stage 为 NULL 的记录分别为通用卡/通用桶卡。
    """

    model = SafetyCard

    async def find_card(
        self,
        session: AsyncSession,
        bucket: BehaviorBucket | None,
        stage: CrisisStage | None,
    ) -> SafetyCard | None:
        """查询指定 桶×阶段 的已审核卡片（版本最新优先）。"""

        async def _query() -> SafetyCard | None:
            stmt: Select = (
                select(self.model)
                .where(self.model.review_status == CaseStatus.APPROVED)
                .order_by(self.model.version.desc())
                .limit(1)
            )
            if bucket is None:
                stmt = stmt.where(self.model.bucket.is_(None))
            else:
                stmt = stmt.where(self.model.bucket == bucket)
            if stage is None:
                stmt = stmt.where(self.model.crisis_stage.is_(None))
            else:
                stmt = stmt.where(self.model.crisis_stage == stage)
            result = await session.execute(stmt)
            return result.scalars().first()

        return await self._execute_with_retry(session, "find_card", _query)

    async def list_all(
        self,
        session: AsyncSession,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> list[SafetyCard]:
        """管理端列表（全量，含未审核）。"""

        async def _query() -> list[SafetyCard]:
            stmt: Select = (
                select(self.model)
                .order_by(self.model.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

        return await self._execute_with_retry(session, "list_all", _query)


__all__ = ["SafetyCardRepository"]
