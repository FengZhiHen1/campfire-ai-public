"""CSLT-02 RAG语义检索 — ConsultRepository。

提供 search_similar_chunks() 方法，通过参数化 SQL 执行 pgvector HNSW
混合检索（标签精确过滤 + 向量余弦排序）。

功能要点：
- 使用 SQLAlchemy text() + 绑定参数，避免字符串拼接 SQL
- 支持三层降级放宽（EMOTION_RELAXED / BEHAVIOR_RELAXED / ALL_TAGS_REMOVED）
- 自动排除 CASE-06 标记的失效案例（obsolete/erroneous/disputed/force_removed）
- 仅检索 status='approved' 且 vectorized='true' 的已审核切片
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.repositories.base_repository import DependencyCommunicationError
from py_schemas.consult import DegradationLevel

_logger = logging.getLogger(__name__)


class ConsultRepository:
    """应急咨询数据访问仓储。

    封装 case_chunks 表的 pgvector 混合检索操作。
    继承 BaseRepository 的通用 CRUD 能力（通过 session_factory），
    本类专注于向量检索特有的查询方法。
    """

    # ------------------------------------------------------------------
    # 公共查询方法
    # ------------------------------------------------------------------

    async def search_similar_chunks(
        self,
        session: AsyncSession,
        query_vector: list[float],
        age_range: str,
        behavior_type: str,
        emotion_level: str | None,
        top_k: int,
        degradation_level: DegradationLevel = DegradationLevel.NONE,
    ) -> list[dict[str, Any]]:
        """执行 pgvector HNSW 混合检索。

        根据指定降级层级构建动态 WHERE 条件，执行参数化 SQL 查询，
        返回按余弦距离升序排列的案例切片结果列表。

        Args:
            session: 活动数据库异步会话。
            query_vector: 1024 维查询向量（由 encode_query() 编码）。
            age_range: 患者年龄段过滤条件。
            behavior_type: 行为类型过滤条件。
            emotion_level: 情绪等级过滤条件（为 None 时不应用）。
            top_k: 期望返回的结果数量（上限 50）。
            degradation_level: 降级放宽层级，控制 WHERE 条件的严格程度。

        Returns:
            查询结果字典列表，每项包含：
            - id (str): 切片 UUID
            - case_id (str): 案例编号
            - chunk_text (str): 切片文本
            - chunk_type (str | None): 切片类型
            - similarity (float): 余弦相似度（0.0-1.0）
            - metadata (dict): JSONB 元数据

        Raises:
            DependencyCommunicationError: 数据库连接失败且重试耗尽。
        """
        # --- 入口参数校验 ---
        if session is None:
            raise ValueError("session must not be None")
        if not query_vector:
            raise ValueError("query_vector must not be empty")
        if len(query_vector) != 1024:
            raise ValueError(
                f"query_vector must be 1024 dimensions, got {len(query_vector)}"
            )
        # 注意：age_range 和 behavior_type 在降级流程中可能为空字符串
        # （degradation_level=ALL_TAGS_REMOVED 或 BEHAVIOR_RELAXED 时合法），故不做非空校验

        # 基础过滤条件（始终生效）
        base_conditions: list[str] = [
            "cc.metadata->>'status' = 'approved'",
            "cc.metadata->>'vectorized' = 'true'",
            "cc.metadata->>'status' NOT IN ('obsolete', 'erroneous', 'disputed', 'force_removed')",
        ]

        # 根据降级层级动态添加标签过滤条件
        bind_params: dict[str, Any] = {
            "query_vector": str(query_vector),  # pgvector 接受字符串表示的向量
            "top_k": top_k,
        }

        if degradation_level == DegradationLevel.ALL_TAGS_REMOVED:
            # 层级 3：移除全部标签条件，仅保留基础过滤
            pass
        elif degradation_level == DegradationLevel.BEHAVIOR_RELAXED:
            # 层级 2：仅保留 age_range
            base_conditions.append("cc.metadata->>'age_range' = :age_range")
            bind_params["age_range"] = age_range
        elif degradation_level == DegradationLevel.EMOTION_RELAXED:
            # 层级 1：保留 age_range + behavior_type
            base_conditions.append("cc.metadata->>'age_range' = :age_range")
            base_conditions.append("cc.metadata->>'behavior_type' = :behavior_type")
            bind_params["age_range"] = age_range
            bind_params["behavior_type"] = behavior_type
        else:
            # 层级 0（NONE）：全部标签条件
            base_conditions.append("cc.metadata->>'age_range' = :age_range")
            base_conditions.append("cc.metadata->>'behavior_type' = :behavior_type")
            bind_params["age_range"] = age_range
            bind_params["behavior_type"] = behavior_type
            if emotion_level is not None:
                base_conditions.append(
                    "cc.metadata->>'emotion_level' = :emotion_level"
                )
                bind_params["emotion_level"] = emotion_level

        where_clause = " AND ".join(base_conditions)

        sql = text(f"""
            SELECT
                cc.id::text AS id,
                cc.case_id,
                cc.chunk_text,
                cc.chunk_type,
                1 - (cc.embedding <=> CAST(:query_vector AS vector(1024))) AS similarity,
                cc.metadata
            FROM case_chunks cc
            WHERE {where_clause}
            ORDER BY cc.embedding <=> CAST(:query_vector AS vector(1024))
            LIMIT :top_k
        """)

        try:
            result = await session.execute(sql, bind_params)
            rows = result.fetchall()
        except Exception as exc:
            _logger.error(
                "search_similar_chunks_failed",
                extra={
                    "degradation_level": degradation_level.value,
                    "top_k": top_k,
                    "error": str(exc),
                },
            )
            raise DependencyCommunicationError(
                f"数据库检索操作失败: {exc}"
            ) from exc

        return [
            {
                "id": str(row[0]),
                "case_id": str(row[1]),
                "chunk_text": str(row[2]),
                "chunk_type": str(row[3]) if row[3] is not None else None,
                "similarity": float(row[4]) if row[4] is not None else 0.0,
                "metadata": dict(row[5]) if row[5] is not None else {},
            }
            for row in rows
        ]


__all__ = ["ConsultRepository"]
