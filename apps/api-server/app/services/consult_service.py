"""CSLT-02 RAG语义检索 — search_cases() 服务编排。

编排请求校验 → 检索引擎调用 → 结果包装的完整用例流程。

本 Service 是 consult 模块的业务编排入口，组合 py-rag 的检索引擎
和 py-schemas 的 DTO 来完成一次完整的语义检索。

调用路径：
  api/v1/consult.py → consult_service.search_cases() → py_rag.retrieval.hybrid_search()
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from py_rag.retrieval import hybrid_search
from py_schemas.consult import (
    SemanticSearchInput,
    SemanticSearchResult,
)

_logger = logging.getLogger(__name__)


async def search_cases(
    request: SemanticSearchInput,
    db: AsyncSession,
) -> SemanticSearchResult:
    """RAG 语义检索用例编排。

    按以下步骤执行一次完整的语义检索：
    1. 二次校验：Top-K 边界钳位（由 hybrid_search 内部处理）
    2. 调用 hybrid_search 执行混合检索
    3. 返回 SemanticSearchResult 给 API 层

    Args:
        request: Pydantic 校验通过的语义检索请求（含 query_text、tag_filters、top_k、request_id）。
        db: 活动数据库异步会话（由依赖注入提供）。

    Returns:
        SemanticSearchResult: 排序后的案例切片列表及检索状态。

    Raises:
        异常向上传播给 FastAPI 全局异常处理器：
        - EmbeddingUnavailableError → 503
        - DependencyCommunicationError → 503
        - 其他未预期异常 → 500
    """
    # --- 入口参数校验 ---
    if request is None:
        raise ValueError("request must not be None")
    if db is None:
        raise ValueError("db must not be None")

    # 提取请求参数
    query_text: str = request.query_text
    tag_filters = request.tag_filters
    top_k: int = request.top_k
    request_id: str | None = request.request_id

    _logger.info(
        "search_cases_started",
        extra={
            "request_id": request_id,
            "query_len": len(query_text),
            "top_k": top_k,
            "tag_filters": {
                "age_range": tag_filters.age_range,
                "behavior_type": tag_filters.behavior_type,
                "emotion_level": tag_filters.emotion_level,
            },
        },
    )

    # Step: 调用检索引擎
    result: SemanticSearchResult = await hybrid_search(
        query_text=query_text,
        tag_filters=tag_filters,
        top_k=top_k,
        request_id=request_id,
        db=db,
    )

    _logger.info(
        "search_cases_completed",
        extra={
            "request_id": request_id,
            "result_count": result.total_count,
            "elapsed_ms": result.elapsed_ms,
            "is_complete": result.is_complete,
            "degradation_level": result.degradation_level.value,
        },
    )

    return result


__all__ = ["search_cases"]
