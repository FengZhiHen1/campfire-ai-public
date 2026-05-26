# 1 功能点：OBS-01 结构化日志 — 落地规范

> **文档生成时间**：2026-05-26 17:21:02
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 17:21:02 | AI Assistant | 初始版本，基于设计文档 v1.0 和契约协调报告（s08） |
>
> **配套文档**：本模块的设计思路与决策依据见 `OBS-01-结构化日志-设计文档.md`。
> **契约协调依据**：`.tmp/contract-harmonize-report.json` — 5 个新类型，零冲突，零可复用项。

## 【对内实现】

### 1.1 技术栈绑定

- **必须使用**：
  - Python 标准库 `logging`（日志基础设施），版本随 Python 3.12+
  - Python 标准库 `json`（JSON 序列化），版本随 Python 3.12+
  - Python 标准库 `uuid`（UUID4 trace_id 生成），版本随 Python 3.12+
  - Python 标准库 `contextvars`（trace_id 上下文传播），版本随 Python 3.12+
  - Python 标准库 `datetime`（时间戳生成，含 `timezone.utc`），版本随 Python 3.12+
  - `logging.Formatter` 子类化自定义 `JSONFormatter`，重写 `format(record)` 方法
  - `contextvars.ContextVar[str]` 存储 trace_id，在 FastAPI 中间件中设置，协程间自动隔离
  - 项目结构 §6.1 规定的包目录结构：`packages/py-logger/py_logger/` 含 `core.py`、`context.py`、`middlewares/fastapi.py`
- **禁止使用**：
  - 禁止使用 `structlog`、`python-json-logger` 或任何第三方日志库（MVP 阶段零外部依赖）
  - 禁止使用 `threading.local` 存储 trace_id（asyncio 下存在跨协程串扰风险）
  - 禁止在日志输出阶段使用 `asyncio` 异步 I/O（日志写入必须同步操作）
  - 禁止使用 `orjson`、`ujson` 等第三方 JSON 库（标准库 `json` 满足需求）
  - 禁止日志模块直接写入文件或数据库（stdout 为唯一输出通道）

### 1.2 文件归属

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 模块核心 | `packages/py-logger/py_logger/core.py` | 日志工厂、JSON 格式化器、等级便捷方法（debug/info/warning/error/critical） |
| 上下文管理 | `packages/py-logger/py_logger/context.py` | trace_id ContextVar 定义与 get/set 接口、trace_id 自动补全逻辑 |
| FastAPI 中间件 | `packages/py-logger/py_logger/middlewares/fastapi.py` | `RequestLoggingMiddleware`：自动记录请求 method/path/status_code/duration_ms |
| 测试文件 | `packages/py-logger/tests/test_core.py` | 日志写入、JSON 格式验证、序列化失败降级 |
| 测试文件 | `packages/py-logger/tests/test_context.py` | trace_id 传播、ContextVar 隔离、空值自动补全 |
| 测试文件 | `packages/py-logger/tests/test_middleware.py` | FastAPI 中间件字段完整性、trace_id 注入与提取 |

## 【已锁定】

### 1.3 输入定义（精确类型 / 或契约引用）

**LogLevel**
- 【契约引用】`docs/contracts/OBS-01/LogLevel.json`
- 本模块作为该契约的定义方
- 消费方：暂无（首个模块）

**LogInput**
- 【契约引用】`docs/contracts/OBS-01/LogInput.json`
- 本模块作为该契约的定义方
- 消费方：平台全部后端模块（api-server、worker、各 py-* 包）

**Logger 接口**
- 【契约引用】`docs/contracts/OBS-01/Logger-interface.json`
- 本模块作为该契约的定义方
- 消费方：平台全部后端模块

### 1.4 输出定义（精确类型 / 或契约引用）

**LogEntry**
- 【契约引用】`docs/contracts/OBS-01/LogEntry.json`
- 本模块作为该契约的定义方
- 消费方：Docker 日志驱动（stdout 采集）；OBS-02（指标监控，间接消费）；OBS-03（告警通知，间接消费）

