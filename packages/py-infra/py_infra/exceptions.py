"""CSLT-02 RAG语义检索 — 检索引擎异常定义。

追加 RetrievalTimeoutError 和 EmbeddingUnavailableError 异常类。
继承体系：
  - RetrievalTimeoutError: 检索超时且无任何结果时触发（继承 AppException 风格）
  - EmbeddingUnavailableError: DashScope 嵌入 API 不可用时触发（继承 AppException 风格）

这两个异常类的设计遵循项目统一异常体系规范，status_code 字段供
FastAPI 全局异常处理器映射为 HTTP 状态码。
"""

from __future__ import annotations


class RetrievalTimeoutError(Exception):
    """检索整体超时异常。

    当 asyncio.wait_for(timeout=0.5) 触发 TimeoutError 且无任何部分结果时抛出。
    对应落地规范 §1.9.2：检索耗时超过 500 毫秒。

    Attributes:
        message: 异常描述信息。
        elapsed_ms: 超时时的已耗时（毫秒）。
        partial_count: 超时前已返回的部分结果数量（=0 时抛出此异常）。
    """

    status_code: int = 504

    def __init__(
        self,
        message: str = "检索超时，未能返回任何结果",
        elapsed_ms: float = 500.0,
        partial_count: int = 0,
    ) -> None:
        self.message: str = message
        self.elapsed_ms: float = elapsed_ms
        self.partial_count: int = partial_count
        super().__init__(self.message)


class EmbeddingUnavailableError(Exception):
    """向量编码服务不可用异常。

    当 DashScope text-embedding-v4 API 在重试 2 次后仍然失败时抛出。
    对应落地规范 §1.9.3：DashScope 嵌入 API 不可用。

    Attributes:
        message: 异常描述信息。
        retry_count: 已尝试的重试次数（含首次尝试）。
        last_error: 最后一次失败的原始异常信息。
    """

    status_code: int = 503

    def __init__(
        self,
        message: str = "向量编码服务暂时不可用，请稍后重试",
        retry_count: int = 3,
        last_error: str = "",
    ) -> None:
        self.message: str = message
        self.retry_count: int = retry_count
        self.last_error: str = last_error
        super().__init__(self.message)


__all__ = [
    "RetrievalTimeoutError",
    "EmbeddingUnavailableError",
]
