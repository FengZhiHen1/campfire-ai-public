"""Worker 任务：案例卡片向量化索引入库。

委托 py_rag.indexing.IndexPipeline 处理完整索引管线（CASE-04 契约）：
文本组装 → PII 校验 → 嵌入编码 → pgvector 写入 → 状态标记。

本模块作为向后兼容的薄层——实际索引逻辑全部在 py-rag 中。
"""

from __future__ import annotations

from py_logger import logger
from py_rag.indexing import IndexPipeline
from py_rag.indexing_contract import INDEX_QUEUE_KEY


async def index_case(case_id: str, trace_id: str = "") -> None:
    """对单个案例卡片执行向量化索引入库（ad-hoc 调试用）。

    委托 IndexPipeline.process_task() 走完整契约管线。
    每次调用创建独立的数据库引擎和会话，完成后自动释放。

    注意：本函数每次调用重建连接池，不适合生产循环调用。
    生产路径请走 main.py 的 _get_session_factory() 单例。

    Args:
        case_id: 卡片 UUID 字符串。
        trace_id: 全链路追踪标识（32 位十六进制），为空时由管线内部生成。
    """
    logger.info(
        "worker",
        f"开始处理案例索引: {case_id}",
        op_type="index_case_start",
        extra={"case_id": case_id, "trace_id": trace_id},
    )

    from py_rag.embedding import _get_encoder
    from py_rag.indexing.chunk_builder import build_chunk_text
    from py_rag.indexing.index_writer import write_index_to_pgvector

    pipeline = IndexPipeline(
        embedding_encoder=_get_encoder(),
        chunk_builder=build_chunk_text,
        index_writer=write_index_to_pgvector,
    )

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from py_config import get_settings

    settings = get_settings()
    database_url = str(settings.DATABASE_URL)

    engine = None
    try:
        engine = create_async_engine(database_url, echo=False)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            await pipeline.process_task(
                case_id=case_id,
                trace_id=trace_id,
                db_session=session,
            )
    finally:
        if engine is not None:
            await engine.dispose()


__all__ = ["index_case", "INDEX_QUEUE_KEY"]
