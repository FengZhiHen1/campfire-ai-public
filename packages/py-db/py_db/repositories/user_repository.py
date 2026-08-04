"""认证域 — UserRepository（ADR-013 目标态）。

提供 users 表的参数化查询能力。登录标识统一为手机号，
username/device_id 查询已随匿名演示轨废除。
"""

from __future__ import annotations

from collections.abc import Sequence

from py_schemas.auth import UserRole
from py_schemas.enums import AccountStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from py_db.base_repository import BaseRepository
from py_db.models.auth import User


class UserRepository(BaseRepository[User]):
    """用户账号 Repository。

    继承 BaseRepository[User] 获得通用 CRUD 方法骨架（create / find_by_id /
    find_all / update / delete），另提供手机号唯一性查询与准入审核列表查询。

    Usage:
        repo = UserRepository(session_factory=async_session_factory)
        existing = await repo.find_by_phone(session, "13800138000")
    """

    model = User

    async def find_by_phone(
        self,
        session: AsyncSession,
        phone: str,
    ) -> User | None:
        """手机号精确匹配唯一性查询。

        执行 WHERE phone = :phone 精确匹配，走 users.phone 唯一索引。

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

    async def list_by_status_and_roles(
        self,
        session: AsyncSession,
        statuses: Sequence[AccountStatus],
        roles: Sequence[UserRole],
    ) -> list[User]:
        """按账号状态 + 角色集合过滤用户列表（准入审核队列）。

        Args:
            session: 活动数据库会话。
            statuses: 账号状态集合（如 [PENDING_REVIEW, REJECTED]）。
            roles: 角色集合（如 [TEACHER, EXPERT]）。

        Returns:
            匹配的 User 列表，按注册时间升序（先申请先审）。
        """

        async def _query() -> list[User]:
            stmt: Select = (
                select(self.model)
                .where(self.model.status.in_(list(statuses)))
                .where(self.model.role.in_(list(roles)))
                .order_by(self.model.created_at.asc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

        return await self._execute_with_retry(session, "list_by_status_and_roles", _query)


__all__ = ["UserRepository"]
