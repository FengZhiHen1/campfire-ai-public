"""CASE-04 Worker 协程模块。

负责单例 Worker 协程的启动/停止管理。Worker 作为 asyncio 协程运行在
FastAPI 进程内，通过 lifespan 事件启停。

Worker 循环（异步处理路径步骤 4-9）：
    4. Worker 从 Redis List BRPOP 消费任务
    5. 更新状态为 processing + 读取案例数据
    6. 文本组装与 PII 最终防线校验（委托 chunk_builder）
    7. 调用嵌入服务生成向量（委托 embedding_client）
    8. 写入 pgvector 索引（委托 index_writer）
    9. 更新索引状态为 indexed

对外接口：
    - start_worker(app)  — 由 lifespan 事件注册
    - stop_worker(app)   — 由 lifespan 事件注册
    - worker_task: asyncio.Task | None — Worker 协程 Task 引用
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from py_cache import get_redis_client
from py_logger import logger

from py_indexing.chunk_builder import build_chunk_text
from py_indexing.embedding_client import (
    generate_embedding,
)
from py_indexing.exceptions import (
    ChunkBuildError,
    EmbeddingServiceError,
    PIIRejectionError,
)
from py_indexing.index_writer import write_index_to_pgvector
from py_indexing.models import ChunkMetadata

# ============================================================================
# 常量
# ============================================================================

INDEX_QUEUE_KEY: str = "index:queue:case_chunks"
"""Redis List 键名。必须与 service.py 中的 INDEX_QUEUE_KEY 一致。"""

BRPOP_TIMEOUT: int = 5
"""BRPOP 阻塞等待超时（秒）。超时后重新进入循环。"""

REDIS_RECONNECT_INTERVAL_INITIAL: float = 1.0
"""Redis 断连后首次重连等待时间（秒）。"""

REDIS_RECONNECT_INTERVAL_MAX: float = 10.0
"""Redis 断连后最大重连等待时间（秒）。"""


# ============================================================================
# 模块级状态
# ============================================================================

worker_task: asyncio.Task[None] | None = None
"""Worker 协程的 asyncio.Task 引用。用于生命周期管理和优雅关闭。"""

_shutdown_event: asyncio.Event | None = None
"""优雅关闭信号事件。调用 stop_worker() 时设置此事件。"""


# ============================================================================
# 生命周期接口
# ============================================================================


def start_worker(app: object) -> None:
    """由 FastAPI lifespan 事件注册，启动单例 Worker 协程。

    Args:
        app: FastAPI 应用实例。用于获取数据库会话工厂等依赖。
    """
    global worker_task, _shutdown_event

    if worker_task is not None and not worker_task.done():
        logger.warning("py-indexing", "Worker 协程已在运行，跳过启动")
        return

    _shutdown_event = asyncio.Event()
    worker_task = asyncio.create_task(_worker_loop(app))

    logger.info(
        "py-indexing",
        "Worker 协程已启动",
        op_type="worker_start",
        extra={"task_name": "indexing_worker"},
    )


def stop_worker(app: object) -> None:
    """由 FastAPI lifespan 事件注册，优雅停止 Worker 协程。

    Args:
        app: FastAPI 应用实例。
    """
    global worker_task, _shutdown_event

    if worker_task is None or worker_task.done():
        return

    if _shutdown_event is not None:
        _shutdown_event.set()

    worker_task.cancel()

    logger.info(
        "py-indexing",
        "Worker 协程已停止",
        op_type="worker_stop",
        extra={"task_name": "indexing_worker"},
    )


# ============================================================================
# 内部函数 — Worker 主循环
# ============================================================================


async def _worker_loop(app: object) -> None:
    """Worker 主协程循环。

    从 Redis List BRPOP 阻塞消费任务，依次执行文本组装、嵌入生成、索引写入。

    最外层 try/except 兜底确保 Worker 永不死循环退出：
    任何未捕获异常导致协程终止时，记录 CRITICAL 日志并等待 1s 后继续。

    Args:
        app: FastAPI 应用实例。通过 app.state 获取 db_session_factory。
    """
    # 获取数据库会话工厂
    db_session_factory: async_sessionmaker[AsyncSession] | None = getattr(
        app.state, "db_session_factory", None
    )
    if db_session_factory is None:
        logger.critical(
            "py-indexing",
            "Worker 启动失败：app.state.db_session_factory 未设置",
            op_type="worker_start_failed",
        )
        return

    redis_reconnect_interval: float = REDIS_RECONNECT_INTERVAL_INITIAL

    while True:
        # 检查优雅关闭信号
        if _shutdown_event is not None and _shutdown_event.is_set():
            logger.info("py-indexing", "Worker 收到关闭信号，退出循环")
            break

        try:
            # 获取 Redis 客户端
            redis_client = await get_redis_client()

            # 步骤 4：BRPOP 阻塞消费
            result: tuple[str, str] | None = await redis_client.brpop(
                INDEX_QUEUE_KEY,
                timeout=BRPOP_TIMEOUT,
            )

            if result is None:
                # BRPOP 超时（5s 无任务），继续循环
                redis_reconnect_interval = REDIS_RECONNECT_INTERVAL_INITIAL
                continue

            # 恢复重连间隔
            redis_reconnect_interval = REDIS_RECONNECT_INTERVAL_INITIAL

            # 反序列化任务
            _, json_str = result
            task_data: dict[str, Any] = json.loads(json_str)
            case_id: str = task_data["case_id"]
            trace_id: str = task_data.get("trace_id", "")

            logger.info(
                "py-indexing",
                "Worker 取出索引任务",
                op_type="worker_dequeue",
                extra={
                    "case_id": case_id,
                    "trace_id": trace_id,
                    "phase": "dequeue",
                },
            )

            # 创建数据库会话
            async with db_session_factory() as session:
                await _process_task(case_id, trace_id, session, app)

        except asyncio.CancelledError:
            logger.info("py-indexing", "Worker 协程被取消，退出循环")
            break

        except Exception as exc:
            logger.critical(
                "py-indexing",
                f"Worker 主循环捕获未预期异常: {exc}",
                op_type="worker_unexpected_error",
                extra={"error": str(exc)},
            )
            await asyncio.sleep(redis_reconnect_interval)
            # 指数退避重连（上限 10s）
            redis_reconnect_interval = min(
                redis_reconnect_interval * 2,
                REDIS_RECONNECT_INTERVAL_MAX,
            )


async def _process_task(
    case_id: str,
    trace_id: str,
    session: AsyncSession,
    app: object,
) -> None:
    """处理单个索引任务（步骤 5-9）。

    Args:
        case_id: 案例 UUID 字符串。
        trace_id: 链路追踪标识。
        session: SQLAlchemy 异步会话。
        app: FastAPI 应用实例。
    """
    # ------------------------------------------------------------------
    # 步骤 5：更新状态为 processing + 读取案例数据
    # ------------------------------------------------------------------
    update_processing_sql = text("""
        UPDATE cases
        SET index_status = 'processing'
        WHERE id = :case_id
          AND index_status = 'pending'
    """)
    result = await session.execute(update_processing_sql, {"case_id": case_id})
    if result.rowcount == 0:
        # CAS 失败：状态已非 pending，跳过本次任务（幂等保护）
        logger.info(
            "py-indexing",
            "任务 CAS 冲突：案例状态非 pending，跳过",
            op_type="worker_skip",
            extra={"case_id": case_id, "trace_id": trace_id},
        )
        await session.commit()
        return

    # 读取案例完整数据
    query_case_sql = text("""
        SELECT id, title, scene_description, behavior_manifestation,
               intervention_action, result_feedback, behavior_type,
               emotion_level, applicable_population, evidence_level,
               disclaimer
        FROM cases
        WHERE id = :case_id
    """)
    case_result = await session.execute(query_case_sql, {"case_id": case_id})
    case_row = case_result.fetchone()

    if case_row is None:
        logger.error(
            "py-indexing",
            "案例数据读取失败：行不存在",
            op_type="worker_error",
            extra={"case_id": case_id, "trace_id": trace_id, "phase": "read_case"},
        )
        await _mark_indexing_failed(session, case_id, trace_id, "案例不存在", "read_case")
        return

    case_data: dict[str, Any] = dict(case_row._mapping)
    await session.commit()

    # ------------------------------------------------------------------
    # 步骤 6：文本组装与 PII 最终防线校验
    # ------------------------------------------------------------------
    try:
        chunk_text: str
        metadata: ChunkMetadata
        chunk_text, metadata = build_chunk_text(case_data)
    except (ChunkBuildError, PIIRejectionError) as exc:
        error_msg: str = str(exc)
        phase: str = "build_chunk_text"

        # 标记索引失败
        await _mark_indexing_failed(session, case_id, trace_id, error_msg, phase)

        if isinstance(exc, ChunkBuildError):
            logger.error(
                "py-indexing",
                error_msg,
                op_type="chunk_build_failed",
                extra={
                    "case_id": case_id,
                    "trace_id": trace_id,
                    "missing_fields": getattr(exc, "missing_fields", []),
                    "reason": "incomplete_fields",
                    "phase": phase,
                },
            )
        else:
            logger.warning(
                "py-indexing",
                error_msg,
                op_type="pii_rejection",
                extra={
                    "case_id": case_id,
                    "trace_id": trace_id,
                    "patterns_matched": getattr(exc, "patterns_matched", []),
                    "phase": phase,
                },
            )
        return

    # ------------------------------------------------------------------
    # 步骤 7：调用嵌入服务生成向量
    # ------------------------------------------------------------------
    try:
        embedding: list[float] = await generate_embedding(chunk_text)
    except EmbeddingServiceError:
        error_msg = "嵌入服务调用失败"
        await _mark_indexing_failed(session, case_id, trace_id, error_msg, "generate_embedding")
        return

    # ------------------------------------------------------------------
    # 步骤 8：写入 pgvector 索引
    # ------------------------------------------------------------------
    try:
        await write_index_to_pgvector(
            case_id=case_id,
            chunk_text=chunk_text,
            embedding=embedding,
            metadata=metadata,
            db_session=session,
        )
    except Exception as exc:
        error_msg = f"pgvector 索引写入失败: {exc}"
        await _mark_indexing_failed(session, case_id, trace_id, error_msg, "write_index")
        return

    # ------------------------------------------------------------------
    # 步骤 9：更新索引状态为 indexed
    # ------------------------------------------------------------------
    await _mark_indexed(session, case_id, trace_id)


# ============================================================================
# 内部函数 — 状态更新辅助
# ============================================================================


async def _mark_indexing_failed(
    session: AsyncSession,
    case_id: str,
    trace_id: str,
    error: str,
    phase: str,
) -> None:
    """将案例索引状态更新为 indexing_failed。

    索引流程失败仅影响 cases.index_status，绝不修改 cases.status（审核结果）。

    Args:
        session: SQLAlchemy 异步会话。
        case_id: 案例 UUID 字符串。
        trace_id: 链路追踪标识。
        error: 错误描述。
        phase: 失败阶段。
    """
    update_sql = text("""
        UPDATE cases
        SET index_status = 'indexing_failed'
        WHERE id = :case_id
    """)
    await session.execute(update_sql, {"case_id": case_id})
    await session.commit()

    logger.error(
        "py-indexing",
        f"索引失败 [{phase}]: {error}",
        op_type="indexing_failed",
        extra={
            "case_id": case_id,
            "trace_id": trace_id,
            "error": error,
            "phase": phase,
        },
    )


async def _mark_indexed(
    session: AsyncSession,
    case_id: str,
    trace_id: str,
) -> None:
    """更新案例索引状态为 indexed。

    同时记录 indexed_at 时间戳。

    Args:
        session: SQLAlchemy 异步会话。
        case_id: 案例 UUID 字符串。
        trace_id: 链路追踪标识。
    """
    now_iso: str = datetime.now(timezone.utc).isoformat()

    update_sql = text("""
        UPDATE cases
        SET index_status = 'indexed', indexed_at = :indexed_at
        WHERE id = :case_id
          AND index_status = 'processing'
    """)
    result = await session.execute(
        update_sql,
        {
            "case_id": case_id,
            "indexed_at": now_iso,
        },
    )
    await session.commit()

    if result.rowcount == 0:
        # CAS 失败：状态已非 processing（可能已被手动标记）
        logger.warning(
            "py-indexing",
            "状态更新为 indexed 时 CAS 冲突（行已被修改）",
            op_type="indexed_cas_conflict",
            extra={"case_id": case_id, "trace_id": trace_id},
        )
    else:
        logger.info(
            "py-indexing",
            "索引入库完成",
            op_type="indexed",
            extra={
                "case_id": case_id,
                "trace_id": trace_id,
                "index_status": "indexed",
                "phase": "complete",
            },
        )
