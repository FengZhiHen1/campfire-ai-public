"""Campfire-AI Worker — 独立后台任务消费进程。

复用 py-rag 索引管线契约（BaseIndexPipeline）+ 实现（IndexPipeline），
作为独立容器部署的进程壳。

职责：
  - 数据库引擎与会话工厂生命周期
  - Redis 异步队列消费（BRPOP）
  - 委托 IndexPipeline.process_task() 处理完整索引管线
  - SIGTERM/SIGINT 优雅关闭

MVP Phase 0：仅消费 index:queue:case_chunks 队列。
"""

from __future__ import annotations

import asyncio
import json
import signal
import threading
import traceback

from py_cache import close_redis_client, get_redis_client, maybe_await
from py_config import get_settings
from py_logger import logger
from py_rag.indexing import IndexPipeline
from py_rag.indexing_contract import INDEX_QUEUE_KEY
from py_rag.types import CaseIdStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

BRPOP_TIMEOUT: int = 5
REDIS_RECONNECT_INITIAL: float = 1.0
REDIS_RECONNECT_MAX: float = 30.0

# ---------------------------------------------------------------------------
# 模块级状态
# ---------------------------------------------------------------------------

_shutdown_event: threading.Event = threading.Event()
_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_pipeline: IndexPipeline | None = None


# ---------------------------------------------------------------------------
# 信号处理
# ---------------------------------------------------------------------------


def _handle_signal(signum: int, _frame: object) -> None:
    """处理 SIGTERM / SIGINT，触发优雅关闭。"""
    sig_name = signal.Signals(signum).name
    logger.info(
        "worker",
        f"收到信号 {sig_name}，开始优雅关闭...",
        op_type="worker_shutdown",
    )
    _shutdown_event.set()


# ---------------------------------------------------------------------------
# 数据库引擎
# ---------------------------------------------------------------------------


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """获取或创建全局异步会话工厂。"""
    global _session_factory, _engine
    if _session_factory is None:
        settings = get_settings()
        database_url = str(settings.DATABASE_URL)
        _engine = create_async_engine(database_url, echo=False)
        _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _session_factory


# ---------------------------------------------------------------------------
# 索引管线
# ---------------------------------------------------------------------------


def _get_pipeline() -> IndexPipeline:
    """获取全局索引管线单例。"""
    global _pipeline
    if _pipeline is None:
        from py_rag.embedding import _get_encoder
        from py_rag.indexing.chunk_builder import build_chunk_text
        from py_rag.indexing.index_writer import write_index_to_pgvector

        _pipeline = IndexPipeline(
            embedding_encoder=_get_encoder(),
            chunk_builder=build_chunk_text,
            index_writer=write_index_to_pgvector,
        )
    return _pipeline


# ---------------------------------------------------------------------------
# 任务处理
# ---------------------------------------------------------------------------


async def _process_task(
    pipeline: IndexPipeline,
    raw_message: str,
) -> None:
    """解析 Redis 消息并委托 IndexPipeline 处理。

    Args:
        pipeline: 索引管线实例。
        raw_message: Redis List 取出的 JSON 字符串（IndexTaskEnvelope 格式）。
    """
    try:
        task_data: dict[str, object] = json.loads(raw_message)
    except json.JSONDecodeError as exc:
        logger.error(
            "worker",
            f"任务消息 JSON 解析失败: {exc}",
            op_type="worker_parse_error",
            extra={"raw": raw_message[:200]},
        )
        return

    raw_case_id = task_data.get("case_id")
    case_id = CaseIdStr(raw_case_id) if isinstance(raw_case_id, str) and raw_case_id else None
    trace_id = str(task_data.get("trace_id", ""))

    if not case_id:
        logger.warning(
            "worker",
            "任务消息缺少 case_id，跳过",
            op_type="worker_skip",
            extra={"task_data": task_data},
        )
        return

    session_factory = _get_session_factory()
    async with session_factory() as session:
        await pipeline.process_task(
            case_id=case_id,
            trace_id=trace_id,
            db_session=session,
        )


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------


async def _main_loop() -> None:
    """Redis BRPOP 消费主循环。

    复用 py-rag 的 INDEX_QUEUE_KEY 常量和 IndexPipeline 实现，
    不重复索引逻辑。
    """
    pipeline = _get_pipeline()
    reconnect_interval = REDIS_RECONNECT_INITIAL

    logger.info(
        "worker",
        f"Worker 启动，监听队列: {INDEX_QUEUE_KEY}",
        op_type="worker_start",
    )

    while not _shutdown_event.is_set():
        try:
            redis_client = await get_redis_client()

            result = await maybe_await(redis_client.brpop(INDEX_QUEUE_KEY, timeout=BRPOP_TIMEOUT))

            if result is None:
                reconnect_interval = REDIS_RECONNECT_INITIAL
                continue

            reconnect_interval = REDIS_RECONNECT_INITIAL

            _queue_name, raw_message = result
            await _process_task(pipeline, raw_message)

        except asyncio.CancelledError:
            logger.info("worker", "Worker 协程被取消，退出循环")
            break

        except Exception:
            logger.error(
                "worker",
                "Worker 主循环异常",
                op_type="worker_loop_error",
                extra={
                    "error": traceback.format_exc(),
                },
            )
            await asyncio.sleep(reconnect_interval)
            reconnect_interval = min(reconnect_interval * 2, REDIS_RECONNECT_MAX)

    logger.info("worker", "Worker 主循环已退出", op_type="worker_stop")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI 入口 — 启动独立 Worker 进程。"""
    global _engine, _session_factory, _pipeline

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    main_task = loop.create_task(_main_loop())

    try:
        loop.run_until_complete(main_task)
    except KeyboardInterrupt:
        logger.info("worker", "Worker 被键盘中断")
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

        if _engine is not None:
            loop.run_until_complete(_engine.dispose())

        from py_rag.embedding import _get_encoder

        encoder = _get_encoder()
        if hasattr(encoder, "close"):
            loop.run_until_complete(encoder.close())

        loop.run_until_complete(close_redis_client())

        loop.close()

        _engine = None
        _session_factory = None
        _pipeline = None

        logger.info("worker", "Worker 已关闭")


if __name__ == "__main__":
    main()
