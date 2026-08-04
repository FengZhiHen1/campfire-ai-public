"""红线关键词仓储（ADR-008 二元安全门词库）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from py_db.base_repository import BaseRepository
from py_db.models.redline_keyword import RedlineKeyword


class RedlineKeywordRepository(BaseRepository[RedlineKeyword]):
    """红线关键词仓储——仅加载 is_active=true 的词库记录。"""

    model = RedlineKeyword

    async def list_active(self, session: AsyncSession) -> list[RedlineKeyword]:
        """加载全部启用的红线关键词。"""

        async def _query() -> list[RedlineKeyword]:
            stmt: Select = select(self.model).where(self.model.is_active.is_(True))
            result = await session.execute(stmt)
            return list(result.scalars().all())

        return await self._execute_with_retry(session, "list_active", _query)


__all__ = ["RedlineKeywordRepository"]
