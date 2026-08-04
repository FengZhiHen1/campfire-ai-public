"""认证域 — CredentialRepository（ADR-013 目标态）。

提供 credentials 表的参数化查询能力。
核心查询：(type, identifier) 唯一凭证定位（登录凭证校验入口）。
"""

from __future__ import annotations

from py_schemas.enums import CredentialType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from py_db.base_repository import BaseRepository
from py_db.models.auth import Credential


class CredentialRepository(BaseRepository[Credential]):
    """渠道凭证 Repository。

    继承 BaseRepository[Credential] 获得通用 CRUD 方法骨架，
    另提供 (type, identifier) 唯一凭证查询。

    Usage:
        repo = CredentialRepository(session_factory=async_session_factory)
        cred = await repo.find_by_type_and_identifier(session, CredentialType.PASSWORD, "13800138000")
    """

    model = Credential

    async def find_by_type_and_identifier(
        self,
        session: AsyncSession,
        cred_type: CredentialType,
        identifier: str,
    ) -> Credential | None:
        """(type, identifier) 唯一凭证查询。

        走 uq_credentials_type_identifier 唯一约束索引。

        Args:
            session: 活动数据库会话。
            cred_type: 渠道类型（password / wechat）。
            identifier: 渠道内唯一标识（password 渠道为手机号）。

        Returns:
            匹配的 Credential 实例，不存在时返回 None。
        """

        async def _query() -> Credential | None:
            stmt: Select = select(self.model).where(
                self.model.type == cred_type,
                self.model.identifier == identifier,
            )
            result = await session.execute(stmt)
            return result.scalars().first()

        return await self._execute_with_retry(session, "find_by_type_and_identifier", _query)


__all__ = ["CredentialRepository"]
