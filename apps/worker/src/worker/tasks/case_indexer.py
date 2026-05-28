"""Worker 任务：案例向量化索引入库。

消费 Redis 队列中的案例 ID，执行：
1. 读取案例全文
2. 拼接四段式文本
3. 调用 DashScope 嵌入编码
4. 写入 case_chunks 表（pgvector）
5. 更新 cases.index_status

失败策略：重试 3 次（指数退避），最终失败标记 indexing_failed。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from py_config import get_settings
from py_logger import logger
from py_rag.embedding import encode_text
from py_rag.models import ChunkMetadata

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_MAX_RETRIES: int = 3
_RETRY_BACKOFF: list[float] = [1.0, 2.0, 4.0]

_CASE_QUERY_SQL = text("""
    SELECT
        case_id,
        title,
        behavior_type,
        age_range_min,
        age_range_max,
        severity,
        scene,
        immediate_action,
        comforting_phrase,
        observation_metrics,
        medical_criteria,
        evidence_level
    FROM cases
    WHERE case_id = :case_id
""")


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


async def index_case(case_id: str) -> None:
    """对单个案例执行向量化索引入库。

    Args:
        case_id: 案例标识（CASE-YYYY-NNNN 格式）。
    """
    settings = get_settings()
    database_url = str(settings.DATABASE_URL)
    engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        await _do_index_case(case_id, session)

    await engine.dispose()


async def _do_index_case(case_id: str, session: AsyncSession) -> None:
    """在已有数据库会话中执行索引逻辑。"""

    # ---- 1. 读取案例 ----
    result = await session.execute(_CASE_QUERY_SQL, {"case_id": case_id})
    row = result.mappings().first()
    if row is None:
        logger.error(
            "worker",
            f"案例不存在: {case_id}",
            extra={"case_id": case_id, "task": "index_case"},
        )
        await _mark_failed(session, case_id, "案例不存在")
        return

    case_data = dict(row)

    # ---- 2. 拼接 chunk_text ----
    chunk_text = (
        f"场景：{case_data['scene']}\n"
        f"行为：{case_data['immediate_action']} {case_data['comforting_phrase']}\n"
        f"干预：{case_data['observation_metrics']}\n"
        f"结果：{case_data['medical_criteria']}"
    )

    # ---- 3. 构造 metadata ----
    metadata = ChunkMetadata(
        case_id=case_id,
        case_title=case_data["title"],
        behavior_type=case_data["behavior_type"],
        age_range=f"{case_data['age_range_min']}-{case_data['age_range_max']}",
        severity=case_data["severity"],
        evidence_level=case_data["evidence_level"],
        source="case_library",
        status="approved",
        vectorized=True,
    )

    # ---- 4. 编码 + 写入（带重试）----
    last_error: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            embedding = await encode_text(chunk_text, text_type="document")
            await _write_chunk(session, case_id, chunk_text, embedding, metadata)
            await _mark_indexed(session, case_id)
            logger.info(
                "worker",
                f"案例索引入库成功: {case_id}",
                extra={"case_id": case_id, "task": "index_case", "attempt": attempt},
            )
            return
        except Exception as exc:
            last_error = exc
            logger.warning(
                "worker",
                f"案例索引失败（尝试 {attempt + 1}/{_MAX_RETRIES + 1}）: {case_id}",
                extra={
                    "case_id": case_id,
                    "task": "index_case",
                    "attempt": attempt,
                    "error": str(exc),
                },
            )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BACKOFF[attempt])

    # 重试耗尽
    logger.error(
        "worker",
        f"案例索引最终失败: {case_id}",
        extra={
            "case_id": case_id,
            "task": "index_case",
            "error": str(last_error),
        },
    )
    await _mark_failed(session, case_id, str(last_error))


async def _write_chunk(
    session: AsyncSession,
    case_id: str,
    chunk_text: str,
    embedding: list[float],
    metadata: ChunkMetadata,
) -> None:
    """写入 case_chunks 表。"""

    metadata_dict = metadata.model_dump()
    chunk_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    insert_sql = text("""
        INSERT INTO case_chunks (id, case_id, chunk_text, embedding, metadata, created_at)
        VALUES (
            :id,
            :case_id,
            :chunk_text,
            :embedding::vector(1024),
            :metadata::jsonb,
            :created_at
        )
    """)

    await session.execute(
        insert_sql,
        {
            "id": chunk_id,
            "case_id": case_id,
            "chunk_text": chunk_text,
            "embedding": json.dumps(embedding),
            "metadata": json.dumps(metadata_dict, ensure_ascii=False),
            "created_at": now_iso,
        },
    )
    await session.commit()


async def _mark_indexed(session: AsyncSession, case_id: str) -> None:
    """更新 cases 表状态为 indexed。"""

    stmt = text("""
        UPDATE cases
        SET index_status = :index_status, indexed_at = :indexed_at
        WHERE case_id = :case_id
    """)
    await session.execute(
        stmt,
        {
            "index_status": "indexed",
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "case_id": case_id,
        },
    )
    await session.commit()


async def _mark_failed(session: AsyncSession, case_id: str, reason: str) -> None:
    """更新 cases 表状态为 indexing_failed。"""

    stmt = text("""
        UPDATE cases
        SET index_status = :index_status
        WHERE case_id = :case_id
    """)
    await session.execute(
        stmt,
        {
            "index_status": "indexing_failed",
            "case_id": case_id,
        },
    )
    await session.commit()
    logger.error(
        "worker",
        f"案例索引标记为失败: {case_id}",
        extra={"case_id": case_id, "reason": reason, "task": "index_case"},
    )


__all__ = ["index_case"]