**FastAPIRequestLog**
- 【契约引用】`docs/contracts/OBS-01/FastAPIRequestLog.json`
- 本模块作为该契约的定义方
- 消费方：Docker 日志驱动（stdout 采集）；OBS-02（性能分析，间接消费）

## 【对内实现】

### 1.5 核心逻辑步骤

1. **步骤 1：trace_id 初始化**
   - **操作对象**：`contextvars.ContextVar[str]` 实例 `_trace_id_var`
   - **具体操作**：FastAPI 中间件在请求入口读取 `traceparent` header（W3C Trace Context），提取 `trace_id` 部分；若 header 不存在或解析失败，调用 `uuid.uuid4().hex` 生成新的 trace_id。通过 `_trace_id_var.set(trace_id)` 注入上下文
   - **输入来源**：HTTP 请求头 `traceparent: 00-<trace_id>-<span_id>-<flags>`；或空（生成新 ID）
   - **输出去向**：当前 asyncio Task 及其子协程自动继承此 trace_id
   - **失败行为**：header 解析失败时静默降级为 UUID4 生成新 ID，不抛出异常，不记录警告日志（避免在极早期阶段产生无 trace_id 的日志条目）

2. **步骤 2：日志方法调用**
   - **操作对象**：`core.py` 中的日志方法（`debug`、`info`、`warning`、`error`、`critical`）
   - **具体操作**：调用方传入 level、message、service 及可选的 op_type、extra。方法内部先从 `_trace_id_var` 读取当前 trace_id（若为空则自动补全 UUID4 并在 extra 中追加 `"_trace_missing": true`），再组装 `LogEntry` 字典
   - **输入来源**：调用方传入的 `LogInput` 参数
   - **输出去向**：组装完成的 `LogEntry` 字典进入步骤 3
   - **失败行为**：`critical()` 方法在 op_type 为空或 None 时立即抛出 `ValueError("op_type is required for critical audit log")`，不进入后续步骤

3. **步骤 3：JSON 序列化**
   - **操作对象**：步骤 2 组装的 `LogEntry` 字典
   - **具体操作**：调用 `json.dumps(log_entry, default=_default_handler, ensure_ascii=False)` 序列化。`_default_handler` 对不可序列化对象返回 `f"<{type(obj).__name__}: {repr(obj)[:100]}>"` 占位字符串
   - **输入来源**：步骤 2 的 `LogEntry` 字典
   - **输出去向**：JSON 字符串进入步骤 4
   - **失败行为**：`json.dumps()` 抛出 `TypeError` 或 `ValueError` → 捕获后构造降级日志 `{"timestamp": ..., "severity": "ERROR", "service": service, "trace_id": trace_id, "message": "日志序列化失败，原始数据类型: <type>", "extra": {"_serialize_error": true, "original_keys": [...], "original_types": {...}}}`，降级 JSON 进入步骤 4

4. **步骤 4：stdout 输出**
   - **操作对象**：JSON 字符串
   - **具体操作**：`sys.stdout.write(json_str + "\n")` 写入 stdout，后跟 `sys.stdout.flush()` 确保立即输出
   - **输入来源**：步骤 3 的 JSON 字符串
   - **输出去向**：stdout → 由 Docker 日志驱动采集
   - **失败行为**：stdout 写入失败（`OSError`）→ 检查环形缓冲区剩余空间。若未满，将 JSON 字符串追加到缓冲区（带时间戳和等级）。若缓冲区达到 80% 高水位，触发淘汰：遍历缓冲区，按等级优先保留（ERROR > WARNING > INFO > DEBUG），淘汰低等级条目直到降至 50% 低水位。输出通道恢复后（下次写入成功时），按时间序将缓冲区全部刷出到 stdout。同时在 stderr 输出告警：`print("[py-logger] stdout unavailable, buffering: {} items".format(len(buffer)), file=sys.stderr)`

