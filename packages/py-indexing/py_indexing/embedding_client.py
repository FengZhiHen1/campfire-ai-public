"""CASE-04 嵌入服务客户端模块。

负责调用阿里 text-embedding-v4 API 生成 1024 维文本嵌入向量。
包含熔断器机制：连续 5 次失败后暂停消费 30 秒。

对外接口：
    - generate_embedding(chunk_text: str) -> list[float]
    - reset_embedding_failure_count()
    - embedding_failure_count: int  — 全局失败计数器
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from py_config import get_settings
from py_logger import logger

from py_indexing.exceptions import EmbeddingServiceError

# ============================================================================
# 常量
# ============================================================================

EMBEDDING_TIMEOUT: int = 5
"""嵌入 API 超时阈值（秒）。"""

EMBEDDING_MODEL: str = "text-embedding-v4"
"""嵌入模型名称。"""

EMBEDDING_URL: str = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
)
"""阿里 text-embedding-v4 API 端点。"""

MAX_CONSECUTIVE_FAILURES: int = 5
"""触发熔断的连续失败次数阈值。"""

CIRCUIT_BREAKER_SLEEP: int = 30
"""熔断器暂停时间（秒）。"""

RETRY_INTERVALS: list[float] = [1.0, 3.0]
"""重试退避间隔：第 1 次重试等待 1s，第 2 次重试等待 3s。"""

# ============================================================================
# 模块级状态
# ============================================================================

embedding_failure_count: int = 0
"""嵌入服务连续失败计数器（模块级变量，asyncio 单线程天然安全）。"""

_http_client: httpx.AsyncClient | None = None
"""httpx 异步客户端（模块级单例，带连接池）。"""


# ============================================================================
# 公开接口
# ============================================================================


async def generate_embedding(chunk_text: str) -> list[float]:
    """调用阿里 text-embedding-v4 API 生成文本嵌入向量。

    本函数内嵌重试逻辑：
    - 重试最多 2 次（共 3 次尝试）
    - 线性退避间隔：1s → 3s
    - 全局连续失败计数器在每次真实失败时递增

    Args:
        chunk_text: 待向量化的文本字符串。

    Returns:
        1024 维 float32 向量列表。

    Raises:
        EmbeddingServiceError: 所有重试耗尽后仍失败。
    """
    global embedding_failure_count
    last_error: Exception | None = None

    # 尝试 3 次（1 主 + 2 重试）
    for attempt in range(3):
        try:
            result: list[float] = await _do_embed(chunk_text)

            # 成功：重置失败计数器（无论是否重试后成功）
            embedding_failure_count = 0

            return result

        except (httpx.HTTPStatusError, httpx.TimeoutException, KeyError, ValueError) as exc:
            last_error = exc
            embedding_failure_count += 1

            if attempt < 2:
                # 还有重试机会，等待退避间隔后重试
                wait_time: float = RETRY_INTERVALS[attempt]
                logger.warning(
                    "py-indexing",
                    f"嵌入 API 调用失败，{wait_time}s 后重试",
                    op_type="embedding_retry",
                    extra={
                        "attempt": attempt + 1,
                        "max_attempts": 3,
                        "error": str(exc),
                        "phase": "generate_embedding",
                    },
                )
                await asyncio.sleep(wait_time)
            else:
                # 所有尝试耗尽
                logger.error(
                    "py-indexing",
                    "嵌入 API 重试耗尽",
                    op_type="embedding_exhausted",
                    extra={
                        "retry_count": 2,
                        "last_error": str(last_error),
                        "phase": "generate_embedding",
                    },
                )

    # 触发熔断检查
    if embedding_failure_count >= MAX_CONSECUTIVE_FAILURES:
        logger.warning(
            "py-indexing",
            f"嵌入服务连续 {MAX_CONSECUTIVE_FAILURES} 次失败，熔断器触发，暂停 {CIRCUIT_BREAKER_SLEEP}s",
            op_type="circuit_breaker_triggered",
            extra={
                "failure_count": embedding_failure_count,
                "circuit_breaker_sleep": CIRCUIT_BREAKER_SLEEP,
            },
        )
        await asyncio.sleep(CIRCUIT_BREAKER_SLEEP)
        embedding_failure_count = 0

    raise EmbeddingServiceError(
        f"嵌入 API 调用失败，重试 3 次后仍未恢复: {last_error}",
    ) from last_error


def reset_embedding_failure_count() -> None:
    """重置嵌入服务失败计数器（用于测试和手动恢复）。"""
    global embedding_failure_count
    embedding_failure_count = 0


# ============================================================================
# 内部函数
# ============================================================================


async def _do_embed(chunk_text: str) -> list[float]:
    """执行单次嵌入 API 调用。

    Args:
        chunk_text: 待向量化的文本。

    Returns:
        1024 维向量列表。

    Raises:
        httpx.HTTPStatusError: API 返回 4xx/5xx。
        httpx.TimeoutException: 请求超时。
        KeyError: 响应 JSON 中缺少 expected 字段。
        ValueError: embedding 维度不为 1024。
    """
    client: httpx.AsyncClient = _get_http_client()
    settings = get_settings()

    api_key: str = settings.DASHSCOPE_API_KEY.get_secret_value()

    request_body: dict[str, object] = {
        "model": EMBEDDING_MODEL,
        "input": {"texts": [chunk_text]},
        "parameters": {"text_type": "document"},
    }

    headers: dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = await client.post(
        EMBEDDING_URL,
        json=request_body,
        headers=headers,
        timeout=EMBEDDING_TIMEOUT,
    )
    response.raise_for_status()

    response_data: dict[str, Any] = response.json()

    # 提取 embedding 数组
    data_list: list[Any] = response_data.get("data", [])
    if not data_list:
        raise KeyError("响应 data 字段为空")

    embedding: list[float] = data_list[0].get("embedding", [])
    if not embedding:
        raise KeyError("响应 data[0].embedding 字段缺失")

    # 维度校验
    if len(embedding) != 1024:
        raise ValueError(
            f"期望 1024 维，实际 {len(embedding)} 维",
        )

    return embedding


def _get_http_client() -> httpx.AsyncClient:
    """获取 httpx 异步客户端单例（带连接池）。

    Returns:
        全局 httpx.AsyncClient 实例。
    """
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient()
    return _http_client
