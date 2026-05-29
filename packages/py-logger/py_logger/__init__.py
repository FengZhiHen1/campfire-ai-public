"""py-logger: Campfire-AI 结构化日志模块。

通过 ``from py_logger import logger`` 导入全局单例 logger 实例，
调用 logger.debug() / info() / warning() / error() / critical() 写入日志。

架构：
- logger_contract.py: BaseStructuredLogger ABC（契约骨架）
- context_contract.py: BaseTraceContext ABC（trace_id 管理契约）
- core.py: StructuredLogger（实现 BaseStructuredLogger 契约）
- context.py: TraceContext（实现 BaseTraceContext 契约）
- types.py: 语义类型（LogSeverity, TraceId, ServiceName）
- middlewares/fastapi.py: RequestLoggingMiddleware

上下文管理：
    from py_logger import get_trace_id, set_trace_id

中间件：
    from py_logger.middlewares.fastapi import RequestLoggingMiddleware

Zero external dependencies —— 仅使用 Python 3.12 标准库。
"""

from py_logger.context import TraceContext, get_trace_id, set_trace_id
from py_logger.context_contract import BaseTraceContext
from py_logger.core import JSONFormatter, StructuredLogger, logger, setup_logging
from py_logger.logger_contract import BaseStructuredLogger
from py_logger.types import LogSeverity, ServiceName, TraceId

__all__ = [
    # 全局单例
    "logger",
    # 核心类
    "StructuredLogger",
    "JSONFormatter",
    "TraceContext",
    # 契约
    "BaseStructuredLogger",
    "BaseTraceContext",
    # 语义类型
    "LogSeverity",
    "TraceId",
    "ServiceName",
    # 便捷函数
    "get_trace_id",
    "set_trace_id",
    "setup_logging",
]
