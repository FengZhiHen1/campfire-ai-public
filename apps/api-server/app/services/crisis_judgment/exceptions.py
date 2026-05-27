"""CSLT-01 危机分级判定 — 异常定义。

异常层级：
    CrisisJudgmentError（基类）
    ├── LLMReviewTimeoutError  LLM 复审超时
    └── KeywordDictLoadError   关键词词库加载失败
"""

from __future__ import annotations


class CrisisJudgmentError(Exception):
    """危机分级判定模块的异常基类。

    所有判定层面的不可恢复错误均继承此类。
    调用方应捕获此基类或其子类以统一处理判定异常。
    """

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        self.message = message
        self.original_error = original_error
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.original_error:
            return f"{self.message} (caused by: {self.original_error})"
        return self.message


class LLMReviewTimeoutError(CrisisJudgmentError):
    """LLM 精调复审超时异常。

    当 asyncio.wait_for() 在配置的超时阈值内未收到 LLM API 响应时抛出。
    捕获此异常后 Pipeline 降级为规则引擎结果，不重试。
    """

    def __init__(
        self,
        timeout_ms: int,
        elapsed_ms: int | None = None,
        original_error: Exception | None = None,
    ) -> None:
        message = (
            f"LLM review timed out after {timeout_ms}ms"
            + (f" (elapsed: {elapsed_ms}ms)" if elapsed_ms is not None else "")
        )
        self.timeout_ms = timeout_ms
        self.elapsed_ms = elapsed_ms
        super().__init__(message=message, original_error=original_error)


class KeywordDictLoadError(CrisisJudgmentError):
    """关键词词库加载失败异常。

    当 PostgreSQL 连接失败、crisis_keywords 表不存在或查询为空时抛出。
    捕获此异常后 Pipeline 进入降级模式：规则引擎层跳过，仅依赖前置选择层。
    """

    def __init__(
        self,
        detail: str = "",
        original_error: Exception | None = None,
    ) -> None:
        message = f"failed to load keyword dictionary: {detail}" if detail else "failed to load keyword dictionary"
        super().__init__(message=message, original_error=original_error)
