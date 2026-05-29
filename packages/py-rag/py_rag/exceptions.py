"""py-rag 异常类定义。

模块: py_rag.exceptions
职责: 定义 py-rag 包所有公开异常的层次结构。
      所有 py-rag 异常继承自 RagError 基类，确保上层可统一捕获。
数据来源:
  - 无外部数据来源
边界:
  - 依赖: Python 标准库 Exception
  - 被依赖: py_rag 内所有模块、api-server 异常处理中间件
禁止行为:
  - 禁止在异常类中包含数据库查询或 HTTP 调用
  - 禁止裸 raise Exception（必须使用 RagError 子类）
  - 禁止异常消息使用英文

设计意图：
  - RagError 作为统一基类，上层 try/except RagError 即可捕获所有本包异常
  - 每个子类携带诊断字段（missing_fields、patterns_matched 等），方便日志和监控
"""

from __future__ import annotations


class RagError(Exception):
    """py-rag 统一异常基类。

    所有 py-rag 抛出的异常必须继承此类。
    """


# ============================================================================
# 嵌入编码异常
# ============================================================================


class EmbeddingError(RagError):
    """嵌入服务调用异常。

    触发条件：DashScope API 不可达、返回非 2xx、或响应解析失败后重试耗尽。

    诊断字段:
      - retry_count: 已执行的重试次数
      - last_error: 最后一次失败的异常信息
    """

    def __init__(
        self,
        message: str,
        retry_count: int = 0,
        last_error: str | None = None,
    ) -> None:
        self.retry_count = retry_count
        self.last_error = last_error
        super().__init__(message)


# ============================================================================
# 索引相关异常
# ============================================================================


class ChunkBuildError(RagError):
    """文本组装阶段异常。

    触发条件：四段式字段任一为空或过短、免责声明在文本组装过程中丢失。

    诊断字段:
      - missing_fields: 缺失或过短的字段名列表
      - case_id: 出错的案例标识
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


class PIIRejectionError(RagError):
    """PII 最终防线校验触发异常。

    触发条件：chunk_text 中正则匹配到手机号、身份证号或家庭住址模式。

    诊断字段:
      - patterns_matched: 匹配到的 PII 模式名列表
      - sample_offset: 第一个匹配在文本中的偏移量
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


class IndexWriteError(RagError):
    """pgvector 索引写入异常。

    触发条件：case_chunks INSERT 失败，重试耗尽后仍失败。

    诊断字段:
      - case_id: 出错的案例标识
      - retry_count: 已执行的重试次数
      - last_error: 最后一次失败的异常信息
    """

    def __init__(
        self,
        message: str,
        case_id: str | None = None,
        retry_count: int = 0,
        last_error: str | None = None,
    ) -> None:
        self.case_id = case_id
        self.retry_count = retry_count
        self.last_error = last_error
        super().__init__(message)


class RedisConnectionError(RagError):
    """Redis List 连接失败异常。

    触发条件：LPUSH/BRPOP 操作超时后重试仍失败。
    """


__all__ = [
    "RagError",
    "EmbeddingError",
    "ChunkBuildError",
    "PIIRejectionError",
    "IndexWriteError",
    "RedisConnectionError",
]
