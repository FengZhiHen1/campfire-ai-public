"""
Trace ID 上下文管理模块。

通过 `contextvars.ContextVar` 在 asyncio 协程间自动传播 trace_id，
每个协程自动隔离，无需调用方手动传递。

关键行为：
- 默认值为空字符串 ""，禁止使用 None（方便用 `if not trace_id` 统一判断空值）
- asyncio.create_task() 创建的 Task 默认继承当前 ContextVar 值
- 跨 Task 传播时，若需要独立 trace_id，调用方需显式调用 set_trace_id()
"""

from contextvars import ContextVar

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def get_trace_id() -> str:
    """
    获取当前上下文的 trace_id。

    Returns:
        str: 当前 trace_id；若从未设置则返回空字符串 ""（ContextVar 默认值）。
    """
    return _trace_id_var.get()


def set_trace_id(trace_id: str) -> None:
    """
    设置当前上下文的 trace_id。

    通常在请求入口（FastAPI 中间件）或消息消费入口（Worker）调用。
    设置后，当前 asyncio Task 及其子协程自动继承该值。

    Args:
        trace_id: 要设置的 trace_id（32 位十六进制字符串，如 uuid4().hex）。
    """
    _trace_id_var.set(trace_id)
