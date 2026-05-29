# @contract
"""OBS-01 Trace ID 上下文管理 — TraceContext 实现。

通过 contextvars.ContextVar 在 asyncio 协程间自动传播 trace_id。
实现 BaseTraceContext 契约。

关键行为：
- 默认值为空字符串 ""，禁止使用 None（方便用 `if not trace_id` 统一判断空值）
- asyncio.create_task() 创建的 Task 默认继承当前 ContextVar 值
- 跨 Task 传播时，若需要独立 trace_id，调用方需显式调用 set_trace_id()
"""

from __future__ import annotations

from contextvars import ContextVar

from py_logger.context_contract import BaseTraceContext
from py_logger.types import TraceId

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


class TraceContext(BaseTraceContext):
    """基于 contextvars 的 trace_id 上下文管理实现。

    asyncio 原生支持 contextvars，每个协程自动隔离，
    无需额外依赖。

    通过全局单例 _trace_context 提供模块级访问。
    """

    def get_trace_id(self) -> TraceId:
        """获取当前上下文的 trace_id。

        Returns:
            TraceId: 当前 trace_id；若从未设置则返回空字符串 ""。
        """
        return TraceId(_trace_id_var.get())

    def set_trace_id(self, trace_id: TraceId) -> None:
        """设置当前上下文的 trace_id。

        Args:
            trace_id: 要设置的 trace_id（32 位十六进制字符串）。
        """
        _trace_id_var.set(trace_id)


# 模块级单例
_trace_context = TraceContext()

# 便捷函数（保持向后兼容）


def get_trace_id() -> TraceId:
    """获取当前上下文的 trace_id。"""
    return _trace_context.get_trace_id()


def set_trace_id(trace_id: TraceId) -> None:
    """设置当前上下文的 trace_id。"""
    _trace_context.set_trace_id(trace_id)
