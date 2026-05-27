"""CASE-01 案例录入管理 — CaseRepository。

封装 cases 表的参数化查询方法，确保 Service 层
不直接操作数据库会话。

特殊查询：
- generate_case_id(): 使用数据库序列生成 CASE-YYYY-NNNN 格式 ID
- find_by_id_with_version(): 乐观锁冲突检测（case_id + updated_at 双条件查询）
- find_by_filters(): 筛选 + 分页 + 总数查询
- update_status(): 状态更新单入口
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select, func as sa_func

from py_db.models.case_model import Case
from py_db.repositories.base_repository import BaseRepository
from py_schemas.enums.case_enums import CaseStatus

_logger = logging.getLogger(__name__)


class CaseRepository(BaseRepository[Case]):
    """案例 Repository。

    继承 BaseRepository[Case] 获得通用 CRUD 方法骨架，
    另提供案例专属查询方法。

    Usage:
        repo = CaseRepository(session_factory=async_session_factory)
        case = await repo.find_by_case_id(session, "CASE-2026-0001")
    """

    model = Case

    # ------------------------------------------------------------------
    # 案例 ID 生成
    # ------------------------------------------------------------------

    async def generate_case_id(self, session: AsyncSession) -> str:
        """生成案例唯一标识（CASE-YYYY-NNNN 格式）。

        从数据库序列 case_id_seq 获取下一个序列值，
        格式化为 CASE-{当前年份}-{序列值(4位补零)}。

        Returns:
            格式化的案例 ID，如 "CASE-2026-0001"。

        Raises:
            DependencyCommunicationError: 序列读取失败且重试耗尽。
        """
        async def _generate() -> str:
            result = await session.execute(text("SELECT nextval('case_id_seq')"))
            seq_value: int = result.scalar()
            year: int = datetime.now().year
            return f"CASE-{year}-{seq_value:04d}"

        return await self._execute_with_retry(
            session, "generate_case_id", _generate
        )

    # ------------------------------------------------------------------
    # 自定义查询方法
    # ------------------------------------------------------------------

    async def find_by_case_id(
        self,
        session: AsyncSession,
        case_id: str,
    ) -> Case | None:
        """按 case_id 查询单条案例。

        Args:
            session: 活动数据库会话。
            case_id: 案例唯一标识。

        Returns:
            匹配的 Case 实例，不存在时返回 None。
        """
        async def _query() -> Case | None:
            stmt: Select = select(self.model).where(self.model.case_id == case_id)
            result = await session.execute(stmt)
            return result.scalars().first()

        return await self._execute_with_retry(session, "find_by_case_id", _query)

    async def find_by_id_with_version(
        self,
        session: AsyncSession,
        case_id: str,
        expected_updated_at: datetime,
    ) -> Case | None:
        """按 case_id + updated_at 乐观锁条件查询。

        用于乐观锁冲突检测：
        - 返回 Case 实例 → 版本匹配，允许更新
        - 返回 None → 版本不匹配，需返回 409 Conflict

        Args:
            session: 活动数据库会话。
            case_id: 案例唯一标识。
            expected_updated_at: 期望的时间戳（客户端上次读取的值）。

        Returns:
            Case 实例（版本匹配）或 None（版本不匹配）。
        """
        async def _query() -> Case | None:
            stmt: Select = select(self.model).where(
                self.model.case_id == case_id,
                self.model.updated_at == expected_updated_at,
            )
            result = await session.execute(stmt)
            return result.scalars().first()

        return await self._execute_with_retry(
            session, "find_by_id_with_version", _query
        )

    async def find_by_filters(
        self,
        session: AsyncSession,
        status: CaseStatus | None = None,
        author_id: str | None = None,
        page: int = 1,
        page_size: int = 15,
    ) -> tuple[list[Case], int]:
        """按状态和作者筛选案例，支持分页。

        查询结果按 created_at 倒序排列。
        同时返回匹配总数用于分页计算。

        Args:
            session: 活动数据库会话。
            status: 可选状态筛选（draft/pending_review/rejected）。
            author_id: 可选作者筛选。
            page: 页码，从 1 开始。
            page_size: 每页条数，默认 15。

        Returns:
            (cases, total_count) 元组：
            - cases: 当前页的案例列表。
            - total_count: 匹配条件的总记录数。
        """
        async def _query() -> tuple[list[Case], int]:
            # 构建基础查询条件
            conditions: list[Any] = []
            if status is not None:
                conditions.append(self.model.status == status)
            if author_id is not None:
                conditions.append(self.model.author_id == author_id)

            # 总数查询
            count_stmt: Select = select(sa_func.count()).select_from(self.model)
            if conditions:
                count_stmt = count_stmt.where(*conditions)
            count_result = await session.execute(count_stmt)
            total_count: int = count_result.scalar() or 0

            # 分页查询
            offset: int = (page - 1) * page_size
            data_stmt: Select = (
                select(self.model)
                .where(*conditions if conditions else [True])
                .order_by(self.model.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
            data_result = await session.execute(data_stmt)
            cases: list[Case] = list(data_result.scalars().all())

            return cases, total_count

        return await self._execute_with_retry(session, "find_by_filters", _query)

    # ------------------------------------------------------------------
    # 状态更新
    # ------------------------------------------------------------------

    async def update_status(
        self,
        session: AsyncSession,
        case_id: str,
        new_status: CaseStatus,
        review_comment: str | None = None,
    ) -> Case:
        """更新案例状态。

        状态转换的统一入口，使用 WHERE case_id=$1 AND status=$current 实现原子性。

        Args:
            session: 活动数据库会话。
            case_id: 案例唯一标识。
            new_status: 目标状态。
            review_comment: 可选的审核驳回意见。

        Returns:
            更新状态后的 Case 实例。

        Raises:
            ValueError: 案例不存在或状态不匹配。
        """
        async def _update() -> Case:
            case = await self.find_by_case_id(session, case_id)
            if case is None:
                raise ValueError(f"案例 {case_id} 不存在")

            case.status = new_status
            if review_comment is not None:
                case.review_comment = review_comment

            session.add(case)
            await session.flush()
            await session.refresh(case)
            return case

        return await self._execute_with_retry(session, "update_status", _update)


__all__ = ["CaseRepository"]