5. **步骤 5（仅限 FastAPI 中间件）：请求日志自动记录**
   - **操作对象**：FastAPI `Request` 和 `Response` 对象
   - **具体操作**：中间件在请求到达时记录 `start = time.monotonic()`；请求处理完成后计算 `duration_ms = (time.monotonic() - start) * 1000`，构造 `FastAPIRequestLog` 字典，调用步骤 2 的 `info()` 方法写入
   - **输入来源**：`request.method`、`request.url.path`、`response.status_code`、`request.client.host`（client_ip）、`request.state.user_id`（如有认证中间件设置）、异常类型（从 `sys.exc_info()` 提取）
   - **输出去向**：经步骤 3-4 的序列化和 stdout 输出链路
   - **失败行为**：中间件内部任何异常均在第 4 步的异常屏障内处理，不向上传播，不阻塞请求响应

## 【已锁定】

### 1.6 接口契约（对外暴露的公共接口）

本模块对外暴露一个全局单例 `logger` 实例，通过 `from py_logger import logger` 导入。提供 5 个公共方法。

#### 1.6.1 接口 1：debug

```python
def debug(
    service: str,
    message: str,
    op_type: str | None = None,
    extra: dict[str, object] | None = None,
) -> None:
    """
    写入 DEBUG 级别日志。用于开发调试，本地环境默认启用。

    Args:
        service: 来源服务名称，必须为平台已注册的服务名称
        message: 日志消息正文，长度 1-4096 字符
        op_type: 可选，操作类型。DEBUG 日志通常不填
        extra: 可选，结构化补充数据

    Returns:
        None —— 日志写入 stdout 不返回值

    Raises:
        不向上传播异常 —— 任何内部异常在 _write_log() 内捕获

    Side Effects:
        - 写入一行 JSON 到 stdout
        - 若 stdout 不可用，日志进入环形缓冲区

    Thread Safety:
        线程安全。内部通过 contextvars 隔离 trace_id，无共享可变状态。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `debug` —— 对应 DEBUG 日志等级 |
| **输入类型** | `LogInput`（详见 §1.3），`op_type` 和 `extra` 为可选 |
| **输出类型** | 无返回值（输出到 stdout） |
| **异常类型** | 不传播异常（内部捕获） |
| **副作用** | 写入 stdout |
| **幂等性** | 每次调用产生独立的日志条目，非幂等 |
| **并发安全** | 线程安全 |

#### 1.6.2 接口 2：info

```python
def info(
    service: str,
    message: str,
    op_type: str | None = None,
    extra: dict[str, object] | None = None,
) -> None:
    """
    写入 INFO 级别日志。用于正常业务事件（请求开始/完成、用户操作）。

    Args:
        service: 来源服务名称
        message: 日志消息正文，长度 1-4096 字符
        op_type: 可选，操作类型。非关键动作可省略
        extra: 可选，结构化补充数据

    Returns: None
    Raises: 不向上传播异常
    Side Effects: 写入 stdout
    Thread Safety: 线程安全
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `info` —— 对应 INFO 日志等级 |
| **输入类型** | `LogInput`，`op_type` 和 `extra` 为可选 |
| **输出类型** | 无返回值（输出到 stdout） |
| **异常类型** | 不传播异常 |
| **副作用** | 写入 stdout |
| **并发安全** | 线程安全 |

#### 1.6.3 接口 3：warning

```python
def warning(
    service: str,
    message: str,
    op_type: str | None = None,
    extra: dict[str, object] | None = None,
) -> None:
    """
    写入 WARNING 级别日志。用于非错误但需关注的事件（重试发生、降级触发）。

    Args:
        service: 来源服务名称
        message: 日志消息正文，长度 1-4096 字符
        op_type: 可选，操作类型
        extra: 可选，结构化补充数据

    Returns: None
    Raises: 不向上传播异常
    Side Effects: 写入 stdout
    Thread Safety: 线程安全
    """
```

#### 1.6.4 接口 4：error

```python
def error(
    service: str,
    message: str,
    op_type: str | None = None,
    extra: dict[str, object] | None = None,
) -> None:
    """
    写入 ERROR 级别日志。用于业务异常（数据库连接失败、外部 API 调用失败）。

    Args:
        service: 来源服务名称
        message: 日志消息正文，长度 1-4096 字符
        op_type: 可选，操作类型
        extra: 可选，结构化补充数据（如异常堆栈摘要、错误码）

    Returns: None
    Raises: 不向上传播异常
    Side Effects: 写入 stdout；若级别 >= WARNING 且 stdout 不可用，优先保留至缓冲区
    Thread Safety: 线程安全
    """
```

#### 1.6.5 接口 5：critical（审计日志强制方法）

```python
def critical(
    service: str,
    message: str,
    op_type: str,
    extra: dict[str, object] | None = None,
) -> None:
    """
    写入审计日志。用于 AI 调用、权限拒绝、工单创建三个关键动作。

    op_type 为必填参数 —— 调用方不得省略或传入空字符串。
    此方法在接口层面强制审计不可绕过，编译/类型检查即可发现遗漏。

    Args:
        service: 来源服务名称
        message: 日志消息正文
        op_type: 操作类型（必填）。合法值包括 "AI调用"、"权限拒绝"、"工单创建"
        extra: 可选，结构化补充数据

    Returns: None

    Raises:
        ValueError: op_type 为空字符串或仅含空白字符 —— 在日志写入前抛出

    Side Effects: 写入 stdout

    Thread Safety: 线程安全
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `critical` —— 语义化命名，表达"关键动作审计记录"的业务意图 |
| **输入类型** | `LogInput`，但 `op_type` 为必填（`str`，非 `str \| None`） |
| **输出类型** | 无返回值（输出到 stdout） |
| **异常类型** | `ValueError` —— op_type 为空时在调用阶段抛出（不等到序列化阶段） |
| **副作用** | 写入 stdout；op_type 字段必定非空 |
| **幂等性** | 每次调用产生独立的审计记录，非幂等 |
| **并发安全** | 线程安全 |

