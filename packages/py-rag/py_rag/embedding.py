"""py-rag 统一文本嵌入编码模块。

基于 DashScope 原生 API（非 OpenAI 兼容模式）调用 text-embedding-v4，
支持 text_type 参数区分 document（索引入库）和 query（检索查询）。

核心类 DashScopeEncoder 实现 BaseEmbeddingEncoder 契约，
通过 @final encode() 获得统一的重试循环与熔断器。

模块级便捷函数（向后兼容）：
  - encode_text(): 委托给 DashScopeEncoder 单例
  - encode_query(): 等价于 encode_text(text_type="query")

API 协议：DashScope 原生
端点：POST https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding
模型：text-embedding-v4
维度：1024

参考文档：docs/API文档/通义-文本与多模态向量化.md
"""

from __future__ import annotations

from typing import Literal

import httpx

from typing import Any

from py_config import get_settings
from py_logger import logger
from py_rag.embedding_contract import BaseEmbeddingEncoder
from py_rag.types import EMBEDDING_DIMENSION, EmbeddingVector

# ---------------------------------------------------------------------------
# 模块级常量
# ---------------------------------------------------------------------------

EMBEDDING_URL: str = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
)
EMBEDDING_MODEL: str = "text-embedding-v4"
# 单次 embedding HTTP 调用超时，适当放宽以应对网络抖动。
EMBEDDING_TIMEOUT: int = 15
EMBEDDING_MAX_CONNECTIONS: int = 5
EMBEDDING_MAX_KEEPALIVE: int = 2


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------

_encoder: DashScopeEncoder | None = None


def _get_encoder() -> DashScopeEncoder:
    """获取全局嵌入编码器单例。"""
    global _encoder
    if _encoder is None:
        _encoder = DashScopeEncoder()
    return _encoder


# ---------------------------------------------------------------------------
# DashScopeEncoder — 契约实现类
# ---------------------------------------------------------------------------


class DashScopeEncoder(BaseEmbeddingEncoder):
    """DashScope text-embedding-v4 编码器。

    实现 BaseEmbeddingEncoder 契约的 _do_encode() 钩子，
    管理 httpx.AsyncClient 生命周期。
    """

    def __init__(self) -> None:
        super().__init__()
        self._http_client: httpx.AsyncClient | None = None

    # === _do_encode 钩子实现 ===

    async def _do_encode(
        self,
        text: str,
        text_type: Literal["document", "query"],
    ) -> list[float]:
        """执行单次 DashScope 嵌入 API 调用。

        Args:
            text: 已通过 _validate_text 校验的待编码文本。
            text_type: "document"（索引入库）或 "query"（检索查询）。

        Returns:
            1024 维向量列表。

        Raises:
            httpx.HTTPStatusError: API 返回非 2xx。
            httpx.TimeoutException: 请求超时。
            KeyError: 响应中缺少 embedding 字段。
            ValueError: embedding 维度不为 1024。
        """
        client = self._get_client()
        settings = get_settings()
        api_key = settings.DASHSCOPE_API_KEY.get_secret_value()

        request_body: dict[str, object] = {
            "model": EMBEDDING_MODEL,
            "input": {"texts": [text]},
            "parameters": {
                "text_type": text_type,
                "dimension": EMBEDDING_DIMENSION,
            },
        }

        response = await client.post(
            EMBEDDING_URL,
            json=request_body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=EMBEDDING_TIMEOUT,
        )
        response.raise_for_status()

        data: dict[str, Any] = response.json()

        # DashScope 原生响应格式:
        #   {"output": {"embeddings": [{"embedding": [...], "text_index": 0}]}}
        output: dict[str, Any] = data.get("output", {}) or {}
        embeddings: list[dict[str, Any]] = output.get("embeddings", []) or []
        if not embeddings:
            raise KeyError("响应 output.embeddings 字段为空")

        embedding: list[float] = embeddings[0].get("embedding", [])
        if not embedding:
            raise KeyError("响应中缺少 embedding 字段")

        if len(embedding) != EMBEDDING_DIMENSION:
            raise ValueError(
                f"期望 {EMBEDDING_DIMENSION} 维，实际 {len(embedding)} 维"
            )

        return embedding

    # === HTTP 客户端管理 ===

    def _get_client(self) -> httpx.AsyncClient:
        """获取 httpx 异步客户端单例（带连接池）。"""
        if self._http_client is None:
            limits = httpx.Limits(
                max_connections=EMBEDDING_MAX_CONNECTIONS,
                max_keepalive_connections=EMBEDDING_MAX_KEEPALIVE,
            )
            self._http_client = httpx.AsyncClient(limits=limits)
        return self._http_client

    async def close(self) -> None:
        """关闭 HTTP 客户端连接池。"""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None


# ---------------------------------------------------------------------------
# 模块级便捷函数（向后兼容）
# ---------------------------------------------------------------------------


async def encode_text(
    text: str,
    text_type: Literal["document", "query"] = "document",
) -> EmbeddingVector:
    """将文本编码为 1024 维嵌入向量。

    使用 DashScope 原生 API，支持 text_type 参数：
    - "document"：用于索引入库的文档文本（默认）
    - "query"：用于检索的查询文本

    Args:
        text: 待编码的文本字符串（非空）。
        text_type: 文本类型，"document" 或 "query"。

    Returns:
        1024 维 float32 向量列表。

    Raises:
        EmbeddingUnavailableError: 所有重试耗尽后仍失败。
        ValueError: text 为空或仅空白字符。
    """
    return await _get_encoder().encode(text, text_type)


async def encode_query(text: str) -> EmbeddingVector:
    """将查询文本编码为 1024 维向量（text_type="query"）。

    等价于 encode_text(text, text_type="query")。
    """
    return await encode_text(text, text_type="query")


def reset_embedding_failure_count() -> None:
    """重置嵌入服务失败计数器（用于测试和手动恢复）。"""
    _get_encoder().reset_failure_count()


__all__ = [
    "DashScopeEncoder",
    "encode_text",
    "encode_query",
    "reset_embedding_failure_count",
    "EMBEDDING_DIMENSION",
    "EMBEDDING_MODEL",
]
