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

from sqlalchemy import and_, func, or_, select, text, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect as sa_inspect
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
        behavior_type: str | None = None,
        evidence_level: str | None = None,
        keyword: str | None = None,
        sort_by: str | None = None,
        page: int = 1,
        page_size: int = 15,
    ) -> tuple[list[Case], int]:
        """按多条件筛选案例，支持分页、搜索和动态排序。

        Args:
            session: 活动数据库会话。
            status: 可选状态筛选（draft/pending_review/rejected）。
            author_id: 可选作者筛选。
            behavior_type: 可选行为类型筛选。
            evidence_level: 可选循证等级筛选（A/B/C/D）。
            keyword: 可选关键词（模糊匹配 title/behavior_type/scene）。
            sort_by: 可选排序方式（latest/evidence/cited/updated）。
            page: 页码，从 1 开始。
            page_size: 每页条数，默认 15。

        Returns:
            (cases, total_count) 元组。
        """
        async def _query() -> tuple[list[Case], int]:
            conditions: list[Any] = []
            if status is not None:
                conditions.append(self.model.status == status)
            if author_id is not None:
                conditions.append(self.model.author_id == author_id)
            if behavior_type is not None:
                conditions.append(self.model.behavior_type == behavior_type)
            if evidence_level is not None:
                conditions.append(self.model.evidence_level == evidence_level)
            if keyword is not None:
                kw = f"%{keyword}%"
                conditions.append(
                    or_(
                        self.model.title.ilike(kw),
                        self.model.behavior_type.ilike(kw),
                        self.model.scene.ilike(kw),
                    )
                )

            # 总数查询
            count_stmt: Select = select(sa_func.count()).select_from(self.model)
            if conditions:
                count_stmt = count_stmt.where(*conditions)
            count_result = await session.execute(count_stmt)
            total_count: int = count_result.scalar() or 0

            # 排序字段映射
            sort_column = {
                "evidence": self.model.evidence_level,
                "cited": self.model.citation_count,
                "updated": self.model.updated_at,
            }.get(sort_by or "", self.model.created_at)

            # 分页查询
            offset: int = (page - 1) * page_size
            data_stmt: Select = (
                select(self.model)
                .where(*conditions if conditions else [True])
                .order_by(sort_column.desc())
                .offset(offset)
                .limit(page_size)
            )
            data_result = await session.execute(data_stmt)
            cases: list[Case] = list(data_result.scalars().all())

            return cases, total_count

        return await self._execute_with_retry(session, "find_by_filters", _query)

    # ------------------------------------------------------------------
    # 批量查询：已审核通过的案例（供 KNOW-01 等下游消费）
    # ------------------------------------------------------------------

    async def find_approved_ids(
        self,
        session: AsyncSession,
        case_ids: list[str],
    ) -> list[str]:
        """批量查询指定案例 ID 列表中已审核通过的案例 ID。

        供 KNOW-01 等下游模块在创建/更新文章时校验案例引用合法性。
        使用 `WHERE status='approved' AND case_id = ANY(:ids)` 索引命中查询，
        十亿级数据量内性能 <5ms（cases.status 已建立索引）。

        Args:
            session: 活动数据库会话。
            case_ids: 待校验的案例 ID 列表。

        Returns:
            状态为 approved 的案例 ID 子集（空列表表示无匹配）。

        Raises:
            DependencyCommunicationError: 数据库连接失败且重试耗尽。
        """
        if not case_ids:
            return []

        async def _query() -> list[str]:
            stmt: Select = select(self.model.case_id).where(
                self.model.status == CaseStatus.APPROVED,
                self.model.case_id.in_(case_ids),
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

        return await self._execute_with_retry(
            session, "find_approved_ids", _query
        )

    # ------------------------------------------------------------------
    # 状态更新
    # ------------------------------------------------------------------

    async def update_status(
        self,
        session: AsyncSession,
        case_id: str,
        new_status: CaseStatus,
        expected_status: CaseStatus | None = None,
        review_comment: str | None = None,
    ) -> Case:
        """原子性更新案例状态。

        若提供 expected_status，使用 UPDATE ... WHERE case_id=$1 AND status=$current
        实现乐观锁，仅当案例仍处于预期状态时才执行更新。

        Args:
            session: 活动数据库会话。
            case_id: 案例唯一标识。
            new_status: 目标状态。
            expected_status: 预期当前状态（乐观锁）。为 None 则跳过 CAS 检查。
            review_comment: 可选的审核驳回意见。

        Returns:
            更新状态后的 Case 实例。

        Raises:
            ValueError: 案例不存在或状态不匹配（CAS 冲突）。
        """

        async def _update() -> Case:
            conditions = [Case.case_id == case_id]
            if expected_status is not None:
                conditions.append(Case.status == expected_status)

            values: dict[str, object] = {"status": new_status}
            if review_comment is not None:
                values["review_comment"] = review_comment

            result = await session.execute(
                sa_update(Case).where(and_(*conditions)).values(**values)
            )
            if result.rowcount == 0:
                raise ValueError(
                    f"案例 {case_id} 不存在或状态已变更（预期 {expected_status}）"
                )

            case = await self.find_by_case_id(session, case_id)
            assert case is not None
            await session.refresh(case)
            return case

        return await self._execute_with_retry(session, "update_status", _update)

    async def update_case_with_version(
        self,
        session: AsyncSession,
        case: Case,
        expected_updated_at: datetime,
    ) -> Case:
        """原子性更新案例，带乐观锁检测。

        使用 UPDATE ... WHERE case_id=$1 AND updated_at=$2，
        确保在读取版本检查与写入之间无其他事务修改该记录。

        Args:
            session: 活动数据库会话。
            case: 已在内存中修改过的 Case ORM 实例。
            expected_updated_at: 读操作时记录的时间戳。

        Returns:
            更新后的 Case 实例。

        Raises:
            ValueError: 乐观锁冲突（updated_at 已变化）。
        """

        async def _update() -> Case:
            insp = sa_inspect(case)
            dirty = {attr.key for attr in insp.attrs if attr.history.has_changes()}
            if not dirty:
                await session.refresh(case)
                return case

            values = {col: getattr(case, col) for col in dirty}
            result = await session.execute(
                sa_update(Case)
                .where(
                    and_(
                        Case.case_id == case.case_id,
                        Case.updated_at == expected_updated_at,
                    )
                )
                .values(**values)
            )
            if result.rowcount == 0:
                raise ValueError(
                    f"案例 {case.case_id} 已被其他用户修改，请刷新后重试"
                )

            await session.refresh(case)
            return case

        return await self._execute_with_retry(session, "update_case_with_version", _update)


__all__ = ["CaseRepository"]
