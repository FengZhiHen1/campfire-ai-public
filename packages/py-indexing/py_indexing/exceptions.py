"""CASE-04 异常类定义。

本模块定义 4 个自定义异常类型：
    - ChunkBuildError: 四段式字段不完整或免责声明丢失
    - PIIRejectionError: PII 最终防线校验触发
    - RedisConnectionError: Redis List 连接失败
    - EmbeddingServiceError: 嵌入服务不可用或超时
"""

from __future__ import annotations


class ChunkBuildError(Exception):
    """文本组装阶段异常。

    触发条件：
    - 四段式字段（scene_description, behavior_manifestation,
      intervention_action, result_feedback）任一为空或过短
    - 免责声明在文本组装过程中丢失

    Attributes:
        message: 错误描述。
        missing_fields: 缺失/过短的字段名列表。
        case_id: 关联的案例标识。
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

    触发条件：
    - chunk_text 中正则匹配到手机号、身份证号或家庭住址模式

    Attributes:
        message: 错误描述。
        patterns_matched: 匹配到的模式类型列表（如 ["phone_number", "id_card"]）。
        sample_offset: 匹配文本在 chunk_text 中的偏移量。
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

    触发条件：
    - LPUSH 操作超时后重试 1 次仍失败
    - Redis 连接池耗尽或服务不可达
    """


class EmbeddingServiceError(Exception):
    """嵌入服务不可用或超时异常。

    触发条件：
    - 阿里 text-embedding-v4 API 返回 4xx/5xx
    - httpx 请求超时（超过 EMBEDDING_TIMEOUT）
    - 响应 JSON 解析失败或 embedding 字段缺失
    - 返回的 embedding 数组长度不等于 1024
    """


__all__ = [
    "ChunkBuildError",
    "PIIRejectionError",
    "RedisConnectionError",
    "EmbeddingServiceError",
]
