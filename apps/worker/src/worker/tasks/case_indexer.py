"""Worker 任务：案例卡片向量化索引入库。

消费 Redis 队列中的卡片 ID (UUID)，执行：
1. 读取 case_cards（L2）数据
2. 拼接四段式文本
3. 调用 DashScope 嵌入编码
4. 写入 case_chunks 表（pgvector）
5. 更新 case_cards.index_status

失败策略：重试 3 次（指数退避），最终失败标记 indexing_failed。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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

_CARD_QUERY_SQL = text("""
    SELECT
        card_id,
        narrative_id,
        title,
        scenario,
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
    FROM case_cards
    WHERE card_id = :card_id
""")


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


async def index_case(card_id: str) -> None:
    """对单个案例卡片执行向量化索引入库。

    Args:
        card_id: 卡片 UUID 字符串。
    """
    settings = get_settings()
    database_url = str(settings.DATABASE_URL)
    engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        await _do_index_card(card_id, session)

    await engine.dispose()


async def _do_index_card(card_id: str, session: AsyncSession) -> None:
    """在已有数据库会话中执行索引逻辑。"""

    # ---- 1. 读取卡片 ----
    result = await session.execute(_CARD_QUERY_SQL, {"card_id": uuid.UUID(card_id)})
    row = result.mappings().first()
    if row is None:
        logger.error(
            "worker",
            f"卡片不存在: {card_id}",
            extra={"card_id": card_id, "task": "index_case"},
        )
        return

    card_data = dict(row)

    # ---- 2. 拼接 chunk_text ----
    chunk_text = (
        f"场景：{card_data['scene']}\n"
        f"行为：{card_data['immediate_action']} {card_data['comforting_phrase']}\n"
        f"干预：{card_data['observation_metrics']}\n"
        f"结果：{card_data['medical_criteria']}"
    )

    # ---- 3. 构造 metadata ----
    metadata = ChunkMetadata(
        case_id=card_id,
        case_title=card_data["title"],
        behavior_type=card_data["behavior_type"],
        age_range=f"{card_data['age_range_min']}-{card_data['age_range_max']}",
        severity=card_data["severity"],
        evidence_level=card_data["evidence_level"],
        source="case_library",
        status="approved",
        vectorized=True,
    )

    # ---- 4. 编码 + 写入（带重试）----
    last_error: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            embedding = await encode_text(chunk_text, text_type="document")
            await _write_chunk(session, card_id, chunk_text, embedding, metadata)
            await _mark_indexed(session, card_id)
            logger.info(
                "worker",
                f"卡片索引入库成功: {card_id}",
                extra={"card_id": card_id, "task": "index_case", "attempt": attempt},
            )
            return
        except Exception as exc:
            last_error = exc
            logger.warning(
                "worker",
                f"卡片索引失败（尝试 {attempt + 1}/{_MAX_RETRIES + 1}）: {card_id}",
                extra={
                    "card_id": card_id,
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
        f"卡片索引最终失败: {card_id}",
        extra={
            "card_id": card_id,
            "task": "index_case",
            "error": str(last_error),
        },
    )
    await _mark_failed(session, card_id, str(last_error))


async def _write_chunk(
    session: AsyncSession,
    card_id: str,
    chunk_text: str,
    embedding: list[float],
    metadata: ChunkMetadata,
) -> None:
    """写入 case_chunks 表。"""

    metadata_dict = metadata.model_dump()
    chunk_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    insert_sql = text("""
        INSERT INTO case_chunks (id, card_id, chunk_text, embedding, metadata, created_at)
        VALUES (
            :id,
            :card_id,
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
            "card_id": uuid.UUID(card_id),
            "chunk_text": chunk_text,
            "embedding": json.dumps(embedding),
            "metadata": json.dumps(metadata_dict, ensure_ascii=False),
            "created_at": now_iso,
        },
    )
    await session.commit()


async def _mark_indexed(session: AsyncSession, card_id: str) -> None:
    """更新 case_cards 表状态为 indexed。"""

    stmt = text("""
        UPDATE case_cards
        SET index_status = 'indexed', indexed_at = :indexed_at
        WHERE card_id = :card_id
    """)
    await session.execute(
        stmt,
        {
            "indexed_at": datetime.now(timezone.utc),
            "card_id": uuid.UUID(card_id),
        },
    )
    await session.commit()


async def _mark_failed(session: AsyncSession, card_id: str, reason: str) -> None:
    """更新 case_cards 表状态为 indexing_failed。"""

    stmt = text("""
        UPDATE case_cards
        SET index_status = 'indexing_failed'
        WHERE card_id = :card_id
    """)
    await session.execute(
        stmt,
        {"card_id": uuid.UUID(card_id)},
    )
    await session.commit()
    logger.error(
        "worker",
        f"卡片索引标记为失败: {card_id}",
        extra={"card_id": card_id, "reason": reason, "task": "index_case"},
    )


__all__ = ["index_case"]
