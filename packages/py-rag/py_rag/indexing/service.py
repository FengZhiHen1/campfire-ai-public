"""CASE-04 索引服务入口模块（索引管线步骤 1-3）。

对外暴露两个公共函数：
    - enqueue_index_task(case_id, db_session): 将审核通过案例投递到异步队列
    - manual_retry_index(case_id, db_session): 对手动重试案例重新投递

同步投递路径（步骤 1-3）：
    1. 输入校验与状态查询
    2. 状态分支判断（幂等跳转或允许入队）
    3. 生成任务载荷并 LPUSH 到 Redis List
"""

from __future__ import annotations

import json
import secrets
import uuid as uuid_lib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from py_cache import get_redis_client
from py_logger import logger

from py_rag.exceptions import RedisConnectionError
from py_rag.models import IndexTaskEnvelope

# ============================================================================
# 常量
# ============================================================================

INDEX_QUEUE_KEY: str = "index:queue:case_chunks"
REDIS_LPUSH_RETRY_COUNT: int = 1
REDIS_LPUSH_RETRY_INTERVAL: float = 0.5


# ============================================================================
# 公开接口
# ============================================================================


async def enqueue_index_task(
    case_id: uuid_lib.UUID,
    db_session: AsyncSession,
) -> dict[str, str]:
    """将审核通过的案例卡片投递到索引入库异步队列。

    本函数是 CASE-04 对外暴露的唯一入口，由 CASE-03 在审核通过后调用。
    同步返回，耗时 < 50ms。

    Args:
        case_id: 审核通过的案例唯一标识（UUID v4）。
        db_session: SQLAlchemy 异步会话。

    Returns:
        {"status": "enqueued" | "already_queued" | "already_indexed"}

    Raises:
        ValueError: case_id 格式无效、案例不存在、或案例未审核通过。
        RedisConnectionError: Redis List 连接失败（重试 1 次后仍失败）。
    """
    if not isinstance(case_id, uuid_lib.UUID):
        raise ValueError("无效的 case_id 格式")

    case_id_str = str(case_id)

    # 步骤 1：输入校验与状态查询
    query_sql = text(
        """SELECT id, status, index_status FROM cases WHERE id = :case_id"""
    )
    result = await db_session.execute(query_sql, {"case_id": case_id_str})
    row = result.fetchone()

    if row is None:
        raise ValueError(f"案例 {case_id_str} 不存在")

    row_dict: dict[str, Any] = dict(row._mapping)
    case_status: str | None = row_dict.get("status")
    index_status: str | None = row_dict.get("index_status")

    # 步骤 2：状态分支判断
    if case_status != "approved":
        raise ValueError(
            f"案例 {case_id_str} 未审核通过，当前状态: {case_status}"
        )

    if index_status == "indexed":
        logger.info(
            "py-rag",
            "案例已索引完成，幂等跳过",
            op_type="enqueue_skipped",
            extra={"case_id": case_id_str, "index_status": index_status, "reason": "already_indexed"},
        )
        return {"status": "already_indexed"}

    if index_status in ("pending", "processing"):
        logger.info(
            "py-rag",
            "案例已在索引队列或处理中，幂等跳过",
            op_type="enqueue_skipped",
            extra={"case_id": case_id_str, "index_status": index_status, "reason": "already_queued"},
        )
        return {"status": "already_queued"}

    # 步骤 3：生成任务载荷并投递到 Redis List
    trace_id = secrets.token_hex(16)
    enqueued_at = datetime.now(timezone.utc).isoformat()

    envelope = IndexTaskEnvelope(
        case_id=case_id_str,
        trace_id=trace_id,
        enqueued_at=enqueued_at,
    )

    json_str = json.dumps(envelope.model_dump(), ensure_ascii=False)

    redis_client = await get_redis_client()

    last_error: Exception | None = None
    for attempt in range(REDIS_LPUSH_RETRY_COUNT + 1):
        try:
            await redis_client.lpush(INDEX_QUEUE_KEY, json_str)
            break
        except Exception as exc:
            last_error = exc
            if attempt < REDIS_LPUSH_RETRY_COUNT:
                import asyncio

                await asyncio.sleep(REDIS_LPUSH_RETRY_INTERVAL)
            else:
                logger.critical(
                    "py-rag",
                    "索引队列不可用，案例索引入库暂时中断",
                    op_type="redis_unavailable",
                    extra={
                        "operation": "lpush",
                        "case_id": case_id_str,
                        "retry_count": REDIS_LPUSH_RETRY_COUNT,
                        "error": str(exc),
                    },
                )
                raise RedisConnectionError(
                    "索引队列不可用，案例索引入库暂时中断"
                ) from exc

    # UPDATE cases SET index_status = 'pending'（CAS 原子更新）
    update_sql = text("""
        UPDATE cases
        SET index_status = 'pending'
        WHERE id = :case_id
          AND (index_status IS NULL
               OR index_status = 'indexing_failed'
               OR index_status NOT IN ('pending', 'processing', 'indexed'))
    """)
    update_result = await db_session.execute(update_sql, {"case_id": case_id_str})
    await db_session.commit()

    if update_result.rowcount == 0:
        logger.warning(
            "py-rag",
            "CAS 冲突：任务已入队但状态更新失败",
            op_type="enqueue_cas_conflict",
            extra={"case_id": case_id_str},
        )
        return {"status": "already_queued"}

    logger.info(
        "py-rag",
        "案例索引任务入队成功",
        op_type="enqueue",
        extra={"case_id": case_id_str, "trace_id": trace_id, "index_status": "pending"},
    )

    return {"status": "enqueued"}


async def manual_retry_index(
    case_id: uuid_lib.UUID,
    db_session: AsyncSession,
) -> dict[str, str]:
    """对索引入库失败的案例执行手动重新索引。

    仅当案例 index_status = 'indexing_failed' 时允许调用。

    Args:
        case_id: 索引异常的案例唯一标识（UUID v4）。
        db_session: SQLAlchemy 异步会话。

    Returns:
        {"status": "enqueued"}

    Raises:
        ValueError: 案例不存在或 index_status 非 indexing_failed。
    """
    if not isinstance(case_id, uuid_lib.UUID):
        raise ValueError("无效的 case_id 格式")

    case_id_str = str(case_id)

    query_sql = text("SELECT index_status FROM cases WHERE id = :case_id")
    result = await db_session.execute(query_sql, {"case_id": case_id_str})
    row = result.fetchone()

    if row is None:
        raise ValueError(f"案例 {case_id_str} 不存在")

    row_dict = dict(row._mapping)
    index_status: str | None = row_dict.get("index_status")

    if index_status != "indexing_failed":
        raise ValueError(
            f"案例当前索引状态非异常，不允许手动重试 (当前: {index_status})"
        )

    logger.info(
        "py-rag",
        "手动重试索引",
        op_type="manual_retry",
        extra={"case_id": case_id_str, "index_status": index_status},
    )

    return await enqueue_index_task(case_id, db_session)
