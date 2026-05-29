"""py-logger 语法契约 — 语义类型与数据结构定义。

通过 NewType 防止日志严重等级、trace_id、服务名等语义类型
在类型检查期被混淆。
"""

from typing import Literal, NewType

# === 语义类型 ===

LogSeverity = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
"""日志严重等级。CRITICAL 为审计日志专用等级。"""

TraceId = NewType("TraceId", str)
"""32 位十六进制追踪标识，贯穿一次请求全生命周期。"""

ServiceName = NewType("ServiceName", str)
"""产生日志的服务模块名称。"""
