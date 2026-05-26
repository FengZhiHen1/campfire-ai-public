"""AUTH-01 用户注册 — UserRepository。

提供 users 表的参数化查询能力，封装用户名大小写不敏感唯一性查询
和手机号精确匹配查询，确保 Service 层不直接操作数据库会话。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from py_db.models.auth import User
from py_db.repositories.base_repository import BaseRepository


class UserRepository(BaseRepository[User]):
    """用户账号 Repository。

    继承 BaseRepository[User] 获得通用 CRUD 方法骨架（create / find_by_id /
    find_all / update / delete），另提供用户名唯一性查询和手机号唯一性查询。

    Usage:
        repo = UserRepository(session_factory=async_session_factory)
        existing = await repo.find_by_username_lower(session, "zhang_san")
    """

    model = User

    # ------------------------------------------------------------------
    # 自定义查询方法
    # ------------------------------------------------------------------

    async def find_by_username_lower(
        self,
        session: AsyncSession,
        username: str,
    ) -> User | None:
        """大小写不敏感用户名唯一性查询。

        通过 LOWER(username) = LOWER(:username) 实现大小写不敏感匹配，
        保留用户输入的原始大小写存储方式。

        Args:
            session: 活动数据库会话。
            username: 待查询的用户名。

        Returns:
            匹配的 User 实例，不存在时返回 None。
        """
        async def _query() -> User | None:
            stmt: Select = select(self.model).where(
                func.lower(self.model.username) == func.lower(username)
            )
            result = await session.execute(stmt)
            return result.scalars().first()

        return await self._execute_with_retry(session, "find_by_username_lower", _query)

    async def find_by_phone(
        self,
        session: AsyncSession,
        phone: str,
    ) -> User | None:
        """手机号精确匹配唯一性查询。

        执行 WHERE phone = :phone 精确匹配，
        走 idx_users_phone 唯一索引。

        Args:
            session: 活动数据库会话。
            phone: 待查询的手机号。

        Returns:
            匹配的 User 实例，不存在时返回 None。
        """
        async def _query() -> User | None:
            stmt: Select = select(self.model).where(self.model.phone == phone)
            result = await session.execute(stmt)
            return result.scalars().first()

        return await self._execute_with_retry(session, "find_by_phone", _query)


__all__ = ["UserRepository"]
