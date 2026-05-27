"""py-rag 异常类定义。

包含：
- EmbeddingUnavailableError, RetrievalTimeoutError（检索端，由 py_infra 定义）
- ChunkBuildError, PIIRejectionError, RedisConnectionError（索引端）
"""

from __future__ import annotations


class ChunkBuildError(Exception):
    """文本组装阶段异常。

    触发条件：四段式字段任一为空或过短、免责声明在文本组装过程中丢失。
    """

    def __init__(
        self,
        message: str,
        missing_fields: list[str] | None = None,
        case_id: str | None = None,
    ) -> None:
        self.missing_fields = missing_fields or []
        self.case_id = case_id
        super().__init__(message)


class PIIRejectionError(Exception):
    """PII 最终防线校验触发异常。

    触发条件：chunk_text 中正则匹配到手机号、身份证号或家庭住址模式。
    """

    def __init__(
        self,
        message: str,
        patterns_matched: list[str] | None = None,
        sample_offset: int | None = None,
    ) -> None:
        self.patterns_matched = patterns_matched or []
        self.sample_offset = sample_offset
        super().__init__(message)


class RedisConnectionError(Exception):
    """Redis List 连接失败异常。

    触发条件：LPUSH 操作超时后重试 1 次仍失败。
    """


__all__ = [
    "ChunkBuildError",
    "PIIRejectionError",
    "RedisConnectionError",
]
