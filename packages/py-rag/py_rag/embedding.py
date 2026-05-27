"""py-rag 统一文本嵌入编码模块。

基于 DashScope 原生 API（非 OpenAI 兼容模式）调用 text-embedding-v4，
支持 text_type 参数区分 document（索引入库）和 query（检索查询）。

API 协议：DashScope 原生
端点：POST https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding
模型：text-embedding-v4
维度：1024

参考文档：docs/API文档/通义-文本与多模态向量化.md
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import httpx

from py_config import get_settings
from py_infra.exceptions import EmbeddingUnavailableError
from py_logger import logger

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

EMBEDDING_URL: str = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
)
EMBEDDING_MODEL: str = "text-embedding-v4"
EMBEDDING_DIMENSION: int = 1024
EMBEDDING_TIMEOUT: int = 5

MAX_RETRY_COUNT: int = 2  # 共 3 次尝试（1 主 + 2 重试）
RETRY_INTERVALS: list[float] = [1.0, 3.0]  # 线性退避

MAX_CONSECUTIVE_FAILURES: int = 5
CIRCUIT_BREAKER_SLEEP: int = 30

# ---------------------------------------------------------------------------
# 模块级状态
# ---------------------------------------------------------------------------

embedding_failure_count: int = 0
"""嵌入服务连续失败计数器（asyncio 单线程模型下天然安全）。"""

_http_client: httpx.AsyncClient | None = None


# ---------------------------------------------------------------------------
# 公共接口
# ---------------------------------------------------------------------------


async def encode_text(
    text: str,
    text_type: Literal["document", "query"] = "document",
) -> list[float]:
    """将文本编码为 1024 维嵌入向量。

    使用 DashScope 原生 API，支持 text_type 参数：
    - "document"：用于索引入库的文档文本（默认），模型生成"正文"向量
    - "query"：用于检索的查询文本，模型生成"标题"向量，更具方向性

    内嵌重试逻辑：最多 3 次尝试，线性退避 1s → 3s。
    连续 5 次失败触发熔断器，暂停 30 秒后恢复。

    Args:
        text: 待编码的文本字符串（非空）。
        text_type: 文本类型，"document" 或 "query"。

    Returns:
        1024 维 float32 向量列表。

    Raises:
        EmbeddingUnavailableError: 所有重试耗尽后仍失败。
        ValueError: text 为空或仅空白字符。
    """
    if not text or not text.strip():
        raise EmbeddingUnavailableError(
            message="编码文本不能为空",
            retry_count=0,
            last_error="empty_text",
        )

    global embedding_failure_count
    last_error: Exception | None = None

    for attempt in range(MAX_RETRY_COUNT + 1):
        try:
            result = await _do_embed(text, text_type)
            embedding_failure_count = 0
            return result

        except (httpx.HTTPStatusError, httpx.TimeoutException, KeyError, ValueError) as exc:
            last_error = exc
            embedding_failure_count += 1

            if attempt < MAX_RETRY_COUNT:
                wait_time = RETRY_INTERVALS[attempt]
                logger.warning(
                    "py-rag",
                    f"嵌入 API 调用失败，{wait_time}s 后重试",
                    op_type="embedding_retry",
                    extra={
                        "attempt": attempt + 1,
                        "max_attempts": MAX_RETRY_COUNT + 1,
                        "error": str(exc),
                        "text_type": text_type,
                    },
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(
                    "py-rag",
                    "嵌入 API 重试耗尽",
                    op_type="embedding_exhausted",
                    extra={
                        "retry_count": MAX_RETRY_COUNT,
                        "last_error": str(last_error),
                        "text_type": text_type,
                    },
                )

    # 熔断器检查
    if embedding_failure_count >= MAX_CONSECUTIVE_FAILURES:
        logger.warning(
            "py-rag",
            f"嵌入服务连续 {MAX_CONSECUTIVE_FAILURES} 次失败，熔断器触发，暂停 {CIRCUIT_BREAKER_SLEEP}s",
            op_type="circuit_breaker_triggered",
            extra={"failure_count": embedding_failure_count},
        )
        await asyncio.sleep(CIRCUIT_BREAKER_SLEEP)
        embedding_failure_count = 0

    raise EmbeddingUnavailableError(
        message="向量编码服务暂时不可用，请稍后重试",
        retry_count=MAX_RETRY_COUNT + 1,
        last_error=str(last_error),
    )


def reset_embedding_failure_count() -> None:
    """重置嵌入服务失败计数器（用于测试和手动恢复）。"""
    global embedding_failure_count
    embedding_failure_count = 0


# ---------------------------------------------------------------------------
# 内部函数
# ---------------------------------------------------------------------------


async def _do_embed(
    text: str,
    text_type: Literal["document", "query"],
) -> list[float]:
    """执行单次嵌入 API 调用（DashScope 原生协议）。

    Args:
        text: 待编码的文本。
        text_type: 文本类型。

    Returns:
        1024 维向量列表。

    Raises:
        httpx.HTTPStatusError: API 返回非 2xx。
        httpx.TimeoutException: 请求超时。
        KeyError: 响应中缺少 embedding 字段。
        ValueError: embedding 维度不为 1024。
    """
    client = _get_http_client()
    settings = get_settings()
    api_key = settings.DASHSCOPE_API_KEY.get_secret_value()

    request_body: dict[str, Any] = {
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

    # DashScope 原生响应格式: {"output": {"embeddings": [{"embedding": [...], "text_index": 0}]}}
    embeddings: list[dict[str, Any]] = data.get("output", {}).get("embeddings", [])
    if not embeddings:
        raise KeyError("响应 output.embeddings 字段为空")

    embedding: list[float] = embeddings[0].get("embedding", [])
    if not embedding:
        raise KeyError("响应中缺少 embedding 字段")

    if len(embedding) != EMBEDDING_DIMENSION:
        raise ValueError(f"期望 {EMBEDDING_DIMENSION} 维，实际 {len(embedding)} 维")

    return embedding


def _get_http_client() -> httpx.AsyncClient:
    """获取 httpx 异步客户端单例（带连接池）。"""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient()
    return _http_client


# 向后兼容别名 — 落地规范 §1.6.1 定义的接口名为 encode_query
async def encode_query(text: str) -> list[float]:
    """落地规范兼容接口：将查询文本编码为 1024 维向量（text_type="query"）。

    等价于 encode_text(text, text_type="query")。
    """
    return await encode_text(text, text_type="query")


__all__ = [
    "encode_text",
    "encode_query",
    "reset_embedding_failure_count",
    "EMBEDDING_DIMENSION",
    "EMBEDDING_MODEL",
]
