"""认证域 — InviteCodeRepository（ADR-013 目标态）。

提供 invite_codes 表的参数化查询能力。
核心机制：注册原子消费——条件自增 UPDATE 防并发复用（认证与访问 §4.2 / §九）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from py_schemas.enums import InviteCodeStatus
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from py_db.base_repository import BaseRepository
from py_db.models.auth import InviteCode


class InviteCodeRepository(BaseRepository[InviteCode]):
    """邀请码 Repository。

    继承 BaseRepository[InviteCode] 获得通用 CRUD 方法骨架，
    另提供原子消费、按码查询与停用能力。

    Usage:
        repo = InviteCodeRepository(session_factory=async_session_factory)
        consumed = await repo.consume_if_valid(session, "ABCD2345")
    """

    model = InviteCode

    async def find_by_code(
        self,
        session: AsyncSession,
        code: str,
    ) -> InviteCode | None:
        """按码精确查询（主键命中）。"""

        async def _query() -> InviteCode | None:
            stmt: Select = select(self.model).where(self.model.code == code)
            result = await session.execute(stmt)
            return result.scalars().first()

        return await self._execute_with_retry(session, "find_by_code", _query)

    async def consume_if_valid(
        self,
        session: AsyncSession,
        code: str,
    ) -> InviteCode | None:
        """原子消费邀请码——条件自增防并发复用。

        单条 UPDATE ... WHERE status=active AND used_count<max_uses
        AND expires_at>now() RETURNING *：
        - 命中（码有效且有余量）→ used_count+1 并返回更新后的行；
        - 未命中（不存在/已停用/已过期/已用完）→ 返回 None；
        并发下仅一个事务的条件自增成功（认证与访问 §九 失败语义）。

        Args:
            session: 活动数据库会话（调用方负责提交事务）。
            code: 待消费的邀请码。

        Returns:
            消费成功返回更新后的 InviteCode，否则返回 None。
        """

        async def _query() -> InviteCode | None:
            stmt = (
                update(self.model)
                .where(self.model.code == code)
                .where(self.model.status == InviteCodeStatus.ACTIVE)
                .where(self.model.used_count < self.model.max_uses)
                .where(self.model.expires_at > datetime.now(timezone.utc))
                .values(used_count=self.model.used_count + 1)
                .returning(self.model)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

        return await self._execute_with_retry(session, "consume_if_valid", _query)

    async def revoke(
        self,
        session: AsyncSession,
        code: str,
    ) -> InviteCode | None:
        """停用邀请码（active → revoked）。不存在时返回 None。"""

        async def _query() -> InviteCode | None:
            stmt = (
                update(self.model)
                .where(self.model.code == code)
                .values(status=InviteCodeStatus.REVOKED)
                .returning(self.model)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

        return await self._execute_with_retry(session, "revoke", _query)

    async def list_all(
        self,
        session: AsyncSession,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> list[InviteCode]:
        """邀请码列表（管理端），按生成时间倒序。"""

        async def _query() -> list[InviteCode]:
            stmt: Select = (
                select(self.model)
                .order_by(self.model.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

        return await self._execute_with_retry(session, "list_all", _query)


__all__ = ["InviteCodeRepository"]
