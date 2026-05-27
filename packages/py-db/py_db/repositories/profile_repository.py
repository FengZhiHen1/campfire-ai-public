"""PROF-01 个人档案管理 — Repository 层。

提供 Profile 实体的所有数据库操作封装。
所有方法必须通过 AsyncSession 参数化查询执行，
禁止 SQL 字符串拼接。

方法清单：
- create() — INSERT 新档案
- get_by_id() — 按 profile_id + caregiver_id 查询单条
- list_by_caregiver() — 按 caregiver_id 分页查询
- count_active_by_caregiver() — 统计某家属账号下档案总数
- update_with_optimistic_lock() — 带乐观锁的 UPDATE（比较 updated_at）
- delete() — 硬删除（DELETE）
- get_default() — 查询某家属的默认档案
- set_default() — 设置指定档案为默认（原子操作）
- unset_default_for_caregiver() — 取消某家属的所有默认标记
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.models.profiles import Profile


class ProfileRepository:
    """个人档案数据库操作封装。

    所有方法接收 AsyncSession 作为参数，支持跨方法的事务编排。
    不持有 session 状态，无状态设计。
    """

    def __init__(self, session_factory: Any) -> None:
        """初始化 Repository 实例。

        Args:
            session_factory: 异步会话工厂（当前未使用，保留兼容 BaseRepository 接口）。
        """
        self._session_factory = session_factory

    async def create(
        self,
        session: AsyncSession,
        profile: Profile,
    ) -> Profile:
        """创建新档案记录。

        Args:
            session: 活动数据库会话。
            profile: 待创建的 Profile ORM 实例。

        Returns:
            Profile: 创建成功的实体（含数据库生成的时间戳）。
        """
        session.add(profile)
        await session.flush()
        await session.refresh(profile)
        return profile

    async def get_by_id(
        self,
        session: AsyncSession,
        profile_id: UUID,
        caregiver_id: UUID,
    ) -> Profile | None:
        """按 profile_id 和 caregiver_id 查询单条记录。

        Args:
            session: 活动数据库会话。
            profile_id: 目标档案 UUID。
            caregiver_id: 所属家属 UUID。

        Returns:
            Profile | None: 匹配的档案，不存在时返回 None。
        """
        stmt = select(Profile).where(
            Profile.profile_id == profile_id,
            Profile.caregiver_id == caregiver_id,
        )
        result = await session.execute(stmt)
        return result.scalars().first()

    async def list_by_caregiver(
        self,
        session: AsyncSession,
        caregiver_id: UUID,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[Profile], int]:
        """按 caregiver_id 分页查询档案列表。

        Args:
            session: 活动数据库会话。
            caregiver_id: 所属家属 UUID。
            page: 页码（从 1 开始）。
            page_size: 每页条数（默认 10）。

        Returns:
            tuple[list[Profile], int]: (档案列表, 总记录数)。
        """
        # 查询总记录数
        count_stmt = select(func.count()).select_from(Profile).where(
            Profile.caregiver_id == caregiver_id,
        )
        total_result = await session.execute(count_stmt)
        total: int = total_result.scalar() or 0

        # 分页查询
        offset = (page - 1) * page_size
        query_stmt = (
            select(Profile)
            .where(Profile.caregiver_id == caregiver_id)
            .order_by(Profile.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await session.execute(query_stmt)
        profiles = list(result.scalars().all())

        return profiles, total

    async def count_active_by_caregiver(
        self,
        session: AsyncSession,
        caregiver_id: UUID,
    ) -> int:
        """统计某家属账号下所有档案总数。

        Args:
            session: 活动数据库会话。
            caregiver_id: 所属家属 UUID。

        Returns:
            int: 档案总数。
        """
        stmt = select(func.count()).select_from(Profile).where(
            Profile.caregiver_id == caregiver_id,
        )
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def update_with_optimistic_lock(
        self,
        session: AsyncSession,
        profile_id: UUID,
        caregiver_id: UUID,
        previous_updated_at: datetime,
        update_data: dict[str, Any],
    ) -> Profile | None:
        """带乐观锁的更新操作。

        使用 UPDATE ... WHERE profile_id=? AND caregiver_id=? AND updated_at=?
        的原子语义检测并发冲突。若更新行数为 0，说明 updated_at 已变化。

        Args:
            session: 活动数据库会话。
            profile_id: 目标档案 UUID。
            caregiver_id: 所属家属 UUID。
            previous_updated_at: 乐观锁期望的 updated_at 值。
            update_data: 需要更新的字段字典。

        Returns:
            Profile | None: 更新后的档案，乐观锁冲突时返回 None。
        """
        stmt = (
            update(Profile)
            .where(
                Profile.profile_id == profile_id,
                Profile.caregiver_id == caregiver_id,
                Profile.updated_at == previous_updated_at,
            )
            .values(**update_data)
            .returning(Profile)
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.scalars().first()

    async def delete(
        self,
        session: AsyncSession,
        profile_id: UUID,
        caregiver_id: UUID,
    ) -> bool:
        """硬删除指定档案。

        Args:
            session: 活动数据库会话。
            profile_id: 目标档案 UUID。
            caregiver_id: 所属家属 UUID。

        Returns:
            bool: 是否成功删除（True 表示有记录被删除）。
        """
        stmt = (
            delete(Profile)
            .where(
                Profile.profile_id == profile_id,
                Profile.caregiver_id == caregiver_id,
            )
            .returning(Profile.profile_id)
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.scalars().first() is not None

    async def get_default(
        self,
        session: AsyncSession,
        caregiver_id: UUID,
    ) -> Profile | None:
        """查询某家属账号的默认档案。

        Args:
            session: 活动数据库会话。
            caregiver_id: 所属家属 UUID。

        Returns:
            Profile | None: 默认档案，不存在时返回 None。
        """
        stmt = select(Profile).where(
            Profile.caregiver_id == caregiver_id,
            Profile.is_default == True,  # noqa: E712
        )
        result = await session.execute(stmt)
        return result.scalars().first()

    async def set_default(
        self,
        session: AsyncSession,
        profile_id: UUID,
        caregiver_id: UUID,
    ) -> Profile | None:
        """设置指定档案为默认档案。

        在同一个事务中先取消该家属的所有默认标记，
        再设置目标档案为默认。

        Args:
            session: 活动数据库会话。
            profile_id: 目标档案 UUID。
            caregiver_id: 所属家属 UUID。

        Returns:
            Profile | None: 设置成功后的档案。
        """
        # 步骤 1: 取消该家属的所有默认标记
        unset_stmt = (
            update(Profile)
            .where(
                Profile.caregiver_id == caregiver_id,
                Profile.is_default == True,  # noqa: E712
            )
            .values(is_default=False)
        )
        await session.execute(unset_stmt)

        # 步骤 2: 设置目标档案为默认
        set_stmt = (
            update(Profile)
            .where(
                Profile.profile_id == profile_id,
                Profile.caregiver_id == caregiver_id,
            )
            .values(is_default=True)
            .returning(Profile)
        )
        result = await session.execute(set_stmt)
        await session.flush()
        return result.scalars().first()

    async def find_next_default_candidate(
        self,
        session: AsyncSession,
        caregiver_id: UUID,
        exclude_profile_id: UUID,
    ) -> Profile | None:
        """查找除指定档案外最新更新的档案，作为默认档案候选。

        用于删除默认档案时，查找应被提升为默认的下一候选档案。
        按 updated_at 降序选取最新更新的档案（排除当前待删除的档案）。

        Args:
            session: 活动数据库会话。
            caregiver_id: 所属家属 UUID。
            exclude_profile_id: 需要排除的档案 UUID（通常是待删除的档案）。

        Returns:
            Profile | None: 找到的候选档案，不存在（无其他档案）时返回 None。
        """
        stmt = (
            select(Profile)
            .where(
                Profile.caregiver_id == caregiver_id,
                Profile.profile_id != exclude_profile_id,
            )
            .order_by(Profile.updated_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalars().first()

    async def unset_default_for_caregiver(
        self,
        session: AsyncSession,
        caregiver_id: UUID,
    ) -> None:
        """取消某家属账号下的所有默认档案标记。

        Args:
            session: 活动数据库会话。
            caregiver_id: 所属家属 UUID。
        """
        stmt = (
            update(Profile)
            .where(
                Profile.caregiver_id == caregiver_id,
                Profile.is_default == True,  # noqa: E712
            )
            .values(is_default=False)
        )
        await session.execute(stmt)
        await session.flush()


__all__ = [
    "ProfileRepository",
]
