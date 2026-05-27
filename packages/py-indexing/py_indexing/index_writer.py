"""CASE-04 索引写入模块。

负责将已生成的 chunk_text + embedding + metadata 写入 pgvector 的 case_chunks 表。

对外接口：
    - write_index_to_pgvector(case_id, chunk_text, embedding, metadata_dict, db_session) -> None
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from py_logger import logger

from py_indexing.models import ChunkMetadata

# ============================================================================
# 常量
# ============================================================================

RETRY_INTERVAL: float = 1.0
"""pgvector INSERT 重试间隔（秒）。"""

MAX_RETRY_COUNT: int = 2
"""最大重试次数（共 3 次尝试：1 主 + 2 重试）。"""


# ============================================================================
# 公开接口
# ============================================================================


async def write_index_to_pgvector(
    case_id: str,
    chunk_text: str,
    embedding: list[float],
    metadata: ChunkMetadata,
    db_session: AsyncSession,
) -> None:
    """将文本切片和向量写入 pgvector 的 case_chunks 表。

    本函数内嵌最多 2 次重试（线性间隔 1s）。

    Args:
        case_id: 案例 UUID 字符串。
        chunk_text: 拼接后的四要素文本。
        embedding: 1024 维嵌入向量列表。
        metadata: ChunkMetadata 对象（序列化为 JSONB）。
        db_session: SQLAlchemy 异步会话。

    Raises:
        sqlalchemy.exc.IntegrityError: 唯一约束或外键冲突。
        sqlalchemy.exc.OperationalError: 数据库连接或磁盘问题。
    """
    metadata_dict: dict[str, str] = metadata.model_dump()
    chunk_id: str = str(uuid.uuid4())
    now_iso: str = datetime.now(timezone.utc).isoformat()

    # 构造原生 INSERT 语句（使用 pgvector 的 ::vector 类型转换）
    insert_sql = text("""
        INSERT INTO case_chunks (id, case_id, chunk_text, embedding, metadata, created_at)
        VALUES (:id, :case_id, :chunk_text, :embedding::vector(1024), :metadata::jsonb, :created_at)
    """)

    params: dict[str, object] = {
        "id": chunk_id,
        "case_id": case_id,
        "chunk_text": chunk_text,
        "embedding": json.dumps(embedding),
        "metadata": json.dumps(metadata_dict, ensure_ascii=False),
        "created_at": now_iso,
    }

    last_error: Exception | None = None

    for attempt in range(MAX_RETRY_COUNT + 1):
        try:
            await db_session.execute(insert_sql, params)
            await db_session.commit()
            logger.info(
                "py-indexing",
                "pgvector 索引写入成功",
                op_type="index_write",
                extra={
                    "case_id": case_id,
                    "chunk_id": chunk_id,
                    "phase": "write_index",
                },
            )
            return

        except Exception as exc:
            await db_session.rollback()
            last_error = exc

            if attempt < MAX_RETRY_COUNT:
                logger.warning(
                    "py-indexing",
                    f"pgvector 写入失败，{RETRY_INTERVAL}s 后重试",
                    op_type="index_write_retry",
                    extra={
                        "case_id": case_id,
                        "attempt": attempt + 1,
                        "max_attempts": MAX_RETRY_COUNT + 1,
                        "error": str(exc),
                        "phase": "write_index",
                    },
                )
                await asyncio.sleep(RETRY_INTERVAL)
            else:
                logger.error(
                    "py-indexing",
                    "pgvector 索引写入重试耗尽",
                    op_type="index_write_exhausted",
                    extra={
                        "case_id": case_id,
                        "retry_count": MAX_RETRY_COUNT,
                        "error": str(last_error),
                        "phase": "write_index",
                    },
                )
                raise