### 1.7 依赖与集成接口（本模块调用的外部接口）

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 标准输出 | stdout（`sys.stdout.write`） | `sys.stdout.write(json_str + "\n")` 后跟 `sys.stdout.flush()` | 日志 JSON 行输出，供 Docker 日志驱动采集 | `项目结构设计.md §5.1` L3 工程支撑层 Docker 部署 |
| 标准错误 | stderr（`sys.stderr`） | `print(msg, file=sys.stderr)` | 日志模块自身的告警与逃生通道（stdout 不可用时） | 无单独文档依据 —— 标准 Python 进程约定 |
| 配置读取 | `py-config`（可选） | `py_config.get_env("LOG_LEVEL", default="INFO")` | 启动时读取各环境的默认日志级别 | `项目结构设计.md §6.1` `packages/py-config/` |
| 上下文传播 | Python `contextvars` | `ContextVar[str].get()` / `.set()` | trace_id 在 asyncio 协程间自动传播 | Python 3.7+ 标准库，无文档依据 |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| 无 | — | 本模块位于 L2 共享能力层，不依赖 L1 应用层或 L2 其他包 | N/A |

### 1.8 状态机（如适用）

本功能点不涉及状态流转，故无需状态机。结构化日志是无状态管道式处理——日志事件从调用到输出的全流程是瞬时的单向管道。环形缓冲区的淘汰与恢复属于内部实现细节，不构成需要文档化追踪的业务状态机。

### 1.9 异常与边界条件

#### 1.9.1 异常 1：日志序列化失败

