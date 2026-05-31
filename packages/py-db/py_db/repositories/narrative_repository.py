"""CASE-01 L1 叙事层 — NarrativeRepository。

封装 case_narratives 表的参数化查询方法，确保 Service 层
不直接操作数据库会话。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select, func as sa_func

from py_db.models.case_narrative import CaseNarrative
from py_db.base_repository import BaseRepository
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
                conditions.append(self.model.author_id == author_id)
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
