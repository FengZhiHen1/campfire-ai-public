"""CSLT-03 应急方案生成 — 异常定义。

异常层级（所有异常均遵循项目统一异常体系规范，通过 status_code 属性
供 FastAPI 全局异常处理器映射为 HTTP 状态码）：
    GenerationInputError      — 输入校验失败 (422)
    LLMUnavailableError       — LLM API 不可用 (503)
    GenerationTimeoutError    — 全流程超时 (504)
"""

from __future__ import annotations


class GenerationInputError(Exception):
    """输入校验失败异常。

    当 EmergencyPlanInput 的 Pydantic 校验失败时抛出。
    调用方应返回 HTTP 422，detail 含字段名和失败原因。
    不进入 Prompt 构建和 LLM 调用。

    Attributes:
        detail: 包含字段名和失败信息的字典。
        message: 通用异常描述。
        original_error: 原始 Pydantic ValidationError（如有）。
    """

    status_code: int = 422

    def __init__(
        self,
        detail: dict | None = None,
        message: str = "输入数据校验失败",
        original_error: Exception | None = None,
    ) -> None:
        self.detail = detail
        self.message = message
        self.original_error = original_error
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.original_error:
            return f"{self.message} (caused by: {self.original_error})"
        return self.message


class LLMUnavailableError(Exception):
    """LLM API 不可用异常。

    当 LLMClient.async_chat_stream() 抛出 HTTP 非 200 状态码或连接超时时抛出。
    调用方应返回 HTTP 503。
    不重试 —— 单次调用失败即终止，由上游 CSLT-08 决定是否让用户重试。

    Attributes:
        detail: 用户友好的错误信息。
        original_error: 原始 LLMClientError（如有）。
    """

    status_code: int = 503

    def __init__(
        self,
        detail: str = "LLM 生成服务暂时不可用，请稍后重试",
        original_error: Exception | None = None,
    ) -> None:
        self.detail = detail
        self.original_error = original_error
        super().__init__(detail)

    def __str__(self) -> str:
        if self.original_error:
            return f"{self.detail} (caused by: {self.original_error})"
        return self.detail


class GenerationTimeoutError(Exception):
    """生成全流程超时异常。

    当 asyncio.wait_for() 在 GENERATION_TIMEOUT_S 内未完成且无任何文本产出时抛出。
    调用方应返回 HTTP 504。
    超时场景下若已有部分文本（至少一个完整段落），不抛出此异常，改为返回 PARTIAL 结果。

    Attributes:
        detail: 用户友好的错误信息。
        elapsed_ms: 超时时已耗时（毫秒）。
        accumulated_text: 超时时已积累的文本（可能为空）。
    """

    status_code: int = 504

    def __init__(
        self,
        detail: str = "应急方案生成超时，请稍后重试（30秒冷却期）",
        elapsed_ms: float | None = None,
        accumulated_text: str = "",
    ) -> None:
        self.detail = detail
        self.elapsed_ms = elapsed_ms
        self.accumulated_text = accumulated_text
        super().__init__(detail)

    def __str__(self) -> str:
        if self.elapsed_ms is not None:
            return f"{self.detail} (elapsed: {self.elapsed_ms:.0f}ms)"
        return self.detail


__all__ = [
    "GenerationInputError",
    "LLMUnavailableError",
    "GenerationTimeoutError",
]
