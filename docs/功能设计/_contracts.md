# 模块接口契约索引

## OBS-01 - 结构化日志
- **输入**: `LogInput {level: LogLevel, message: str, service: str, op_type: str|null, extra: dict|null}`
- **输出**: `LogEntry {timestamp: str, severity: LogLevel, service: str, trace_id: str, message: str, op_type: str|null, extra: dict|null}`
- **输出（中间件）**: `FastAPIRequestLog` 继承 `LogEntry` + `{method, path, status_code, duration_ms, client_ip, user_id, error_type}`
- **状态机**: 无（无状态管道式处理）
- **模块依赖**: 无（L2 共享能力层，被全平台后端引用）
- **外部依赖**: Docker 日志驱动（stdout），Python 标准库 json
- **技术栈**: Python 标准库 logging + 自定义 JSONFormatter，uuid4，contextvars
- **契约文件**: `docs/contracts/OBS-01/LogLevel.json`, `docs/contracts/OBS-01/LogInput.json`, `docs/contracts/OBS-01/LogEntry.json`, `docs/contracts/OBS-01/FastAPIRequestLog.json`, `docs/contracts/OBS-01/Logger-interface.json`
- **更新时间**: 2026-05-26 17:21:02