- **触发条件**：`json.dumps(log_entry, default=_default_handler)` 抛出 `TypeError` 或 `ValueError`。典型场景包括 `extra` 中包含循环引用对象、`default` handler 自身抛出异常
- **处理策略**：
  1. 在外层 `try/except (TypeError, ValueError)` 中捕获序列化异常
  2. 从原始 `log_entry` 中提取安全可序列化的字段（`timestamp`、`severity`、`service`、`trace_id`、`message`）
  3. 收集 `extra` 中的所有键名（`list(extra.keys())`）和各键对应的值类型（`{k: type(v).__name__ for k, v in extra.items()}`），限制键名列表长度不超过 20 项
  4. 构造降级日志条目，`message` 改为 `"日志序列化失败，原始数据类型见 extra._serialize_error"`，`extra` 改为 `{ "_serialize_error": true, "original_keys": [...], "original_types": {...} }`
  5. 将降级日志 JSON 写入 stdout，不阻塞后续正常日志
  6. 在 stderr 输出一行告警：`print(f"[py-logger] serialization failed for message: {original_message[:200]}", file=sys.stderr)`
- **重试参数**：不重试。序列化失败通常由数据本身问题导致（如循环引用），重试无意义。以降级日志替代。

#### 1.9.2 异常 2：stdout 输出通道阻塞或不可用

- **触发条件**：`sys.stdout.write()` 抛出 `OSError` 或 `BrokenPipeError`；或系统级 stdout 管道缓冲区满导致写入阻塞超过容忍时间（非阻塞式检查，通过 `flush()` 异常判断）
- **处理策略**：
  1. 捕获 `OSError` 和 `BrokenPipeError`
  2. 检查环形缓冲区当前条目数。环形缓冲区使用 `collections.deque` 实现，最大容量 `MAX_BUFFER_SIZE = 5000`
  3. 若当前条目数 < `MAX_BUFFER_SIZE`：将 `(timestamp, severity, json_str)` 元组追加到缓冲区尾部
  4. 若当前条目数 >= `MAX_BUFFER_SIZE * 0.8`（4000 条，高水位）：触发等级淘汰
     - 遍历缓冲区，构建按 severity 分组的计数
     - 优先淘汰 DEBUG 级别（全部清除），若不足以降至低水位则继续淘汰 INFO 级别
     - 淘汰策略：从缓冲区头部开始扫描，删除匹配级别的条目，直至条目数降至 `MAX_BUFFER_SIZE * 0.5`（2500 条，低水位）
     - 每淘汰一条，在 stderr 输出：`print(f"[py-logger] buffer evicted DEBUG entry at {timestamp}", file=sys.stderr)`
  5. 同时输出 stderr 告警（仅首次进入缓冲模式时）：`print("[py-logger] stdout unavailable, buffering logs. current buffer: {} items".format(current_count), file=sys.stderr)`
  6. 后续某次 `sys.stdout.write()` 成功时（判断 `flush()` 无异常），按时间序将缓冲区全部条目依次写入 stdout：`for _, _, json_str in sorted(buffer): sys.stdout.write(json_str + "\n")`，写入完成后清空缓冲区
  7. 输出 stderr 恢复通知：`print("[py-logger] stdout recovered, flushed {} buffered logs".format(count), file=sys.stderr)`
- **重试参数**：不重试。以本地缓冲 + 等级优先淘汰替代重试，确保不阻塞主业务流程。

#### 1.9.3 异常 3：trace_id 缺失

- **触发条件**：调用方在请求处理流程的极早期阶段（trace_id 尚未由中间件设置）调用日志方法；或 `contextvars` 跨 Task 传播失败导致 `_trace_id_var.get()` 返回默认值空字符串 `""` 或 `None`
- **处理策略**：
  1. 在 `core.py` 的 `_build_entry()` 中检测 `trace_id = _trace_id_var.get("")` 的值
  2. 若 `not trace_id`（空字符串或 None）：调用 `uuid.uuid4().hex` 生成本地 trace_id（32 位十六进制）
  3. 在 `extra` dict 中注入标记字段 `"_trace_missing": true`
  4. 使用生成的本地 trace_id 继续组装日志条目，正常输出
  5. 不在 stderr 输出告警（避免在极早期阶段产生无 trace_id 的告警日志），标记字段供后续日志分析时识别
