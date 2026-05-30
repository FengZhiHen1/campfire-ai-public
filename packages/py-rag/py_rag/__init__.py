"""py-rag — Campfire-AI 向量能力统一包。

提供三大能力：
1. 嵌入编码：DashScopeEncoder + encode_text() — DashScope text-embedding-v4
2. 语义检索：PgVectorSearch + hybrid_search() — pgvector HNSW 纯语义检索
3. 索引入库：indexing 子包 — 案例向量化入库异步管线

Usage:
    from py_rag import encode_text, hybrid_search
    from py_rag import DashScopeEncoder
    from py_rag.indexing import enqueue_index_task, start_worker
"""

from py_rag.embedding import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    DashScopeEncoder,
    encode_query,
    encode_text,
    reset_embedding_failure_count,
)
from py_rag.exceptions import EmbeddingUnavailableError, RetrievalTimeoutError
from py_rag.retrieval import PgVectorSearch, hybrid_search

__all__ = [
    # 类
    "DashScopeEncoder",
    "PgVectorSearch",
    # 便捷函数
    "encode_text",
    "encode_query",
    "hybrid_search",
    "reset_embedding_failure_count",
    # 常量
    "EMBEDDING_DIMENSION",
    "EMBEDDING_MODEL",
    # 异常
    "RetrievalTimeoutError",
    "EmbeddingUnavailableError",
]
