"""CASE-04 Worker 协程模块（索引管线步骤 4-9）。

负责单例 Worker 协程的启动/停止管理。Worker 作为 asyncio 协程运行在
FastAPI 进程内，通过 lifespan 事件启停。

核心类 IndexPipeline 实现 BaseIndexPipeline 契约，通过 @final process_task()
获得统一的管线编排：状态更新 → 读取案例数据 → 文本组装 → 嵌入编码 → 索引写入 → 状态标记。

Worker 循环：
  4. Worker 从 Redis List BRPOP 消费任务
  5. 委托 IndexPipeline.process_task() 处理完整索引管线
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from py_cache import get_redis_client, maybe_await
from py_db.sqlalchemy_helpers import rowcount
from py_logger import logger
from py_rag.embedding_contract import BaseEmbeddingEncoder
from py_rag.indexing.chunk_builder import build_chunk_text
from py_rag.indexing.index_writer import write_index_to_pgvector
from py_rag.indexing_contract import (
    INDEX_QUEUE_KEY,
    BaseIndexPipeline,
)
from py_rag.protocols import ChunkBuilder, IndexWriter
from py_rag.types import CaseIdStr

# ============================================================================
# 常量
# ============================================================================

BRPOP_TIMEOUT: int = 5
REDIS_RECONNECT_INTERVAL_INITIAL: float = 1.0
REDIS_RECONNECT_INTERVAL_MAX: float = 10.0


# ============================================================================
# 模块级状态
# ============================================================================

worker_task: asyncio.Task[None] | None = None
_shutdown_event: asyncio.Event | None = None
_pipeline: IndexPipeline | None = None


def _get_pipeline() -> IndexPipeline:
    """获取全局索引管线实例。"""
    global _pipeline
    if _pipeline is None:
        from py_rag.embedding import _get_encoder

        _pipeline = IndexPipeline(
            embedding_encoder=_get_encoder(),
            chunk_builder=build_chunk_text,
            index_writer=write_index_to_pgvector,
        )
    return _pipeline


# ============================================================================
# IndexPipeline — 契约实现类
# ============================================================================


class IndexPipeline(BaseIndexPipeline):
    """索引管线 Worker 实现。

    实现 BaseIndexPipeline 契约的 5 个 @abstractmethod 钩子。
    _do_build_chunk / _do_write_index 由基类委托注入的 Protocol 实例，
    无需覆写。
    """

    def __init__(
        self,
        embedding_encoder: BaseEmbeddingEncoder,
        chunk_builder: ChunkBuilder,
        index_writer: IndexWriter,
    ) -> None:
        super().__init__(embedding_encoder, chunk_builder, index_writer)

    # === _do_ 钩子实现 ===

    async def _do_update_status_to_processing(
        self,
        case_id: CaseIdStr,
        db_session: AsyncSession,
    ) -> bool:
        """CAS 更新 index_status 为 'processing'。

        UPDATE case_cards SET index_status='processing'
        WHERE card_id=:id AND index_status='pending'
        """
        case_id_str = str(case_id)
        update_sql = text("""
            UPDATE case_cards SET index_status = 'processing'
            WHERE card_id = :card_id AND index_status = 'pending'
        """)
        result = await db_session.execute(update_sql, {"card_id": case_id_str})
        if rowcount(result) == 0:
            logger.info(
                "py-rag",
                "任务 CAS 冲突：案例状态非 pending，跳过",
                op_type="worker_skip",
                extra={"case_id": case_id_str},
            )
            await db_session.commit()
            return False
        await db_session.commit()
        return True

    async def _do_read_case_data(
        self,
        case_id: CaseIdStr,
        db_session: AsyncSession,
    ) -> dict[str, Any] | None:
        """读取 case_cards JOIN case_narratives 完整数据。

        Returns:
            案例数据字典，不存在时返回 None。
        """
        case_id_str = str(case_id)
        query_case_sql = text("""
            SELECT cd.card_id, cd.title, cd.immediate_action, cd.comforting_phrase,
                   cd.observation_metrics, cd.medical_criteria, cd.behavior_type,
                   cd.severity, cd.age_range_min, cd.age_range_max, cd.evidence_level,
                   cd.scene, cn.narrative
            FROM case_cards cd
            JOIN case_narratives cn ON cn.narrative_id = cd.narrative_id
            WHERE cd.card_id = :card_id
        """)
        case_result = await db_session.execute(query_case_sql, {"card_id": case_id_str})
        case_row = case_result.fetchone()

        if case_row is None:
            return None

        case_data: dict[str, Any] = dict(case_row._mapping)
        case_data["case_id"] = case_data.get("card_id", case_id_str)
        return case_data

    async def _do_generate_embedding(
        self,
        chunk_text: str,
    ) -> list[float]:
        """调用嵌入服务生成文档向量。

        委托 BaseEmbeddingEncoder.encode()。
        """
        encoder: BaseEmbeddingEncoder = self._encoder  # type: ignore[assignment]
        embedding_vector = await encoder.encode(chunk_text, text_type="document")
        return list(embedding_vector)

    async def _do_mark_indexed(
        self,
        case_id: CaseIdStr,
        db_session: AsyncSession,
    ) -> None:
        """CAS 更新 index_status 为 'indexed'。

        UPDATE case_cards SET index_status='indexed', indexed_at=:now
        WHERE card_id=:id AND index_status='processing'
        """
        case_id_str = str(case_id)
        now = datetime.now(timezone.utc)

        update_sql = text("""
            UPDATE case_cards
            SET index_status = 'indexed', indexed_at = :indexed_at
            WHERE card_id = :card_id AND index_status = 'processing'
        """)
        result = await db_session.execute(
            update_sql, {"card_id": case_id_str, "indexed_at": now}
        )
        await db_session.commit()

        if rowcount(result) == 0:
            logger.warning(
                "py-rag",
                "状态更新为 indexed 时 CAS 冲突",
                op_type="indexed_cas_conflict",
                extra={"case_id": case_id_str},
            )
        else:
            logger.info(
                "py-rag",
                "索引入库完成",
                op_type="indexed",
                extra={
                    "case_id": case_id_str,
                    "index_status": "indexed",
                    "phase": "complete",
                },
            )

    async def _do_mark_failed(
        self,
        case_id: CaseIdStr,
        error: str,
        phase: str,
        db_session: AsyncSession,
    ) -> None:
        """更新 index_status 为 'indexing_failed' 并记录错误日志。"""
        case_id_str = str(case_id)

        update_sql = text("""
            UPDATE case_cards
            SET index_status = 'indexing_failed'
            WHERE card_id = :card_id
        """)
        await db_session.execute(update_sql, {"card_id": case_id_str})
        await db_session.commit()

        logger.error(
            "py-rag",
            f"索引失败 [{phase}]: {error}",
            op_type="indexing_failed",
            extra={
                "case_id": case_id_str,
                "error": error,
                "phase": phase,
            },
        )


# ============================================================================
# 生命周期接口
# ============================================================================


def start_worker(app: object) -> None:
    """由 FastAPI lifespan 事件注册，启动单例 Worker 协程。"""
    global worker_task, _shutdown_event

    if worker_task is not None and not worker_task.done():
        logger.warning("py-rag", "Worker 协程已在运行，跳过启动")
        return

    _shutdown_event = asyncio.Event()
    worker_task = asyncio.create_task(_worker_loop(app))

    logger.info(
        "py-rag",
        "Worker 协程已启动",
        op_type="worker_start",
        extra={"task_name": "indexing_worker"},
    )


def stop_worker(app: object) -> None:
    """由 FastAPI lifespan 事件注册，优雅停止 Worker 协程。"""
    global worker_task, _shutdown_event

    if worker_task is None or worker_task.done():
        return

    if _shutdown_event is not None:
        _shutdown_event.set()

    worker_task.cancel()

    logger.info(
        "py-rag",
        "Worker 协程已停止",
        op_type="worker_stop",
        extra={"task_name": "indexing_worker"},
    )


# ============================================================================
# 内部函数 — Worker 主循环
# ============================================================================


async def _worker_loop(app: object) -> None:
    """Worker 主协程循环。

    最外层 try/except 兜底确保 Worker 永不死循环退出。
    """
    db_session_factory: async_sessionmaker[AsyncSession] | None = getattr(
        app.state, "db_session_factory", None  # type: ignore[attr-defined]
    )
    if db_session_factory is None:
        logger.critical(
            "py-rag",
            "Worker 启动失败：app.state.db_session_factory 未设置",
            op_type="worker_start_failed",
        )
        return

    pipeline = _get_pipeline()
    redis_reconnect_interval = REDIS_RECONNECT_INTERVAL_INITIAL

    while True:
        if _shutdown_event is not None and _shutdown_event.is_set():
            logger.info("py-rag", "Worker 收到关闭信号，退出循环")
            break

        try:
            redis_client = await get_redis_client()

            # 步骤 4：BRPOP 阻塞消费
            # aioredis stub 将 BRPOP 返回值标为 list[Any]，实际为 [key, value] 或 None
            lr: list[str] | None = await maybe_await(
                redis_client.brpop(INDEX_QUEUE_KEY, timeout=BRPOP_TIMEOUT)
            )

            if lr is None:
                redis_reconnect_interval = REDIS_RECONNECT_INTERVAL_INITIAL
                continue

            redis_reconnect_interval = REDIS_RECONNECT_INTERVAL_INITIAL

            _, json_str = lr
            task_data: dict[str, Any] = json.loads(json_str)
            case_id: str = task_data["case_id"]
            trace_id: str = task_data.get("trace_id", "")

            logger.info(
                "py-rag",
                "Worker 取出索引任务",
                op_type="worker_dequeue",
                extra={
                    "case_id": case_id,
                    "trace_id": trace_id,
                    "phase": "dequeue",
                },
            )

            async with db_session_factory() as session:
                await _process_task(pipeline, case_id, trace_id, session)

        except asyncio.CancelledError:
            logger.info("py-rag", "Worker 协程被取消，退出循环")
            break

        except Exception as exc:
            logger.critical(
                "py-rag",
                f"Worker 主循环捕获未预期异常: {exc}",
                op_type="worker_unexpected_error",
                extra={"error": str(exc)},
            )
            await asyncio.sleep(redis_reconnect_interval)
            redis_reconnect_interval = min(
                redis_reconnect_interval * 2, REDIS_RECONNECT_INTERVAL_MAX
            )


async def _process_task(
    pipeline: IndexPipeline,
    case_id: str,
    trace_id: str,
    session: AsyncSession,
) -> None:
    """处理单个索引任务。

    委托 IndexPipeline.process_task() 走完整契约管线。
    """
    await pipeline.process_task(
        case_id=CaseIdStr(case_id),
        trace_id=trace_id,
        db_session=session,
    )


__all__ = [
    "IndexPipeline",
    "start_worker",
    "stop_worker",
]
