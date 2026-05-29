"""CSLT-02 RAG语义检索 — 纯语义检索引擎。

提供 PgVectorSearch 类和 hybrid_search() 模块级便捷函数。
PgVectorSearch 实现 BaseSemanticSearch 契约，通过 @final search() 获得
统一的输入校验、超时保护和结果组装逻辑。

核心设计：
1. 输入校验与预处理 — Top-K 边界钳位、查询指纹计算（契约统一处理）
2. 编码查询向量 — 通过注入的 BaseEmbeddingEncoder 编码（契约统一处理）
3. 纯语义检索 — pgvector HNSW（实现者填充 _do_search 钩子）
4. 超时保护包装 — asyncio.wait_for（契约统一处理）
5. 结果组装与排序 — SemanticSearchResult（契约统一处理）
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from py_db.repositories.consult_repository import ConsultRepository
from py_logger import logger
from py_rag.embedding_contract import BaseEmbeddingEncoder
from py_rag.retrieval_contract import BaseSemanticSearch
from py_rag.types import EmbeddingVector
from py_schemas.consult import SemanticSearchResult

# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------

_search_engine: PgVectorSearch | None = None


def _get_search_engine() -> PgVectorSearch:
    """获取全局检索引擎单例。"""
    global _search_engine
    if _search_engine is None:
        from py_rag.embedding import _get_encoder

        _search_engine = PgVectorSearch(embedding_encoder=_get_encoder())
    return _search_engine


# ---------------------------------------------------------------------------
# PgVectorSearch — 契约实现类
# ---------------------------------------------------------------------------


class PgVectorSearch(BaseSemanticSearch):
    """pgvector 语义检索引擎。

    实现 BaseSemanticSearch 契约的 _do_search() 钩子，
    委托 ConsultRepository.search_similar_chunks() 执行 pgvector HNSW 查询。
    """

    def __init__(self, embedding_encoder: BaseEmbeddingEncoder) -> None:
        super().__init__(embedding_encoder)

    # === _do_search 钩子实现 ===

    async def _do_search(
        self,
        query_vector: EmbeddingVector,
        top_k: int,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """执行 pgvector HNSW 语义检索。

        委托 ConsultRepository.search_similar_chunks()。
        不需要关心编码和校验——@final search 已处理。

        Args:
            query_vector: 已通过维度校验的 1024 维向量。
            top_k: 已钳位到 [1, 50] 的结果数量。
            db: 有效异步会话。

        Returns:
            原始数据库行字典列表，由 search() 组装为 SemanticSearchResult。
        """
        repo = ConsultRepository()
        return await repo.search_similar_chunks(  # type: ignore[no-any-return]
            session=db,
            query_vector=query_vector,
            top_k=top_k,
        )


# ---------------------------------------------------------------------------
# 模块级便捷函数（向后兼容）
# ---------------------------------------------------------------------------


async def hybrid_search(
    query_text: str,
    top_k: int = 10,
    request_id: str | None = None,
    db: AsyncSession = None,  # type: ignore[assignment]
) -> SemanticSearchResult:
    """对用户行为描述文本执行纯语义检索。

    委托 PgVectorSearch.search()，走完整契约管线：
    输入校验 → 编码查询向量 → 检索相似切片 → 结果组装排序。

    Args:
        query_text: 用户行为描述文本（1-2000 字符，上游已脱敏 PII）。
        top_k: 期望返回的结果数量（默认 10，范围 1-50）。
        request_id: 全链路追踪 ID（可选，由上游生成）。
        db: 异步数据库会话（由调用方注入）。

    Returns:
        SemanticSearchResult: 排序后的案例切片列表及检索状态。

    Raises:
        EmbeddingUnavailableError: DashScope 编码服务不可用（重试耗尽）。
        RetrievalTimeoutError: 整体检索超时且无任何结果。
        ValueError: 参数校验失败（query_text 空、db 为 None 等）。
    """
    return await _get_search_engine().search(
        query_text=query_text,
        top_k=top_k,
        request_id=request_id,
        db=db,
    )


__all__ = ["PgVectorSearch", "hybrid_search"]
