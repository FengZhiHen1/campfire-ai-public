"""
py-logger: Campfire-AI 结构化日志模块。

通过 ``from py_logger import logger`` 导入全局单例 logger 实例，
调用 logger.debug() / info() / warning() / error() / critical() 写入日志。

上下文管理：
    from py_logger import get_trace_id, set_trace_id

中间件：
    from py_logger.middlewares.fastapi import RequestLoggingMiddleware

Zero external dependencies —— 仅使用 Python 3.12 标准库。
"""

from .context import get_trace_id, set_trace_id
from .core import JSONFormatter, logger

__all__ = [
    "logger",
    "get_trace_id",
    "set_trace_id",
    "JSONFormatter",
]
