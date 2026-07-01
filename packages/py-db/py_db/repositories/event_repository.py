"""PROF-03 事件记录管理 — Repository 层。

提供 EventLog 实体的所有数据库操作封装。
继承 BaseRepository[EventLog] 获得 @final CRUD + 连接失败重试能力。
自定义方法必须通过 AsyncSession 参数化查询执行，禁止 SQL 字符串拼接。

方法清单：
- create() — [继承] @final INSERT，含重试保护
- get_by_id() — 按 event_id + profile_id 查询单条
- update_event() — UPDATE 事件部分字段（双 ID WHERE）
- delete_event() — 硬删除（DELETE，双 ID WHERE）
- list_by_profile() — 按 profile_id 分页查询，event_time DESC
- count_active_by_profile() — 统计某档案下事件总数
- delete_by_profile() — 级联删除某档案下所有事件（供 PROF-01 调用）
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.base_repository import BaseRepository
from py_db.models.profiles import EventLog


class EventRepository(BaseRepository[EventLog]):
    """事件记录数据库操作封装。

    继承 BaseRepository[EventLog] 获得 @final 保护的 create / find_by_id /
    find_all / update / delete 方法及连接失败重试机制。
    自定义方法接收 AsyncSession 作为参数，支持跨方法的事务编排。
    所有查询必须包含 WHERE profile_id = :pid 条件。
    """

    model = EventLog

    def __init__(self, session_factory: Any) -> None:
        """初始化 Repository 实例。

        Args:
            session_factory: 异步会话工厂（遵循项目 Repository 接口约定）。
        """
        super().__init__(session_factory)

    async def get_by_id(
        self,
        session: AsyncSession,
        event_id: UUID,
        profile_id: UUID,
    ) -> EventLog | None:
        """按 event_id 和 profile_id 查询单条记录。

        必须同时提供 profile_id 以确保数据隔离。

        Args:
            session: 活动数据库会话。
            event_id: 目标事件 UUID。
            profile_id: 所属档案 UUID。

        Returns:
            EventLog | None: 匹配的事件，不存在时返回 None。
        """
        stmt = select(EventLog).where(
            EventLog.event_id == event_id,
            EventLog.profile_id == profile_id,
        )
        result = await session.execute(stmt)
        return result.scalars().first()

    async def update_event(
        self,
        session: AsyncSession,
        event_id: UUID,
        profile_id: UUID,
        update_data: dict[str, Any],
    ) -> EventLog | None:
        """更新事件记录的部分字段。

        Args:
            session: 活动数据库会话。
            event_id: 目标事件 UUID。
            profile_id: 所属档案 UUID。
            update_data: 需要更新的字段字典。

        Returns:
            EventLog | None: 更新后的事件，不存在时返回 None。
        """
        stmt = (
            update(EventLog)
            .where(
                EventLog.event_id == event_id,
                EventLog.profile_id == profile_id,
            )
            .values(**update_data)
            .returning(EventLog)
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.scalars().first()

    async def delete_event(
        self,
        session: AsyncSession,
        event_id: UUID,
        profile_id: UUID,
    ) -> bool:
        """硬删除指定事件记录。

        Args:
            session: 活动数据库会话。
            event_id: 目标事件 UUID。
            profile_id: 所属档案 UUID。

        Returns:
            bool: 是否成功删除（True 表示有记录被删除）。
        """
        stmt = (
            delete(EventLog)
            .where(
                EventLog.event_id == event_id,
                EventLog.profile_id == profile_id,
            )
            .returning(EventLog.event_id)
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.scalars().first() is not None

    async def list_by_profile(
        self,
        session: AsyncSession,
        profile_id: UUID,
        page: int = 1,
        page_size: int = 20,
        behavior_type: str | None = None,
    ) -> tuple[list[EventLog], int]:
        """按 profile_id 分页查询事件列表。

        按 event_time DESC 排序，支持按行为类型筛选。

        Args:
            session: 活动数据库会话。
            profile_id: 所属档案 UUID。
            page: 页码（从 1 开始）。
            page_size: 每页条数（默认 20，上限 100）。
            behavior_type: 可选行为类型筛选。

        Returns:
            tuple[list[EventLog], int]: (事件列表, 总记录数)。
        """
        # 构建基础 WHERE 条件
        conditions = [EventLog.profile_id == profile_id]
        if behavior_type is not None:
            conditions.append(EventLog.behavior_type == behavior_type)

        # 查询总记录数
        count_stmt = select(func.count()).select_from(EventLog).where(*conditions)
        total_result = await session.execute(count_stmt)
        total: int = total_result.scalar() or 0

        # 分页查询
        offset = (page - 1) * page_size
        query_stmt = (
            select(EventLog).where(*conditions).order_by(EventLog.event_time.desc()).offset(offset).limit(page_size)
        )
        result = await session.execute(query_stmt)
        events = list(result.scalars().all())

        return events, total

    async def list_recent_by_profile(
        self,
        session: AsyncSession,
        profile_id: UUID,
        limit: int = 5,
        behavior_type: str | None = None,
        days: int = 30,
    ) -> list[EventLog]:
        """查询指定档案最近 N 天的事件记录。

        按 event_time DESC 排序，优先返回 is_professional=true 的事件。
        若同行为类型不足 2 条，补充其他类型至 limit。

        Args:
            session: 活动数据库会话。
            profile_id: 所属档案 UUID。
            limit: 返回上限（默认 5）。
            behavior_type: 可选行为类型筛选。
            days: 时间范围（天，默认 30）。

        Returns:
            list[EventLog]: 事件列表。
        """
        from datetime import timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        conditions = [
            EventLog.profile_id == profile_id,
            EventLog.event_time >= cutoff,
        ]
        if behavior_type is not None:
            conditions.append(EventLog.behavior_type == behavior_type)

        stmt = (
            select(EventLog)
            .where(*conditions)
            .order_by(EventLog.is_professional.desc(), EventLog.event_time.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        events = list(result.scalars().all())

        # 若同类型不足，补充其他类型
        if behavior_type and len(events) < limit:
            remaining = limit - len(events)
            supplement_stmt = (
                select(EventLog)
                .where(
                    EventLog.profile_id == profile_id,
                    EventLog.event_time >= cutoff,
                    EventLog.behavior_type != behavior_type,
                )
                .order_by(EventLog.is_professional.desc(), EventLog.event_time.desc())
                .limit(remaining)
            )
            supp = await session.execute(supplement_stmt)
            events.extend(list(supp.scalars().all()))

        return events

    async def count_active_by_profile(
        self,
        session: AsyncSession,
        profile_id: UUID,
    ) -> int:
        """统计某档案下所有事件记录总数。

        Args:
            session: 活动数据库会话。
            profile_id: 所属档案 UUID。

        Returns:
            int: 事件记录总数。
        """
        stmt = select(func.count()).select_from(EventLog).where(EventLog.profile_id == profile_id)
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def delete_by_profile(
        self,
        session: AsyncSession,
        profile_id: UUID,
    ) -> int:
        """级联删除指定档案下所有事件记录。

        供 PROF-01 的级联删除路径调用，不执行权限校验。
        调用方（PROF-01）已在调用前完成权限校验，
        且在共享事务上下文中调用。

        Args:
            session: 活动数据库会话（由 PROF-01 传入）。
            profile_id: 目标档案 UUID。

        Returns:
            int: 被删除的事件记录数。
        """
        # 先计数用于日志
        count_stmt = select(func.count()).select_from(EventLog).where(EventLog.profile_id == profile_id)
        count_result = await session.execute(count_stmt)
        deleted_count: int = count_result.scalar() or 0

        # 执行删除
        stmt = delete(EventLog).where(EventLog.profile_id == profile_id)
        await session.execute(stmt)
        await session.flush()

        return deleted_count


__all__ = [
    "EventRepository",
]