- **重试参数**：不重试。自动补全 trace_id 是瞬时的降级策略，不影响日志输出。

#### 1.9.4 边界条件：op_type 对非关键动作的约束

- **触发条件**：调用 `info()`、`warning()`、`error()` 时传入 `op_type`；或调用 `critical()` 时未传入 `op_type`
- **处理策略**：
  1. `debug()`、`info()`、`warning()`、`error()` 允许 `op_type=None`（可选参数），默认值为 `None`
  2. `critical()` 的 `op_type` 参数无默认值（`op_type: str`，必填），调用方未传入时 Python 解释器在调用阶段即抛出 `TypeError`
  3. `critical()` 在函数体内增加二次校验：`if not op_type or not op_type.strip(): raise ValueError("op_type is required for critical audit log")`——防止调用方传入空字符串绕过
  4. 所有 `critical()` 产出的日志条目中 `op_type` 字段必定非空
- **重试参数**：不重试。参数校验失败直接抛出异常，要求调用方修正代码。

### 1.10 验收测试场景

#### 1.10.1 正向测试 1：基本日志写入与 JSON 格式验证

- **场景**：调用 `info()` 方法写入一条普通日志，验证输出为合法 JSON 且包含所有标准字段
- **Given**: trace_id 已由中间件设置为 `"a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"`，调用 `logger.info(service="api-server", message="用户登录成功")`
- **When**: 日志模块执行完整的构建-序列化-输出流程
- **Then**:
  - stdout 输出一行合法的 JSON 字符串
  - JSON 包含且仅包含标准字段：`timestamp`、`severity`、`service`、`trace_id`、`message`
  - `severity` = `"INFO"`
  - `trace_id` = `"a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"`
  - `op_type` = `null`，`extra` = `null`
  - 不抛出任何异常
- **完整 JSON 示例**：
```json
{"timestamp": "2026-05-26T17:21:02.000Z", "severity": "INFO", "service": "api-server", "trace_id": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6", "message": "用户登录成功", "op_type": null, "extra": null}
```

#### 1.10.2 正向测试 2：审计日志 mandatory_op_type

- **场景**：调用 `critical()` 方法写入审计日志，验证 op_type 必填且正确记录
- **Given**: trace_id = `"b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6a1"`，调用 `logger.critical(service="api-server", message="AI 大模型调用完成", op_type="AI调用", extra={"model": "deepseek-chat", "tokens": 1500})`
- **When**: 日志模块执行完整的构建-序列化-输出流程
- **Then**:
  - stdout 输出合法 JSON
  - `severity` = `"INFO"`（critical 仍使用 INFO 级别输出，但接口层面强制 op_type）
  - `op_type` = `"AI调用"`（非 null）
  - `extra` 包含 `{"model": "deepseek-chat", "tokens": 1500}`
  - 不抛出异常
- **完整 JSON 示例**：
```json
{"timestamp": "2026-05-26T17:21:02.100Z", "severity": "INFO", "service": "api-server", "trace_id": "b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6a1", "message": "AI 大模型调用完成", "op_type": "AI调用", "extra": {"model": "deepseek-chat", "tokens": 1500}}
```

#### 1.10.3 正向测试 3：trace_id 缺失自动补全

- **场景**：在未设置 trace_id 的上下文中调用日志方法，验证自动生成本地 trace_id 且附带缺失标记
- **Given**: ContextVar `_trace_id_var` 未设置（默认值 `""`），调用 `logger.info(service="worker", message="后台任务开始")`
- **When**: 日志模块检测到 trace_id 为空，自动调用 `uuid4().hex` 生成
- **Then**:
  - stdout 输出合法 JSON
  - `trace_id` 为 32 字符十六进制字符串，格式匹配 `^[a-f0-9]{32}$`
  - `extra` 包含 `"_trace_missing": true`
  - 不抛出异常
- **完整 JSON 示例**：
```json
{"timestamp": "2026-05-26T17:21:02.200Z", "severity": "INFO", "service": "worker", "trace_id": "e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2", "message": "后台任务开始", "op_type": null, "extra": {"_trace_missing": true}}
```

