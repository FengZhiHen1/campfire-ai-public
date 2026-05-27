"""py-rag — Campfire-AI 向量能力统一包。

提供两大能力：
1. 嵌入编码：encode_text() — DashScope text-embedding-v4 原生 API
2. 语义检索：hybrid_search() — 混合检索（标签过滤 + 向量相似度 + 时效衰减 + 循证加权）
3. 索引入库：indexing 子包 — 案例向量化入库异步管线

Usage:
    from py_rag import encode_text, hybrid_search
    from py_rag.indexing import enqueue_index_task, start_worker
"""

from py_rag.embedding import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    encode_query,
    encode_text,
    reset_embedding_failure_count,
)
from py_rag.retrieval import hybrid_search

__all__ = [
    "encode_text",
    "encode_query",
    "hybrid_search",
    "reset_embedding_failure_count",
    "EMBEDDING_DIMENSION",
    "EMBEDDING_MODEL",
]
