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

from py_logger import logger
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.exceptions import RepositoryCommunicationError



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
        top_k: int,
    ) -> list[dict[str, Any]]:
        """执行 pgvector 纯语义检索，无标签过滤。

        仅按余弦距离排序返回最相似的案例切片。

        Args:
            session: 活动数据库异步会话。
            query_vector: 1024 维查询向量（由 encode_query() 编码）。
            top_k: 期望返回的结果数量（上限 50）。

        Returns:
            查询结果字典列表，每项包含：
            - id (str): 切片 UUID
            - card_id (str): L2 卡片 UUID
            - chunk_text (str): 切片文本
            - chunk_type (str | None): 切片类型
            - similarity (float): 余弦相似度（0.0-1.0）
            - metadata (dict): JSONB 元数据

        Raises:
            RepositoryCommunicationError: 数据库连接失败且重试耗尽。
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
        bind_params: dict[str, Any] = {
            "query_vector": str(query_vector),
            "top_k": top_k,
        }

        sql = text("""
            SELECT
                cc.id::text AS id,
                cc.card_id,
                cc.chunk_text,
                cc.chunk_type,
                1 - (cc.embedding <=> CAST(:query_vector AS vector(1024))) AS similarity,
                cc.metadata
            FROM case_chunks cc
            ORDER BY cc.embedding <=> CAST(:query_vector AS vector(1024))
            LIMIT :top_k
        """)

        try:
            result = await session.execute(sql, bind_params)
            rows = result.fetchall()
        except Exception as exc:
            logger.error(
                "search_similar_chunks_failed",
                extra={
                    "degradation_level": degradation_level.value,
                    "top_k": top_k,
                    "error": str(exc),
                },
            )
            raise RepositoryCommunicationError(
                f"数据库检索操作失败: {exc}"
            ) from exc

        return [
            {
                "id": str(row[0]),
                "card_id": str(row[1]),
                "chunk_text": str(row[2]),
                "chunk_type": str(row[3]) if row[3] is not None else None,
                "similarity": float(row[4]) if row[4] is not None else 0.0,
                "metadata": dict(row[5]) if row[5] is not None else {},
            }
            for row in rows
        ]


__all__ = ["ConsultRepository"]
