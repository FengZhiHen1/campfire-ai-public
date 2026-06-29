"""CASE-01 L1 叙事层 — NarrativeRepository。

封装 case_narratives 表的参数化查询方法，确保 Service 层
不直接操作数据库会话。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select, func as sa_func

from py_db.models.case_narrative import CaseNarrative
from py_db.base_repository import BaseRepository
from py_db.sqlalchemy_helpers import rowcount
from py_schemas.enums.case_enums import CaseStatus


class NarrativeRepository(BaseRepository[CaseNarrative]):
    """叙事 Repository。

    继承 BaseRepository[CaseNarrative] 获得通用 CRUD 方法骨架，
    另提供叙事专属查询方法。

    Usage:
        repo = NarrativeRepository(session_factory=async_session_factory)
        narratives, total = await repo.find_by_filters(session, status=CaseStatus.PENDING_REVIEW)
    """

    model = CaseNarrative

    async def find_by_narrative_id(
        self,
        session: AsyncSession,
        narrative_id: str,
    ) -> CaseNarrative | None:
        """按 narrative_id 查询单条叙事。

        Args:
            session: 活动数据库会话。
            narrative_id: 叙事 UUID（字符串或 UUID 对象均可）。

        Returns:
            匹配的 CaseNarrative 实例，不存在时返回 None。
        """
        async def _query() -> CaseNarrative | None:
            uid = UUID(narrative_id) if isinstance(narrative_id, str) else narrative_id
            stmt: Select = select(self.model).where(self.model.narrative_id == uid)
            result = await session.execute(stmt)
            return result.scalars().first()

        return await self._execute_with_retry(session, "find_by_narrative_id", _query)

    async def update_status(
        self,
        session: AsyncSession,
        narrative_id: str,
        new_status: CaseStatus,
        expected_status: CaseStatus | None = None,
        review_comment: str | None = None,
    ) -> CaseNarrative:
        """原子性更新叙事状态。

        若提供 expected_status，使用 CAS 乐观锁。
        """
        async def _update() -> CaseNarrative:
            uid = UUID(narrative_id) if isinstance(narrative_id, str) else narrative_id
            conditions = [self.model.narrative_id == uid]
            if expected_status is not None:
                conditions.append(self.model.status == expected_status)

            values: dict[str, object] = {"status": new_status}
            if review_comment is not None:
                values["review_comment"] = review_comment

            result = await session.execute(
                sa_update(self.model).where(and_(*conditions)).values(**values)
            )
            if rowcount(result) == 0:
                raise ValueError(
                    f"叙事 {narrative_id} 不存在或状态已变更（预期 {expected_status}）"
                )

            narrative = await self.find_by_narrative_id(session, narrative_id)
            assert narrative is not None
            await session.refresh(narrative)
            return narrative

        return await self._execute_with_retry(session, "update_status", _update)

    async def find_by_filters(
        self,
        session: AsyncSession,
        status: CaseStatus | None = None,
        author_id: str | None = None,
        keyword: str | None = None,
        sort_by: str | None = None,
        page: int = 1,
        page_size: int = 15,
    ) -> tuple[list[CaseNarrative], int]:
        """按多条件筛选叙事，支持分页、搜索和动态排序。

        Args:
            session: 活动数据库会话。
            status: 可选状态筛选（draft/pending_review/rejected）。
            author_id: 可选作者筛选。
            keyword: 可选关键词（模糊匹配 title）。
            sort_by: 可选排序方式（latest/updated）。
            page: 页码，从 1 开始。
            page_size: 每页条数，默认 15。

        Returns:
            (narratives, total_count) 元组。
        """
        async def _query() -> tuple[list[CaseNarrative], int]:
            conditions: list[Any] = []
            if status is not None:
                conditions.append(self.model.status == status)
            if author_id is not None:
                uid = UUID(author_id) if isinstance(author_id, str) else author_id
                conditions.append(self.model.author_id == uid)
            if keyword is not None:
                kw = f"%{keyword}%"
                conditions.append(self.model.title.ilike(kw))

            # 总数查询
            count_stmt: Select = select(sa_func.count()).select_from(self.model)
            if conditions:
                count_stmt = count_stmt.where(*conditions)
            count_result = await session.execute(count_stmt)
            total_count: int = count_result.scalar() or 0

            # 排序字段映射
            sort_column = {
                "updated": self.model.updated_at,
            }.get(sort_by or "", self.model.created_at)

            # 分页查询
            offset: int = (page - 1) * page_size
            data_stmt: Select = (
                select(self.model)
                .where(*conditions if conditions else [True])
                .order_by(sort_column.desc())
                .offset(offset)
                .limit(page_size)
            )
            data_result = await session.execute(data_stmt)
            narratives: list[CaseNarrative] = list(data_result.scalars().all())

            return narratives, total_count

        return await self._execute_with_retry(session, "find_by_filters", _query)


__all__ = ["NarrativeRepository"]
