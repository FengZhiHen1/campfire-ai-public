# @contract
"""api-server 危机分级判定 — 异常定义。

模块: app.modules.crisis.exceptions
职责: 定义危机分级判定模块的统一异常层次。所有判定层面的不可恢复错误
      继承自 CrisisJudgmentError 基类，调用方可通过 except CrisisJudgmentError
      统一捕获本模块的所有错误。

数据来源:
  - 无外部数据来源（纯异常类型定义）

边界:
  - 依赖: 无（仅依赖 Python 标准库）
  - 被依赖: crisis_contract.py, pipeline.py, service.py, 各判定层

禁止行为:
  - 禁止在异常构造函数中执行 IO 操作（日志记录由捕获方负责）
  - 禁止异常携带不可序列化的对象（影响跨进程传递和日志序列化）
  - 禁止在业务代码中 return error dict——必须 raise 具名异常
"""

from __future__ import annotations


class CrisisJudgmentError(Exception):
    """危机分级判定模块的异常基类。

    触发条件: 所有判定层面的不可恢复错误。
    诊断字段:
      - message: 人类可读的错误描述
      - original_error: 导致此异常的原始异常（可用于堆栈追踪）
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

    触发条件: asyncio.wait_for() 在配置的超时阈值内未收到 LLM API 响应。
              捕获此异常后 Pipeline 降级为规则引擎结果，不重试。
    诊断字段:
      - timeout_ms: 配置的超时阈值（毫秒）
      - elapsed_ms: 实际耗时（毫秒），None 表示未记录
      - original_error: 原始 TimeoutError（可选）
    """

    def __init__(
        self,
        timeout_ms: int,
        elapsed_ms: int | None = None,
        original_error: Exception | None = None,
    ) -> None:
        message = f"LLM review timed out after {timeout_ms}ms" + (
            f" (elapsed: {elapsed_ms}ms)" if elapsed_ms is not None else ""
        )
        self.timeout_ms = timeout_ms
        self.elapsed_ms = elapsed_ms
        super().__init__(message=message, original_error=original_error)


class KeywordDictLoadError(CrisisJudgmentError):
    """关键词词库加载失败异常。

    触发条件: PostgreSQL 连接失败、crisis_keywords 表不存在、
              查询返回空结果。捕获此异常后 Pipeline 进入降级模式：
              规则引擎层跳过，仅依赖前置选择层 + LLM 复审。
    诊断字段:
      - detail: 失败原因详情（如 "connection refused"、"empty keyword dict"）
      - original_error: 原始数据库异常（可选，用于日志和监控）
    """

    def __init__(
        self,
        detail: str = "",
        original_error: Exception | None = None,
    ) -> None:
        message = f"failed to load keyword dictionary: {detail}" if detail else "failed to load keyword dictionary"
        super().__init__(message=message, original_error=original_error)
