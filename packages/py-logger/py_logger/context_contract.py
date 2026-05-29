# @contract
"""OBS-01 结构化日志 — Trace ID 上下文管理契约（ABC）。

定义 trace_id 的获取和设置接口。
实现者通过 contextvars.ContextVar 在 asyncio 协程间自动传播。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from py_logger.types import TraceId


class BaseTraceContext(ABC):
    """Trace ID 上下文管理契约。

    定义 trace_id 的 get/set 接口。
    实现者负责选择底层传播机制（contextvars / threading.local / 显式传递）。

    关键行为约束：
    - get_trace_id() 在未设置时应返回空字符串 ""（非 None），
      以便调用方用 `if not trace_id` 统一判断空值。
    - set_trace_id() 设置的值应在当前 asyncio Task 及其子协程中自动继承。
    """

    @abstractmethod
    def get_trace_id(self) -> TraceId:
        """获取当前上下文的 trace_id。

        Returns:
            TraceId: 当前 trace_id；若从未设置则返回空字符串 ""。
        """
        ...

    @abstractmethod
    def set_trace_id(self, trace_id: TraceId) -> None:
        """设置当前上下文的 trace_id。

        设置后，当前 asyncio Task 及其子协程自动继承该值。

        Args:
            trace_id: 要设置的 trace_id（32 位十六进制字符串）。
        """
        ...
