"""CSLT-06 咨询历史管理 — ConsultHistoryRepository。

封装 consultations 表的全部数据库操作。所有查询方法强制注入 user_id
确保用户数据隔离不遗漏。不使用 BaseRepository 继承——直接使用 AsyncSession。

功能要点：
- archive: INSERT ... ON CONFLICT (request_id) DO NOTHING 幂等写入
- find_by_request_id: 按幂等键查询已有记录
- list_by_user: 按用户分页查询（仅 5 字段，按时间降序）
- find_by_id_and_user: 按 id + user_id 联合查询（详情访问控制）
- count_by_id: 辅助查询区分 404 原因（记录不存在 vs user_id 不匹配）
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from py_logger import logger
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.models.consultation import ConsultationHistory



class ConsultHistoryRepository:
    """咨询历史数据访问仓储。

    封装 consultations 表的全部查询和写入操作。
    所有查询方法强制注入 user_id 确保数据隔离。
    不移除已存在的导入——仅提供本模块所需的最小接口面。
    """

    # ------------------------------------------------------------------
    # 归档写入
    # ------------------------------------------------------------------

    async def archive(
        self,
        session: AsyncSession,
        data: dict[str, Any],
    ) -> ConsultationHistory | None:
        """幂等归档写入。

        使用 INSERT ... ON CONFLICT (request_id) DO NOTHING RETURNING * 实现幂等。
        若 RETURNING 返回空行（已存在），返回 None，调用方需执行 SELECT 获取已有记录。
        consultation_time 使用 NOW() 覆盖，忽略 data 中的值。

        Args:
            session: 活动数据库异步会话。
            data: 待归档的字段字典（不含 consultation_time，由 NOW() 生成）。

        Returns:
            插入成功的 ConsultationHistory ORM 实例，或 None（重复归档）。
        """
        if session is None:
            raise ValueError("session must not be None")
        if not data:
            raise ValueError("data must not be empty")

        stmt = text("""
            INSERT INTO consultations (
                id, request_id, user_id, crisis_level, behavior_description,
                consultation_time, generated_plan, source_list, disclaimer,
                generation_time_ms, is_partial, referenced_slice_ids, finish_reason,
                ttft_ms, has_feedback, token_input, token_output, device_info,
                created_at, updated_at
            ) VALUES (
                :id, :request_id, :user_id, :crisis_level, :behavior_description,
                NOW(), :generated_plan, :source_list, :disclaimer,
                :generation_time_ms, :is_partial, :referenced_slice_ids, :finish_reason,
                :ttft_ms, :has_feedback, :token_input, :token_output, :device_info,
                NOW(), NOW()
            )
            ON CONFLICT (request_id) DO NOTHING
            RETURNING *
        """)

        # 将 Python 对象转为 SQL 兼容绑定参数
        # 原始 SQL 模式下 asyncpg 不会自动序列化 JSONB 列，需手动 json.dumps
        bind_params = {
            "id": data["id"],
            "request_id": data["request_id"],
            "user_id": data["user_id"],
            "crisis_level": data["crisis_level"],
            "behavior_description": data["behavior_description"],
            "generated_plan": data["generated_plan"],
            "source_list": json.dumps(data.get("source_list", [])),
            "disclaimer": data["disclaimer"],
            "generation_time_ms": data["generation_time_ms"],
            "is_partial": data["is_partial"],
            "referenced_slice_ids": json.dumps(data.get("referenced_slice_ids", [])),
            "finish_reason": data["finish_reason"],
            "ttft_ms": data["ttft_ms"],
            "has_feedback": data.get("has_feedback", False),
            "token_input": data.get("token_input"),
            "token_output": data.get("token_output"),
            "device_info": json.dumps(data["device_info"]) if data.get("device_info") else None,
        }

        result = await session.execute(stmt, bind_params)
        row = result.fetchone()
        if row is None:
            return None

        # 将 Row 映射为 ORM 实例
        return ConsultationHistory(**row._mapping)

    # ------------------------------------------------------------------
    # 查询方法
    # ------------------------------------------------------------------

    async def find_by_request_id(
        self,
        session: AsyncSession,
        request_id: uuid.UUID,
    ) -> ConsultationHistory | None:
        """按幂等键查询已有记录。

        用于重复归档时获取首次归档的记录。

        Args:
            session: 活动数据库异步会话。
            request_id: 幂等键（由 CSLT-08 生成）。

        Returns:
            匹配的 ConsultationHistory 实例，不存在时返回 None。
        """
        stmt = select(ConsultationHistory).where(
            ConsultationHistory.request_id == request_id
        )
        result = await session.execute(stmt)
        return result.scalars().first()

    async def list_by_user(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        page: int,
        page_size: int,
    ) -> tuple[list, int]:
        """按用户分页查询历史列表摘要。

        仅选取 5 个字段（id, consultation_time, behavior_description,
        crisis_level, has_feedback），不包含 generated_plan 等大字段。
        按 consultation_time DESC 排序。

        Args:
            session: 活动数据库异步会话。
            user_id: 当前用户 UUID。
            page: 页码（1-based）。
            page_size: 每页记录数。

        Returns:
            (items: list[dict], total: int) 元组。
        """
        offset = (page - 1) * page_size

        # 仅选取列表所需的 5 个字段
        columns = [
            ConsultationHistory.id,
            ConsultationHistory.consultation_time,
            ConsultationHistory.behavior_description,
            ConsultationHistory.crisis_level,
            ConsultationHistory.has_feedback,
        ]

        # COUNT 查询
        count_stmt = select(func.count()).where(
            ConsultationHistory.user_id == user_id
        )
        count_result = await session.execute(count_stmt)
        total: int = count_result.scalar_one()

        # 数据查询
        data_stmt = (
            select(*columns)
            .where(ConsultationHistory.user_id == user_id)
            .order_by(ConsultationHistory.consultation_time.desc())
            .limit(page_size)
            .offset(offset)
        )
        data_result = await session.execute(data_stmt)
        rows = data_result.fetchall()

        items: list[dict] = [
            {
                "id": row[0],
                "consultation_time": row[1],
                "behavior_description": row[2],
                "crisis_level": row[3],
                "has_feedback": row[4],
            }
            for row in rows
        ]

        return items, total

    async def find_by_id_and_user(
        self,
        session: AsyncSession,
        record_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ConsultationHistory | None:
        """按 id + user_id 联合查询完整记录。

        详情查询的核心方法——同时校验 id 和 user_id 确保数据隔离。

        Args:
            session: 活动数据库异步会话。
            record_id: 咨询记录 UUID。
            user_id: 当前用户 UUID。

        Returns:
            匹配的 ConsultationHistory 完整实例，不存在或无权访问时返回 None。
        """
        stmt = select(ConsultationHistory).where(
            ConsultationHistory.id == record_id,
            ConsultationHistory.user_id == user_id,
        )
        result = await session.execute(stmt)
        return result.scalars().first()

    async def count_by_id(
        self,
        session: AsyncSession,
        record_id: uuid.UUID,
    ) -> int:
        """按 id 计数记录。

        辅助查询——用于区分「ID 存在但 user_id 不匹配」和「ID 不存在」。
        仅在 find_by_id_and_user 返回 None 时调用。

        Args:
            session: 活动数据库异步会话。
            record_id: 咨询记录 UUID。

        Returns:
            该 id 在表中的记录数（0 或 1）。
        """
        stmt = select(func.count()).where(
            ConsultationHistory.id == record_id
        )
        result = await session.execute(stmt)
        return result.scalar_one()


__all__ = ["ConsultHistoryRepository"]
