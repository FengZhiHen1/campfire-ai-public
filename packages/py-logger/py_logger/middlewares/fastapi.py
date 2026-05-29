"""
FastAPI 请求日志中间件。

ASGI 中间件，在请求到达时解析 W3C traceparent header 设置 trace_id，
请求处理完成后自动记录 method / path / status_code / duration_ms
等关键字段的结构化日志。

W3C Trace Context: traceparent = "00-<trace_id>-<span_id>-<flags>"
- trace_id: 32 位十六进制（提取后通过 set_trace_id 注入上下文）
- span_id: 16 位十六进制（当前不使用）
- flags: 2 位十六进制（当前不使用）

若 traceparent 缺失或格式异常，静默降级为 UUID4 生成新 trace_id。
"""

from __future__ import annotations

import sys
import time
import uuid
from typing import Any, Awaitable, Callable

from ..context import set_trace_id
from ..core import logger
from ..types import ServiceName, TraceId


# W3C traceparent 格式: version-trace_id-span_id-flags
_TRACEPARENT_PATTERN_LENGTH = 4
_TRACEPARENT_TRACE_ID_INDEX = 1
_TRACEPARENT_TRACE_ID_LENGTH = 32


def _parse_traceparent(header_value: str) -> str | None:
    """
    从 W3C traceparent header 值中提取 trace_id。

    Args:
        header_value: traceparent header 原始值。

    Returns:
        提取的 32 位十六进制 trace_id；若格式不合法则返回 None。
    """
    parts = header_value.strip().split("-")
    if len(parts) != _TRACEPARENT_PATTERN_LENGTH:
        return None
    trace_id = parts[_TRACEPARENT_TRACE_ID_INDEX]
    if len(trace_id) != _TRACEPARENT_TRACE_ID_LENGTH:
        return None
    # 校验是否为 32 位十六进制字符串
    try:
        int(trace_id, 16)
    except ValueError:
        return None
    return trace_id


class RequestLoggingMiddleware:
    """
    FastAPI ASGI 请求日志中间件。

    功能：
    1. 请求到达时从 traceparent header 提取/生成 trace_id 并注入上下文
    2. 请求完成后自动记录 method / path / status_code / duration_ms
    3. 可选记录 client_ip / user_id / error_type

    使用方式：
        from py_logger.middlewares.fastapi import RequestLoggingMiddleware
        app.add_middleware(RequestLoggingMiddleware)
    """

    def __init__(
        self,
        app: Callable[[dict[str, Any], Callable[[], Awaitable[dict[str, Any]]], Callable[[dict[str, Any]], Awaitable[None]]], Awaitable[None]],
        service_name: str = "api-server",
    ) -> None:
        self.app = app
        self._service_name: ServiceName = ServiceName(service_name)

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        # 仅处理 HTTP 请求
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        start = time.monotonic()

        # 设置 trace_id
        self._setup_trace_id(scope)

        # 收集响应信息（通过包装 send）
        response_status: int = 0
        error_type: str | None = None

        async def _send_wrapper(message: dict[str, Any]) -> None:
            nonlocal response_status, error_type
            if message.get("type") == "http.response.start":
                response_status = message.get("status", 0)
            elif message.get("type") == "http.response.body":
                # 检查是否有异常通过 scope 传递
                pass
            await send(message)

        try:
            await self.app(scope, receive, _send_wrapper)
        except Exception:
            error_type = sys.exc_info()[1].__class__.__name__ if sys.exc_info()[1] else None
            raise
        finally:
            duration_ms = (time.monotonic() - start) * 1000

            try:
                self._log_request(scope, response_status, duration_ms, error_type)
            except Exception:
                # 中间件内部日志异常不阻塞请求
                pass

    def _setup_trace_id(self, scope: dict[str, Any]) -> None:
        """
        从 scope 的 headers 中解析 traceparent 并设置 trace_id。

        解析失败或 header 缺失时静默降级为 UUID4 生成新 trace_id，
        不记录警告日志（避免在极早期阶段产生无 trace_id 的日志条目）。

        Args:
            scope: ASGI scope dict，包含 headers 列表。
        """
        trace_id: str | None = None

        # 查找 traceparent header
        headers = scope.get("headers", [])
        for key_bytes, value_bytes in headers:
            if key_bytes.lower() == b"traceparent":
                trace_id = _parse_traceparent(value_bytes.decode("ascii", errors="replace"))
                break

        # 降级：生成新 trace_id
        if trace_id is None:
            trace_id = uuid.uuid4().hex

        set_trace_id(TraceId(trace_id))

    def _log_request(
        self,
        scope: dict[str, Any],
        status_code: int,
        duration_ms: float,
        error_type: str | None,
    ) -> None:
        """
        构造请求日志并写入。

        Args:
            scope: ASGI scope dict。
            status_code: HTTP 响应状态码。
            duration_ms: 请求耗时（毫秒）。
            error_type: 异常类型名称（无异常时为 None）。
        """
        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")

        # 提取 client_ip
        client_ip: str | None = None
        client_info = scope.get("client")
        if client_info:
            client_ip = client_info[0]

        # 提取 user_id（来自 scope["state"] 或 headers，取决于认证中间件实现）
        user_id: str | None = None

        # 构造请求日志消息
        message = f"{method} {path} {status_code} {duration_ms:.1f}ms"

        # 组装 extra 字段
        extra: dict[str, object] = {
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 2),
        }
        if client_ip is not None:
            extra["client_ip"] = client_ip
        if user_id is not None:
            extra["user_id"] = user_id
        if error_type is not None:
            extra["error_type"] = error_type

        service = self._service_name

        logger.info(service=service, message=message, extra=extra)
