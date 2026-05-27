"""CASE-04 索引服务入口模块。

对外暴露两个公共函数：
    - enqueue_index_task(case_id): 将审核通过案例投递到异步队列
    - manual_retry_index(case_id): 对手动重试案例重新投递

同步投递路径（步骤 1-3）：
    1. 输入校验与状态查询：SELECT id, status, index_status FROM cases
    2. 状态分支判断：幂等跳转或允许入队
    3. 生成任务载荷并 LPUSH 到 Redis List

异步处理路径（步骤 4-9）实现在 worker.py 中。
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

from py_indexing.exceptions import RedisConnectionError
from py_indexing.models import IndexTaskEnvelope

# ============================================================================
# 常量
# ============================================================================

INDEX_QUEUE_KEY: str = "index:queue:case_chunks"
"""Redis List 键名。Worker BRPOP 和 enqueue LPUSH 使用完全一致的键名。"""

REDIS_LPUSH_RETRY_COUNT: int = 1
"""LPUSH 操作最大重试次数。"""

REDIS_LPUSH_RETRY_INTERVAL: float = 0.5
"""LPUSH 重试间隔（秒）。"""


# ============================================================================
# 公开接口
# ============================================================================


async def enqueue_index_task(
    case_id: uuid_lib.UUID,
    db_session: AsyncSession,
) -> dict[str, str]:
    """将审核通过的案例卡片投递到索引入库异步队列。

    本函数是 CASE-04 对外暴露的唯一入口，由 CASE-03 在审核通过后调用。
    执行内容仅为状态校验 + Redis LPUSH，不执行实际向量化处理。
    同步返回，耗时 < 50ms。

    Args:
        case_id: 审核通过的案例唯一标识（UUID v4）。
        db_session: SQLAlchemy 异步会话。

    Returns:
        dict: {"status": "enqueued" | "already_queued" | "already_indexed"}

    Raises:
        ValueError: case_id 格式无效、案例不存在、或案例未审核通过。
        RedisConnectionError: Redis List 连接失败（重试 1 次后仍失败）。
    """
    if not isinstance(case_id, uuid_lib.UUID):
        raise ValueError("无效的 case_id 格式")

    case_id_str: str = str(case_id)

    # ------------------------------------------------------------------
    # 步骤 1：输入校验与状态查询
    # ------------------------------------------------------------------
    query_sql = text("""
        SELECT id, status, index_status
        FROM cases
        WHERE id = :case_id
    """)

    result = await db_session.execute(query_sql, {"case_id": case_id_str})
    row = result.fetchone()

    # 行不存在
    if row is None:
        raise ValueError(f"案例 {case_id_str} 不存在")

    row_dict: dict[str, Any] = dict(row._mapping)
    case_status: str | None = row_dict.get("status")
    index_status: str | None = row_dict.get("index_status")

    # ------------------------------------------------------------------
    # 步骤 2：状态分支判断
    # ------------------------------------------------------------------
    # 案例未审核通过
    if case_status != "approved":
        raise ValueError(
            f"案例 {case_id_str} 未审核通过，当前状态: {case_status}",
        )

    # 幂等跳过：已索引完成
    if index_status == "indexed":
        logger.info(
            "py-indexing",
            "案例已索引完成，幂等跳过",
            op_type="enqueue_skipped",
            extra={
                "case_id": case_id_str,
                "index_status": index_status,
                "reason": "already_indexed",
            },
        )
        return {"status": "already_indexed"}

    # 幂等跳过：已在队列或处理中
    if index_status in ("pending", "processing"):
        logger.info(
            "py-indexing",
            "案例已在索引队列或处理中，幂等跳过",
            op_type="enqueue_skipped",
            extra={
                "case_id": case_id_str,
                "index_status": index_status,
                "reason": "already_queued",
            },
        )
        return {"status": "already_queued"}

    # ------------------------------------------------------------------
    # 步骤 3：生成任务载荷并投递到 Redis List
    # ------------------------------------------------------------------
    trace_id: str = secrets.token_hex(16)
    enqueued_at: str = datetime.now(timezone.utc).isoformat()

    envelope: IndexTaskEnvelope = IndexTaskEnvelope(
        case_id=case_id_str,
        trace_id=trace_id,
        enqueued_at=enqueued_at,
    )

    json_str: str = json.dumps(envelope.model_dump(), ensure_ascii=False)

    # LPUSH 到 Redis List（含重试）
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
                    "py-indexing",
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
                    "索引队列不可用，案例索引入库暂时中断",
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

    rows_affected: int = update_result.rowcount

    if rows_affected == 0:
        # CAS 冲突：其他并发操作已更新状态，但任务已入队
        logger.warning(
            "py-indexing",
            "CAS 冲突：任务已入队但状态更新失败（并发操作）",
            op_type="enqueue_cas_conflict",
            extra={"case_id": case_id_str},
        )
        # 任务已入队，但状态更新冲突——仍返回已入队
        return {"status": "already_queued"}

    logger.info(
        "py-indexing",
        "案例索引任务入队成功",
        op_type="enqueue",
        extra={
            "case_id": case_id_str,
            "trace_id": trace_id,
            "index_status": "pending",
        },
    )

    return {"status": "enqueued"}


async def manual_retry_index(
    case_id: uuid_lib.UUID,
    db_session: AsyncSession,
) -> dict[str, str]:
    """对索引入库失败的案例执行手动重新索引。

    仅当案例 index_status = 'indexing_failed' 时允许调用。
    内部调用 enqueue_index_task() 重新投递到队列。

    Args:
        case_id: 索引异常的案例唯一标识（UUID v4）。
        db_session: SQLAlchemy 异步会话。

    Returns:
        dict: {"status": "enqueued"}

    Raises:
        ValueError: 案例不存在或 index_status 非 indexing_failed。
    """
    if not isinstance(case_id, uuid_lib.UUID):
        raise ValueError("无效的 case_id 格式")

    case_id_str: str = str(case_id)

    # 检查当前索引状态
    query_sql = text("""
        SELECT index_status FROM cases WHERE id = :case_id
    """)
    result = await db_session.execute(query_sql, {"case_id": case_id_str})
    row = result.fetchone()

    if row is None:
        raise ValueError(f"案例 {case_id_str} 不存在")

    row_dict = dict(row._mapping)
    index_status: str | None = row_dict.get("index_status")

    if index_status != "indexing_failed":
        raise ValueError(
            f"案例当前索引状态非异常，不允许手动重试 (当前: {index_status})",
        )

    logger.info(
        "py-indexing",
        "手动重试索引",
        op_type="manual_retry",
        extra={"case_id": case_id_str, "index_status": index_status},
    )

    # 委托 enqueue_index_task() 重新投递
    return await enqueue_index_task(case_id, db_session)
