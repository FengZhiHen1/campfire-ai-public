"""PROF-05 档案隐私控制 — TeacherLinkRepository。

提供 teacher_links 表的查询方法：
- find_active_links(): 查询指定档案与指定用户的有效关联（unlinked_at IS NULL）
- find_links_by_profile(): 查询指定档案的所有关联关系
- unlink_teacher(): 解除关联（含乐观锁版本校验）

所有查询均包含 unlinked_at IS NULL 条件以确保关联关系的实时有效性。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import InvalidRequestError as _SAInvalidRequestError

from py_db.sqlalchemy_helpers import rowcount

class StaleDataError(_SAInvalidRequestError):
    """乐观锁版本冲突异常（SQLAlchemy 2.0 兼容层 — StaleDataError 已于 2.0 移除）."""
    pass
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select, func

from py_db.models.profiles import TeacherLink
from py_db.base_repository import BaseRepository


class TeacherLinkRepository(BaseRepository[TeacherLink]):
    """家属-老师关联关系 Repository。

    继承 BaseRepository[TeacherLink] 获得通用 CRUD 方法骨架，
    另提供针对 PROF-05 权限校验场景的专用查询方法。

    Usage:
        repo = TeacherLinkRepository(session_factory=async_session_factory)
        link = await repo.find_active_links(session, profile_id, teacher_id)
    """

    model = TeacherLink

    # ------------------------------------------------------------------
    # 查询方法
    # ------------------------------------------------------------------

    async def find_active_links(
        self,
        session: AsyncSession,
        profile_id: object,
        teacher_id: object,
    ) -> TeacherLink | None:
        """查询指定档案与指定用户的有效关联关系。

        执行 SELECT ... WHERE profile_id=$1 AND teacher_id=$2
        AND unlinked_at IS NULL，确保返回的关联关系当前有效。

        用于 PrivacyGuard.check_access() 中判定 teacher/expert 角色
        是否与目标档案存在有效关联。

        Args:
            session: 活动数据库会话。
            profile_id: 目标个人档案 UUID。
            teacher_id: 请求发起人（老师/专家）的用户 UUID。

        Returns:
            匹配的 TeacherLink 实例（仅返回第一条匹配记录），
            不存在有效关联时返回 None。
        """
        async def _query() -> TeacherLink | None:
            stmt: Select = (
                select(self.model)
                .where(self.model.profile_id == profile_id)
                .where(self.model.teacher_id == teacher_id)
                .where(self.model.unlinked_at.is_(None))
            )
            result = await session.execute(stmt)
            return result.scalars().first()

        return await self._execute_with_retry(
            session, "find_active_links", _query,
        )

    async def find_links_by_profile(
        self,
        session: AsyncSession,
        profile_id: object,
    ) -> list[TeacherLink]:
        """查询指定档案的全部关联关系。

        执行 SELECT ... WHERE profile_id=$1 AND unlinked_at IS NULL，
        返回该档案当前所有有效关联（未解除）。

        Args:
            session: 活动数据库会话。
            profile_id: 目标个人档案 UUID。

        Returns:
            有效关联列表，无关联时返回空列表。
        """
        async def _query() -> list[TeacherLink]:
            stmt: Select = (
                select(self.model)
                .where(self.model.profile_id == profile_id)
                .where(self.model.unlinked_at.is_(None))
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

        return await self._execute_with_retry(
            session, "find_links_by_profile", _query,
        )

    # ------------------------------------------------------------------
    # 写入方法
    # ------------------------------------------------------------------

    async def unlink_teacher(
        self,
        session: AsyncSession,
        link_id: object,
        expected_version: int,
    ) -> None:
        """解除老师关联（含乐观锁版本校验）。

        执行 UPDATE teacher_links SET unlinked_at=NOW(), version=version+1
        WHERE link_id=$1 AND version=$2。

        若受影响行数为 0（版本不匹配或 link_id 不存在），抛出 StaleDataError。

        Args:
            session: 活动数据库会话。
            link_id: 待解除关联的 link_id。
            expected_version: 期望的版本号（读取时的 version 值）。

        Raises:
            StaleDataError: 版本不匹配（其他家属已先完成了解除操作）
                            或 link_id 不存在。
        """
        async def _unlink() -> None:
            now = datetime.now(timezone.utc)
            stmt = (
                update(TeacherLink)
                .where(TeacherLink.link_id == link_id)
                .where(TeacherLink.version == expected_version)
                .values(
                    unlinked_at=now,
                    version=TeacherLink.version + 1,
                )
            )
            result = await session.execute(stmt)
            if rowcount(result) == 0:
                raise StaleDataError(
                    f"乐观锁冲突：link_id={link_id} 的版本不匹配，"
                    f"期望 version={expected_version}，"
                    f"实际版本已被其他事务变更"
                )

        await self._execute_with_retry(
            session, "unlink_teacher", _unlink,
        )


__all__ = [
    "TeacherLinkRepository",
]
