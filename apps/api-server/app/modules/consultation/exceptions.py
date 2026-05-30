"""consultation 异常层次 — 统一错误类型定义。

模块: app.modules.consultation.exceptions
职责: 定义咨询域所有异常的统一层次结构。所有异常继承自 ConsultationError 基类，
      上层可通过 `except ConsultationError` 统一捕获本域的所有错误。
      每个异常携带诊断字段，供调用方做程序化处理。
数据来源:
  - 无外部数据来源（纯异常定义层）
边界:
  - 依赖: Python 标准库
  - 被依赖: consultation 模块内所有子域、FastAPI 全局异常处理器
禁止行为:
  - 禁止异常只携带 message 字符串——所有异常必须携带诊断字段
  - 禁止在异常类中执行任何 I/O 或业务逻辑
  - 禁止跨域混用异常（如 consultation 抛 cases 域的异常）
"""

from __future__ import annotations

from typing import Any


class ConsultationError(Exception):
    """咨询域统一异常基类。

    触发条件: 咨询流程中任何可恢复或不可恢复的错误。
    诊断字段:
      - message: 人类可读的错误描述
      - detail: 结构化的错误详情（供 API 响应使用）
    """

    def __init__(self, message: str = "咨询处理异常", detail: dict[str, Any] | None = None) -> None:
        self.message = message
        self.detail = detail or {}
        super().__init__(self.message)


# ============================================================================
# 输入校验异常
# ============================================================================


class ConsultationInputError(ConsultationError):
    """输入校验失败异常。

    触发条件: 请求参数缺失、类型错误、值域不合法。
    调用方应返回 HTTP 422。
    诊断字段:
      - field: 校验失败的字段名
      - received: 实际接收到的值
    """

    status_code: int = 422

    def __init__(
        self,
        message: str = "输入数据校验失败",
        field: str | None = None,
        received: str | None = None,
    ) -> None:
        self.field = field
        self.received = received
        detail: dict[str, Any] = {}
        if field:
            detail["field"] = field
        if received:
            detail["received"] = received
        super().__init__(message, detail)


# ============================================================================
# 检索异常
# ============================================================================


class ConsultationSearchError(ConsultationError):
    """语义检索失败异常。

    触发条件: 检索引擎不可用（嵌入 API 不可达、数据库连接失败）。
    调用方应返回 HTTP 503。
    诊断字段:
      - reason: 检索失败原因标签（embedding_unavailable / db_connection_failed）
      - request_id: 关联的请求追踪 ID
    """

    status_code: int = 503

    def __init__(
        self,
        message: str = "语义检索服务暂时不可用",
        reason: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.reason = reason
        self.request_id = request_id
        detail: dict[str, Any] = {}
        if reason:
            detail["reason"] = reason
        if request_id:
            detail["request_id"] = request_id
        super().__init__(message, detail)


# ============================================================================
# 生成异常
# ============================================================================


class ConsultationGenerationError(ConsultationError):
    """应急方案生成失败异常。

    触发条件: LLM API 不可用、全流程超时且无部分产出。
    诊断字段:
      - finish_reason: 生成结束原因（timeout / error）
      - elapsed_ms: 失败时已耗时
      - accumulated_text: 已积累的部分文本（可能为空）
    """

    status_code: int = 503

    def __init__(
        self,
        message: str = "应急方案生成失败",
        finish_reason: str | None = None,
        elapsed_ms: float | None = None,
        accumulated_text: str = "",
    ) -> None:
        self.finish_reason = finish_reason
        self.elapsed_ms = elapsed_ms
        self.accumulated_text = accumulated_text
        detail: dict[str, Any] = {}
        if finish_reason:
            detail["finish_reason"] = finish_reason
        if elapsed_ms is not None:
            detail["elapsed_ms"] = elapsed_ms
        super().__init__(message, detail)


# ============================================================================
# 归档异常
# ============================================================================


class ConsultationArchiveError(ConsultationError):
    """咨询归档失败异常。

    触发条件: disclaimer 等值校验失败、必填字段缺失、数据库写入异常。
    调用方应返回 HTTP 422。
    诊断字段:
      - field: 校验失败的字段名
      - reason: 拒绝原因描述
    """

    status_code: int = 422

    def __init__(
        self,
        message: str = "咨询归档数据不完整",
        field: str | None = None,
        reason: str | None = None,
    ) -> None:
        self.field = field
        self.reason = reason
        detail: dict[str, Any] = {}
        if field:
            detail["field"] = field
        if reason:
            detail["reason"] = reason
        super().__init__(message, detail)


# ============================================================================
# 记录不存在异常
# ============================================================================


class ConsultationNotFoundError(ConsultationError):
    """咨询记录不存在或无权访问异常。

    触发条件: 按 id + user_id 联合查询无结果。
    调用方应返回 HTTP 404，且不区分「不存在」和「无权访问」（保护用户隐私）。
    诊断字段:
      - consultation_id: 查询的咨询记录 ID
      - actual_reason: 真实拒绝原因（仅记录日志，不返回给客户端）
    """

    status_code: int = 404

    def __init__(
        self,
        message: str = "该咨询记录不存在或无权查看",
        consultation_id: str | None = None,
        actual_reason: str | None = None,
    ) -> None:
        self.consultation_id = consultation_id
        self.actual_reason = actual_reason
        detail: dict[str, Any] = {}
        if actual_reason:
            detail["actual_reason"] = actual_reason
        super().__init__(message, detail)


# ============================================================================
# 流式推送异常
# ============================================================================


class ConsultationStreamError(ConsultationError):
    """SSE 流式推送异常。

    触发条件: session_id 格式非法、未找到 Generator、并发连接数超限。
    诊断字段:
      - session_id: 关联的 SSE 会话标识
      - reason: 拒绝原因标签
    """

    status_code: int = 400

    def __init__(
        self,
        message: str = "流式推送异常",
        session_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.reason = reason
        detail: dict[str, Any] = {}
        if session_id:
            detail["session_id"] = session_id
        if reason:
            detail["reason"] = reason
        super().__init__(message, detail)


__all__ = [
    "ConsultationError",
    "ConsultationInputError",
    "ConsultationSearchError",
    "ConsultationGenerationError",
    "ConsultationArchiveError",
    "ConsultationNotFoundError",
    "ConsultationStreamError",
]