#### 1.10.4 异常测试 1：critical() 缺少 op_type 抛出 ValueError

- **场景**：调用 `critical()` 方法时未传入 `op_type` 参数
- **Given**: trace_id 已设置，调用 `logger.critical(service="api-server", message="工单创建")`——缺少 op_type
- **When**: Python 解释器执行函数调用
- **Then**:
  - `critical()` 内二次校验触发，抛出 `ValueError("op_type is required for critical audit log")`
  - 无日志写入 stdout
  - 调用方代码必须捕获此异常或修正调用

#### 1.10.5 异常测试 2：JSON 序列化失败降级

- **场景**：extra 中包含不可 JSON 序列化的对象（如包含循环引用的自定义类实例）
- **Given**: trace_id 已设置，构造一个包含循环引用的对象 `circular = {}; circular["self"] = circular`，调用 `logger.info(service="test", message="测试序列化", extra={"bad": circular})`
- **When**: `json.dumps()` 抛出 `ValueError: Circular reference detected`
- **Then**:
  - 不抛出异常到调用方
  - stdout 输出降级日志 JSON
  - 降级日志 `severity` = `"ERROR"`，`message` 包含"日志序列化失败"
  - `extra` 包含 `"_serialize_error": true` 和 `"original_keys": ["bad"]`、`"original_types": {"bad": "dict"}`
  - stderr 输出一行告警（格式：`[py-logger] serialization failed for message: 测试序列化`）
- **完整 JSON 示例（降级日志）**：
```json
{"timestamp": "2026-05-26T17:21:02.300Z", "severity": "ERROR", "service": "test", "trace_id": "e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2", "message": "日志序列化失败，原始数据类型见 extra._serialize_error", "op_type": null, "extra": {"_serialize_error": true, "original_keys": ["bad"], "original_types": {"bad": "dict"}}}
```

#### 1.10.6 异常测试 3：stdout 不可用时缓冲与恢复

- **场景**：模拟 stdout 写入失败（如管道断开），验证日志被缓冲、等级淘汰生效、恢复后刷出
- **Given**: trace_id 已设置，stdout 被 mock 为在 5 次写入中抛出 `BrokenPipeError`，调用 `logger.error(service="api-server", message="数据库连接失败")` 3 次
- **When**: 日志模块检测到写入失败，启用环形缓冲区
- **Then**:
  - 前 3 条 ERROR 日志均进入缓冲区
  - 缓冲区内条目数 = 3
  - stderr 输出缓冲告警（仅首次）
  - 当 stdout 恢复时（第 6 次写入成功），缓冲区中的 3 条日志按时间序全部刷出到 stdout
  - stderr 输出恢复通知，含刷出条目数
  - 调用方代码不收到任何异常

### 1.11 注意事项与禁止行为（编码层面）

1. **[约束：异常必须在外层捕获]** `core.py` 中 `_write_log()` 的最外层必须包裹 `try/except Exception`，任何内部异常不得向上传播到调用方。测试时必须覆盖此约束——mock stdout 抛出异常，断言调用方不收到异常。
2. **[约束：JSON 必须为单行]** `json.dumps()` 不得使用 `indent` 参数。每条日志必须是恰好一行 JSON，末尾紧跟 `\n`。多行 JSON 在 Docker 日志驱动中会被拆分为多条独立记录。
3. **[约束：时间戳使用 UTC]** 所有日志的时间戳 `timestamp` 必须使用 UTC 时区：`datetime.now(timezone.utc).isoformat(timespec="milliseconds") + "Z"`。禁止使用本地时区。
4. **[易错点：ContextVar 默认值]** `_trace_id_var = ContextVar("trace_id", default="")` 的默认值必须为空字符串 `""`，禁止使用 `None`——`contextvars.get()` 在 set 前返回默认值，空字符串方便用 `if not trace_id` 统一判断空值。
5. **[易错点：跨 Task 传播]** `asyncio.create_task()` 创建的 Task 默认继承当前 ContextVar 的值——这是正确行为。但需在 `context.py` 的文档字符串中明确说明此行为，避免开发者误以为需要手动复制。
6. **[禁止行为]** 禁止在日志方法内部使用 `await` 或任何异步操作。日志写入必须是同步的，原因：(a) Docker 日志驱动的 stdout 采集是同步管道，异步写入无性能收益；(b) 异步 I/O 在 asyncio 事件循环中可能被其他协程抢占，导致日志输出乱序。
7. **[禁止行为]** 禁止调用方直接使用 `_build_entry()` 或 `_write_log()` 等私有方法。公共接口仅限 `debug()`、`info()`、`warning()`、`error()`、`critical()` 五个方法。私有方法签名变更不视为 breaking change。
8. **[禁止行为]** 禁止在日志中硬编码 `service` 字段。`service` 必须由调用方传入，以保持模块的跨服务通用性。每个服务在初始化时通过环境变量或配置设置自身的 service 名称。

