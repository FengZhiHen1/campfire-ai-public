"""py-rag 异常层次定义。

从 py-infra 迁移的 RAG 检索异常。
"""

from __future__ import annotations


class RetrievalTimeoutError(Exception):
    """检索整体超时异常。

    当 asyncio.wait_for(timeout=0.5) 触发 TimeoutError 且无任何部分结果时抛出。

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


class RedisConnectionError(Exception):
    """Redis 连接异常。

    当 Redis LPUSH 入队操作在重试耗尽后仍然失败时抛出。

    Attributes:
        message: 异常描述信息。
        retry_count: 已尝试的重试次数。
        last_error: 最后一次失败的原始异常信息。
    """

    status_code: int = 503

    def __init__(
        self,
        message: str = "Redis 连接失败，索引任务入队中断",
        retry_count: int = 3,
        last_error: str = "",
    ) -> None:
        self.message: str = message
        self.retry_count: int = retry_count
        self.last_error: str = last_error
        super().__init__(self.message)


class ChunkBuildError(Exception):
    """文本块构建异常。

    当案例数据四段式字段不完整或免责声明在组装过程中丢失时抛出。

    Attributes:
        message: 异常描述信息。
        missing_fields: 缺失的字段列表。
        case_id: 关联的案例 ID。
    """

    status_code: int = 422

    def __init__(
        self,
        message: str = "文本块构建失败",
        missing_fields: list[str] | None = None,
        case_id: str = "",
    ) -> None:
        self.message: str = message
        self.missing_fields: list[str] = missing_fields or []
        self.case_id: str = case_id
        super().__init__(self.message)


class PIIRejectionError(Exception):
    """PII 脱敏检测拒绝异常。

    当索引文本块最终防线检测到未脱敏的个人信息时抛出。

    Attributes:
        message: 异常描述信息。
        patterns_matched: 匹配到的 PII 模式列表。
        sample_offset: 匹配位置的字符偏移量。
    """

    status_code: int = 422

    def __init__(
        self,
        message: str = "文本包含未脱敏的个人信息",
        patterns_matched: list[str] | None = None,
        sample_offset: int | None = None,
    ) -> None:
        self.message: str = message
        self.patterns_matched: list[str] = patterns_matched or []
        self.sample_offset: int | None = sample_offset
        super().__init__(self.message)


class EmbeddingUnavailableError(Exception):
    """向量编码服务不可用异常。

    当 DashScope text-embedding-v4 API 在重试 2 次后仍然失败时抛出。

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
    "ChunkBuildError",
    "EmbeddingUnavailableError",
    "PIIRejectionError",
    "RedisConnectionError",
    "RetrievalTimeoutError",
]
