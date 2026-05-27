"""CASE-03 案例审核工作流 — ReviewRepository。

封装 case_reviews 表和 review_audit_logs 表的参数化查询方法。

ReviewRepository 提供审核记录的写入和查询方法。
ReviewAuditLogRepository 仅提供 INSERT 操作（BIGSERIAL 自增主键保证不可篡改）。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select, func as sa_func

from py_db.models.review_models import CaseReview, ReviewAuditLog
from py_db.repositories.base_repository import BaseRepository

_logger = logging.getLogger(__name__)


class ReviewRepository(BaseRepository[CaseReview]):
    """审核记录 Repository。

    继承 BaseRepository[CaseReview] 获得通用 CRUD 方法骨架，
    另提供审核记录专属查询方法。

    Usage:
        repo = ReviewRepository(session_factory=async_session_factory)
        record = await repo.create_review_record(session, review)
    """

    model = CaseReview

    # ------------------------------------------------------------------
    # 审核记录写入
    # ------------------------------------------------------------------

    async def create_review_record(
        self,
        session: AsyncSession,
        review: CaseReview,
    ) -> CaseReview:
        """创建审核记录。

        写入 case_reviews 表，记录本次专家审核的完整详情。

        Args:
            session: 活动数据库会话。
            review: 待创建的 CaseReview ORM 实例。

        Returns:
            创建成功的 CaseReview 实例。

        Raises:
            DependencyCommunicationError: 数据库连接失败且重试耗尽。
        """
        return await self.create(session, review)

    # ------------------------------------------------------------------
    # 审核历史查询
    # ------------------------------------------------------------------

    async def get_review_history(
        self,
        session: AsyncSession,
        case_id: str,
        limit: int = 10,
    ) -> list[CaseReview]:
        """按 case_id 查询审核历史，按审核轮次倒序。

        Args:
            session: 活动数据库会话。
            case_id: 案例唯一标识。
            limit: 返回的最大记录数，默认 10。

        Returns:
            CaseReview 列表，按 review_round 倒序。
        """
        async def _query() -> list[CaseReview]:
            stmt: Select = (
                select(self.model)
                .where(self.model.case_id == case_id)
                .order_by(self.model.review_round.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

        return await self._execute_with_retry(
            session, "get_review_history", _query
        )

    async def get_latest_review(
        self,
        session: AsyncSession,
        case_id: str,
    ) -> CaseReview | None:
        """获取某案例的最新一条审核记录。

        Args:
            session: 活动数据库会话。
            case_id: 案例唯一标识。

        Returns:
            最新的 CaseReview 实例，不存在时返回 None。
        """
        async def _query() -> CaseReview | None:
            stmt: Select = (
                select(self.model)
                .where(self.model.case_id == case_id)
                .order_by(self.model.review_round.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            return result.scalars().first()

        return await self._execute_with_retry(
            session, "get_latest_review", _query
        )


class ReviewAuditLogRepository:
    """审核审计日志 Repository。

    仅提供 insert_audit_log 方法（INSERT ONLY）。
    BIGSERIAL 自增主键保证记录顺序不可伪造和不可篡改。
    不提供 UPDATE/DELETE 方法。
    """

    def __init__(self, session_factory: Any) -> None:
        """初始化 ReviewAuditLogRepository 实例。

        Args:
            session_factory: 异步会话工厂（callable）。
        """
        self._session_factory = session_factory

    async def insert_audit_log(
        self,
        session: AsyncSession,
        case_id: str,
        action: str,
        operator_id: str,
        operator_role: str,
        details: dict[str, Any] | None = None,
    ) -> ReviewAuditLog:
        """插入一条审核审计日志。

        仅 INSERT 操作，不提供 UPDATE/DELETE 方法以保障审计记录不可篡改。

        Args:
            session: 活动数据库会话。
            case_id: 关联的案例标识。
            action: 审计动作类型。
            operator_id: 操作人 UUID。
            operator_role: 操作人角色。
            details: 操作详情（JSON 可序列化字典）。

        Returns:
            创建的 ReviewAuditLog 实例。

        Raises:
            DependencyCommunicationError: 数据库连接失败且重试耗尽。
        """
        log_entry = ReviewAuditLog(
            case_id=case_id,
            action=action,
            operator_id=operator_id,
            operator_role=operator_role,
            details=details,
        )
        session.add(log_entry)
        await session.flush()
        await session.refresh(log_entry)
        return log_entry


__all__ = [
    "ReviewRepository",
    "ReviewAuditLogRepository",
]