### 1.12 文档详细度自检清单

- [x] 文档自包含：一位不了解本项目代码的 Agent，仅凭此文档即可完成编码
- [x] 无偷懒表述：全文已消除 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`
- [x] 类型定义完整：每个 JSON Schema 字段都有 `description` + `examples` + 约束（`minLength`/`maxLength`/`enum`/`pattern` 等）
- [x] 逻辑步骤完整：5 个步骤每个都有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：4 种异常/边界条件每种都有精确的触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有默认值来源（如缓冲区 5000 条、高水位 80%、低水位 50%）、条件分支（如等级淘汰顺序）、业务规则都已显式写出
- [x] 技术栈绑定明确：必须使用（Python 标准库 json/logging/uuid/contextvars/datetime）和禁止使用（structlog/python-json-logger 等）均已列出
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致（详见 §1.15）

### 1.14 外部接口契约清单

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| LogLevel | `docs/contracts/OBS-01/LogLevel.json` | shared-enum | draft | OBS-01 | — |
| LogInput | `docs/contracts/OBS-01/LogInput.json` | input | draft | OBS-01 | — |
| LogEntry | `docs/contracts/OBS-01/LogEntry.json` | output | draft | OBS-01 | — |
| FastAPIRequestLog | `docs/contracts/OBS-01/FastAPIRequestLog.json` | output | draft | OBS-01 | — |
| Logger | `docs/contracts/OBS-01/Logger-interface.json` | shared-model | draft | OBS-01 | — |

### 1.15 意图一致性声明

- **配套意图文档**：`OBS-01-结构化日志-意图文档.md`
- **冻结时间**：2026-05-26 16:54:47
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档中的业务字段定义一致（LogInput §1.6.1 输入定义 → 落地规范 §1.3；LogEntry §1.6.2 输出定义 → 落地规范 §1.4）
  - [x] 本落地规范中的状态机实现与意图文档中的状态业务定义一致（双方均为"无状态管道式处理"）
  - [x] 本落地规范中的异常处理策略与意图文档中的异常业务策略一致（序列化失败 §1.9.1 → 意图 §1.8.1；输出通道阻塞 §1.9.2 → 意图 §1.8.2；trace_id 缺失 §1.9.3 → 意图 §1.8.3）
  - [x] 本落地规范中的验收测试场景覆盖意图文档中的所有验收标准（AC-01 日志格式统一 → 正向测试 1；AC-02 trace_id 贯穿 → 正向测试 1+3；AC-03 审计日志不可省略 → 正向测试 2 + 异常测试 1；AC-04 输出通道不阻塞业务 → 异常测试 3；AC-05 检索可用性 → 由部署环境验证，不在此落地规范范围内）
  - [x] 本落地规范中的技术实现未超出意图文档中"留给规范阶段的技术决策"的范围（6 项决策已全部在落地规范中明确技术选型）
- **偏差说明**：无偏差，技术实现与意图文档完全一致。
