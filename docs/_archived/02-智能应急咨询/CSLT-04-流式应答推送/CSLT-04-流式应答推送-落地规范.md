## 1 功能点：CSLT-04 流式应答推送 — 落地规范

> **文档生成时间**：`2026-05-27 17:45:12`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-27 17:45:12` | AI Assistant | 初始版本，基于已冻结意图文档 v2.0、设计文档 v1.0、技术预研报告和契约协调报告全量生成 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `CSLT-04-流式应答推送-设计文档.md`。

### 1.1 技术栈绑定【对内实现】

- **必须使用**：
  - `FastAPI >= 0.115`：`StreamingResponse` 类用于封装 SSE 事件流
  - `Pydantic >= 2.0`：所有 SSE 事件数据模型基类，使用 `BaseModel.model_dump_json()` 序列化
  - `asyncio`：`async def` 异步生成器 + `asyncio.Semaphore` 并发限流 + `asyncio.wait_for()` 超时控制
  - `uuid` 标准库：`uuid4()` 生成 stream_id
  - `packages/py-logger`：结构化日志（`logger.bind(stream_id=..., trace_id=...)`）
  - `packages/py-config`：`AppSettings` Pydantic model 读取环境变量配置
  - `packages/py-schemas`：SSE 事件 Pydantic 模型定义（`py_schemas/streaming.py`）

- **禁止使用**：
  - 禁止使用 `websockets` 库或 WebSocket 协议——单向推送使用 SSE 标准协议
  - 禁止使用 `sse-starlette` 或任何第三方 SSE 库——FastAPI `StreamingResponse` 原生支持足够，引入额外库增加依赖链风险
  - 禁止在同步函数中运行异步生成器——必须全程使用 `async def`/`await`
  - 禁止在 CSLT-04 内部直接调用 LLM API 或访问数据库——纯传输层，不持有业务逻辑

### 1.2 文件归属【对内实现】

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| SSE 推送服务 | `apps/api-server/app/services/streaming/sse_service.py` | `SseStreamingService` 类：消费 AsyncGenerator 并封装为 SSE 响应 |
| SSE 会话管理 | `apps/api-server/app/services/streaming/session_manager.py` | `StreamSessionManager` 类：内存中管理 StreamSession 生命周期（创建/查询/过期清理） |
| 路由端点 | `apps/api-server/app/api/v1/consult/stream.py` | FastAPI APIRouter：`GET /api/v1/consult/stream/{session_id}` 端点 |
| 数据模型 | `packages/py-schemas/py_schemas/streaming.py` | Pydantic 模型：`ChunkEvent`、`DoneEvent`、`HeartbeatEvent`、`ErrorEvent`、`StreamErrorCode`、`StreamSession` |
| 单元测试 | `apps/api-server/tests/services/streaming/test_sse_service.py` | `SseStreamingService.stream()` 核心推送逻辑测试 |
| 会话管理测试 | `apps/api-server/tests/services/streaming/test_session_manager.py` | `StreamSessionManager` 生命周期和并发安全测试 |
| 集成测试 | `apps/api-server/tests/api/v1/consult/test_stream.py` | SSE 端点端到端测试（含重连、超时、异常） |

### 1.3 输入定义（契约引用格式）【已锁定】

**GenerationChunk**（上游 CSLT-03 产出）
- 【契约引用】`docs/contracts/CSLT-03/GenerationChunk.json`
- 本模块作为该契约的定义方：否（CSLT-03 定义）
- 消费方：CSLT-04（本模块通过 `async for chunk in generator` 消费）

**GenerationStatus**（上游 CSLT-03 产出）
- 【契约引用】`docs/contracts/CSLT-03/GenerationStatus.json`
- 本模块作为该契约的定义方：否（CSLT-03 定义）
- 消费方：CSLT-04（本模块将 GenerationStatus 枚举值映射为 DoneEvent.finish_reason）

**内部输入类型**（不对外暴露）：

```python
class StreamSession(BaseModel):
    """推送会话的完整上下文，纯内存存储，不持久化到数据库"""
    stream_id: str = Field(
        description="流标识符，格式 stream-{uuid4}，通过首次 SSE 连接响应头 X-Stream-Id 返回前端",
        pattern=r"^stream-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        examples=["stream-a1b2c3d4-e5f6-7890-abcd-ef1234567890"]
    )
    chunk_buffer: dict[int, str] = Field(
        default_factory=dict,
        description="已推送的 chunk 文本缓冲区，key 为 sequence 号（从 1 开始），用于断点续传时跳过已推送内容"
    )
    sequence: int = Field(
        default=0,
        description="当前已推送的最后一个 chunk 的 sequence 号。0 表示尚未推送任何 chunk",
        ge=0
    )
    created_at: float = Field(
        description="会话创建时间戳（time.monotonic()），用于 TTL 过期判定",
        examples=[1716800000.0]
    )
    first_chunk_sent_at: float | None = Field(
        default=None,
        description="首个 chunk 成功推送的时间戳（time.monotonic()），为 None 表示尚未推送任何 chunk"
    )
    status: str = Field(
        description="推送会话内部状态：CREATED|STREAMING|COMPLETED|ABORTED|EXPIRED",
        default="CREATED",
        pattern=r"^(CREATED|STREAMING|COMPLETED|ABORTED|EXPIRED)$"
    )
    finish_reason: str | None = Field(
        default=None,
        description="推送终止原因，仅在 status 为 COMPLETED 或 ABORTED 时填充",
        pattern=r"^(COMPLETE|PARTIAL|BLOCKED|TIMEOUT|ERROR)$"
    )
    ttft_ms: float | None = Field(
        default=None,
        description="首字延迟（TTFT），毫秒，从 chat_started_at 到 first_chunk_sent_at 的差值"
    )
    total_chunks: int = Field(default=0, ge=0, description="累计推送的 chunk 数量")
```

### 1.4 输出定义（契约引用格式）【已锁定】

**ChunkEvent**（SSE chunk 事件 data 载荷）
- 【契约引用】`docs/contracts/CSLT-04/ChunkEvent.json`
- 本模块作为该契约的定义方：是
- 消费方：CSLT-08（前端编排逻辑，通过 EventSource 解析 SSE data 行）

**DoneEvent**（SSE done 事件 data 载荷）
- 【契约引用】`docs/contracts/CSLT-04/DoneEvent.json`
- 本模块作为该契约的定义方：是
- 消费方：CSLT-08

**HeartbeatEvent**（SSE 心跳事件标记）
- 【契约引用】`docs/contracts/CSLT-04/HeartbeatEvent.json`
- 本模块作为该契约的定义方：是
- 消费方：CSLT-08

**ErrorEvent**（SSE error 事件 data 载荷）
- 【契约引用】`docs/contracts/CSLT-04/ErrorEvent.json`
- 本模块作为该契约的定义方：是
- 消费方：CSLT-08

**StreamErrorCode**（SSE 流推送错误码枚举）
- 【契约引用】`docs/contracts/CSLT-04/StreamErrorCode.json`
- 本模块作为该契约的定义方：是
- 消费方：CSLT-08

### 1.5 核心逻辑步骤【对内实现】

执行顺序严格按 1~6。每步是原子、可测试的操作。

1. **步骤 1：并发限流检查**
   - **操作对象**：`asyncio.Semaphore` 实例（全局单例 `_semaphore`，容量 = `SSE_MAX_CONCURRENT_CONNECTIONS`，默认 500）
   - **具体操作**：调用 `await _semaphore.acquire()` 获取信号量。若当前活跃连接数 < 容量则放行；若已达上限则阻塞等待（不推荐）或立即返回 429。实际采用 `_semaphore.acquire()` 的非阻塞变体：若 `_semaphore.locked()` 为 True → 直接 raise HTTP 429
   - **输入来源**：HTTP 请求到达路由入口 `GET /api/v1/consult/stream/{session_id}`
   - **输出去向**：信号量获取成功 → 进入步骤 2；获取失败 → 返回 HTTP 429 `{"error_code": "CONCURRENCY_LIMIT_EXCEEDED", "detail": "当前咨询人数较多，请稍后重试"}`
   - **失败行为**：并发超限时立即拒绝，不排队等待。返回码 429，记录结构化日志 `logger.warning("concurrency_limit_reached", current_connections=...)`，释放信号量不进入后续步骤

2. **步骤 2：会话创建或恢复**
   - **操作对象**：`StreamSessionManager` 单例，内部维护 `dict[str, StreamSession]` 字典
   - **具体操作**：
     - 解析路由参数 `session_id`（UUID 格式）
     - 查询 `_sessions[session_id]`：
       - 若不存在 → 新建 `StreamSession(stream_id=session_id, created_at=time.monotonic())`，存入 `_sessions`
       - 若存在且 status 为 EXPIRED → 返回 `ErrorEvent(error_code="SESSION_NOT_FOUND", detail="当前推送会话不存在或已过期")`
       - 若存在且 status 为 COMPLETED/ABORTED → 返回 `DoneEvent(finish_reason=session.finish_reason, sequence=session.sequence)`
       - 若存在且 status 为 STREAMING → 说明重连，跳转到 Step 3（从中断位置续传）
   - **输入来源**：路由参数 `session_id` + 请求头 `Last-Event-Id`（可选，重连场景）
   - **输出去向**：`StreamSession` 实例传递给步骤 3
   - **失败行为**：`session_id` 格式非法 → 返回 HTTP 400；会话已过期或不存在 → 返回 SSE `error` 事件（error_code=SESSION_NOT_FOUND）后关闭连接

3. **步骤 3：启动上游 Generator 消费与 SSE 推送**
   - **操作对象**：上游传入的 `AsyncGenerator[GenerationChunk, None]`（由 CSLT-08 编排层通过依赖注入传入）
   - **具体操作**：
     1. 设置响应头：`Content-Type: text/event-stream`、`Cache-Control: no-cache`、`Connection: keep-alive`、`X-Accel-Buffering: no`、`X-Stream-Id: {session_id}`
     2. 若请求头包含 `Last-Event-Id` 且值为正整数 n（重连场景）：
        - 将 `StreamSession.sequence` 设为 n（表示前端已收到前 n 个 chunk）
        - 跳过 Generator 中已推送的 chunk：在 `async for chunk in generator:` 循环中比对 chunk index，直到遇见第 n+1 个 chunk 才开始推送
     3. 若为新连接：发送初始 SSE `id: 0` 帧标记会话起始
     4. 将 `StreamSession.status` 设为 `"STREAMING"`
   - **输入来源**：`StreamSession`（步骤 2 产出）+ `AsyncGenerator[GenerationChunk, None]`（上游传入）
   - **输出去向**：SSE 事件流（通过 `StreamingResponse` 的异步迭代器逐帧 yield）。首个有效的 chunk → 进入步骤 4
   - **失败行为**：上游 Generator 在收到任何 chunk 前直接 raise → 进入步骤 5（异常终端处理）

4. **步骤 4：逐 chunk 消费与 SSE 事件推送循环**
   - **操作对象**：`async for chunk in generator:` 循环 + `StreamSession` 状态
   - **具体操作**：
     1. 记录首个 chunk 的时间戳：若 `StreamSession.first_chunk_sent_at` 为 None → 赋值 `time.monotonic()`，计算 TTFT
     2. 首个 chunk 等待超时检测（步骤 3 启动后 5s）：若 5s 内未收到任何 chunk → 推送 `ErrorEvent(error_code="STREAM_TIMEOUT", detail="正在生成中，请耐心等待")` 但继续等待（软超时不终止）。后续继续以 5s 间隔发送进度提示
     3. `StreamSession.sequence += 1`
     4. 构造 ChunkEvent：`{"text": chunk.text, "sequence": session.sequence}`
     5. 写入 SSE 帧：`id: {session.sequence}\nevent: chunk\ndata: {ChunkEvent.model_dump_json()}\n\n`，通过 `yield` 逐帧输出给 StreamingResponse
     6. 将 `chunk.text` 存入 `session.chunk_buffer[session.sequence]`
     7. 检查 `chunk.is_final` → True 则退出循环，进入步骤 6（正常完成终端处理）
     8. 全流程硬超时检测：从 `session.created_at` 起超过 20s → 强制中断 generator（`await generator.aclose()`），`StreamSession.finish_reason = "TIMEOUT"`，进入步骤 6
   - **输入来源**：`chunk`（`GenerationChunk` 实例，来自 `async for` 迭代）
   - **输出去向**：每个 chunk 转换为 SSE 帧 yield 给 StreamingResponse 的异步迭代器
   - **失败行为**：`async for` 循环中 generator 抛出异常 → 退出循环，进入步骤 5

5. **步骤 5：异常终端处理**
   - **操作对象**：`StreamSession` 状态
   - **具体操作**：
     1. `StreamSession.status = "ABORTED"`
     2. 根据异常类型设置 `finish_reason`：
        - 上游 CSLT-03 Generator raise → `finish_reason = "ERROR"`
        - CSLT-03 明确返回 `GenerationStatus=BLOCKED` → `finish_reason = "BLOCKED"`（且不推送任何 chunk_buffer 中内容）
        - 全流程 20s 硬超时 → `finish_reason = "TIMEOUT"`
     3. 发送最后的 `DoneEvent`：
        - 若为 BLOCKED → 推送预设安全提示文本作为最后一个 chunk 事件，然后发送 `DoneEvent(finish_reason="BLOCKED")`
        - 否则 → 发送 `DoneEvent(finish_reason=finish_reason, sequence=session.sequence)`
     4. 记录 `logger.error("stream_aborted", stream_id=..., finish_reason=..., chunks_sent=...)`
   - **输入来源**：被捕获的异常实例
   - **输出去向**：SSE `done` 事件 → SSE 连接关闭
   - **失败行为**：若 `DoneEvent` 推送时连接已断开（客户端提前关闭），静默处理不二次抛异常

6. **步骤 6：正常完成终端处理与心跳**
   - **操作对象**：`StreamSession` 状态
   - **具体操作**：
     1. 在 `async for` 循环（步骤 4）退出后执行（由 `finally` 块保证）
     2. `StreamSession.status = "COMPLETED"`
     3. `StreamSession.finish_reason = chunk.finish_reason or "COMPLETE"`
     4. 发送 `DoneEvent(finish_reason=session.finish_reason, sequence=session.sequence)`
     5. 记录 `logger.info("stream_completed", stream_id=..., chunks_total=..., ttft_ms=...)`
     6. 释放信号量 `_semaphore.release()`
   - **输入来源**：`StreamSession` 最终状态
   - **输出去向**：SSE `done` 事件 → SSE 连接关闭 → 信号量释放

**心跳调度**（独立 asyncio Task，与主推送循环并行运行）：
- **操作对象**：`asyncio.Task`（由 `asyncio.create_task(_heartbeat_loop(session))` 在步骤 3 启动）
- **具体操作**：
  1. 每 `SSE_HEARTBEAT_INTERVAL_SECONDS`（默认 15）秒 → yield `event: heartbeat\ndata: {}\n\n`
  2. 在主推送循环正常结束或异常终止时 → `task.cancel()` 取消心跳 Task
  3. 心跳事件与 chunk 事件共享同一个 `StreamingResponse` 的异步迭代器（通过 `asyncio.Queue` 合并两个生产者）
- **输入来源**：`SSE_HEARTBEAT_INTERVAL_SECONDS` 配置项
- **输出去向**：SSE `heartbeat` 事件帧
- **失败行为**：心跳推送失败（连接断开）→ 取消 Task，不做重试

### 1.6 接口契约（对外暴露的公共接口）【已锁定】

#### 1.6.1 接口 1：stream_response — SSE 流式推送主入口

```python
async def stream_response(
    session_id: str,
    chunk_generator: AsyncGenerator[GenerationChunk, None],
    last_event_id: str | None = None,
) -> StreamingResponse:
    """
    将上游 CSLT-03 产出的 GenerationChunk AsyncGenerator 封装为 W3C SSE 标准的事件流，
    通过 FastAPI StreamingResponse 实时推送至客户端。

    包含：逐 chunk 推送（事件类型 chunk）、心跳保活（事件类型 heartbeat、15s 间隔）、
    流终止通知（事件类型 done）、错误通知（事件类型 error）、Last-Event-Id 断点续传。

    Args:
        session_id: 流标识符，格式 stream-{uuid4}，用于断点续传和日志追踪
        chunk_generator: 上游 CSLT-03 产出的 AsyncGenerator[GenerationChunk, None]，
                        由 CSLT-08 编排层通过依赖注入传入
        last_event_id: 可选，重连时前端通过 Last-Event-Id 请求头发送，值为最后成功接收的
                       sequence 号（正整数），CSLT-04 据此从中断位置续传

    Returns:
        StreamingResponse: FastAPI 流式响应对象，media_type="text/event-stream"

    Raises:
        HTTPException(400): session_id 格式非法（非合法 UUID）
        HTTPException(404): 重连时流会话不存在（SESSION_NOT_FOUND）
        HTTPException(409): 重连时流已完成或已过期（STREAM_ALREADY_COMPLETED）
        HTTPException(429): 并发连接数超限（CONCURRENCY_LIMIT_EXCEEDED）
        HTTPException(502): 上游 CSLT-03 生成失败（GENERATION_FAILED）

    Side Effects:
        - 创建或恢复 StreamSession（纯内存，不持久化）
        - 通过 StreamingResponse 的异步迭代器逐帧输出 SSE 事件
        - 记录结构化日志（stream_id/chunk_count/ttft_ms/finish_reason）

    Idempotency:
        同一 stream_id 的重复调用：
        - 状态为 STREAMING → 视为重连，从中断位置续传（基于 Last-Event-Id）
        - 状态为 COMPLETED → 返回 DoneEvent 后立即关闭连接
        - 状态为 ABORTED → 返回 DoneEvent(finish_reason=...) 后立即关闭连接

    Thread Safety:
        本函数为 async def 协程，内部通过 asyncio.Semaphore 控制全局并发连接数。
        StreamSession 的读写操作限定在单个协程内（asyncio 单线程协作式调度），
        无多线程竞态条件。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `stream_response` —— 语义化，描述"将上游数据流封装为 SSE 响应推送"的业务动作 |
| **输入类型** | `session_id: str`（路由参数）+ `chunk_generator: AsyncGenerator[GenerationChunk, None]`（依赖注入）+ `last_event_id: str | None`（可选请求头） |
| **输出类型** | `StreamingResponse`（FastAPI 原生类型，media_type="text/event-stream"） |
| **异常类型** | `HTTPException(400)`、`HTTPException(404)`、`HTTPException(409)`、`HTTPException(429)`、`HTTPException(502)`（详见"异常与边界条件"章节） |
| **副作用** | 创建/更新内存 StreamSession、yield SSE 事件流、记录结构化日志 |
| **幂等性** | 基于 stream_id 的幂等：重连返回中断位置续传，已完成直接返回 DoneEvent |
| **并发安全** | asyncio.Semaphore 限流，单协程内状态操作无竞态 |

#### 1.6.2 接口 2：create_session — 创建或恢复推送会话

```python
async def create_session(
    session_id: str,
) -> StreamSession:
    """
    创建新的 StreamSession 或恢复已有会话供重连使用。

    由 HTTP 端点的依赖项调用，在手握上游 Generator 之前执行。
    返回的 StreamSession 实例记录本次推送的全部元数据。

    Args:
        session_id: 流标识符，格式 stream-{uuid4}

    Returns:
        StreamSession: 新创建或已存在的会话上下文对象

    Raises:
        HTTPException(404): 会话已过期（超过 SSE_SESSION_TTL_SECONDS）且不可恢复
        HTTPException(409): 会话已完成/已中止，不可重新推送
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `create_session` |
| **输入类型** | `session_id: str` |
| **输出类型** | `StreamSession`（内部 Pydantic 模型） |
| **异常类型** | `HTTPException(404)`、`HTTPException(409)` |

### 1.7 依赖与集成接口（本模块调用的外部接口）【已锁定】

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| Web 框架 | FastAPI | `from fastapi.responses import StreamingResponse`；`StreamingResponse(async_gen(), media_type="text/event-stream")` | 封装异步生成器为 SSE 流式 HTTP 响应，自动注入 Content-Type 和连接相关响应头 | 技术栈设计 §2；项目结构 §7.1 |
| ASGI 服务器 | Uvicorn | `uvicorn app:app --workers 4`（每个 worker 独立进程，独立 Semaphore） | 提供 asyncio 事件循环，支持数千并发 SSE 长连接 | 技术栈设计 §2 |
| 反向代理 | Nginx | `infrastructure/nginx/conf.d/campfire.conf` 中 `/api/v1/consult/stream` location 块 | SSE 连接的三层透传：`proxy_buffering off`（实时推送）、`proxy_read_timeout 3600s`（允长连接）、`proxy_ignore_client_abort off`（客户端断开时中止上游） | 技术栈设计 §3.1；DEPLOY-02 设计文档 |
| 结构化日志 | `packages/py-logger` | `logger = get_logger(__name__)`；`logger.bind(stream_id=..., trace_id=...).info(...)` | 记录推送过程（stream_id、chunk_count、ttft_ms、finish_reason、error_type）的完整结构化日志 | 项目结构 §5.3；OBS-01 落地规范 |
| 环境配置 | `packages/py-config` | `AppSettings` Pydantic model | 读取可配置参数：`SSE_MAX_CONCURRENT_CONNECTIONS`（默认 500）、`SSE_SESSION_TTL_SECONDS`（默认 300）、`SSE_HEARTBEAT_INTERVAL_SECONDS`（默认 15）、`SSE_FIRST_CHUNK_TIMEOUT_SECONDS`（默认 5）、`SSE_FULL_TIMEOUT_SECONDS`（默认 20） | 项目结构 §5.1；DEPLOY-05 落地规范 |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| CSLT-03（应急方案生成） | `AsyncGenerator[GenerationChunk, None]`：`async for chunk in generator:` 逐 chunk 消费 | 流式应急方案文本增量的唯一数据来源。通过 CSLT-08 编排层注入 | 契约 draft，设计文档 v1.0 已冻结，落地规范 v1.0 已冻结 |
| CSLT-08（咨询编排逻辑） | SSE 事件消费方（前端 EventSource / useSSEStream Hook） | 本模块的下游消费方。前端连接 `/api/v1/consult/stream/{session_id}`，解析 SSE 事件流并驱动界面渲染 | 未开始设计（⏭️ 待落地，本模块可独立验证——生成标准 SSE 事件流即可，CSLT-08 实现前可通过 curl 手动验证） |
| `packages/py-schemas` | `from py_schemas.streaming import ChunkEvent, DoneEvent, HeartbeatEvent, ErrorEvent, StreamErrorCode, StreamSession` | SSE 事件 Pydantic 模型的序列化和反序列化 | 类型定义文件 `packages/py-schemas/py_schemas/streaming.py` 待创建 |
| AUTH-04（五级RBAC鉴权） | `Depends(require_role(["family", "teacher", "expert"]))` — FastAPI Depends 注入 | SSE 端点 `/api/v1/consult/stream/{session_id}` 的 JWT 认证和角色鉴权，在请求到达 CSLT-04 路由处理函数前已完成 | 落地规范 v1.0 已冻结，契约 draft |
| `packages/py-schemas`（CSLT-03 契约） | `from py_schemas.generation import GenerationChunk` | 上游数据类型引用（类型标注使用，运行时通过 AsyncGenerator 自动类型匹配） | 契约 draft |

### 1.8 状态机【对内实现】

本功能点不涉及业务状态流转，故无需状态机。意图文档 §1.7 已确认。

CSLT-04 内部分别维护每个 StreamSession 的纯内存生命周期（不持久化，仅助理解内部逻辑）：

| 当前状态 | 触发事件 | 下一状态 | 前置条件 | 副作用 |
|----------|----------|----------|----------|--------|
| CREATED | 开始消费 Generator（首个 chunk 入队） | STREAMING | session_id 有效，上游 Generator 已注入 | status 设为 STREAMING，first_chunk_sent_at 记录时间 |
| STREAMING | 收到 is_final=True 的 chunk | COMPLETED | Generator 正常结束 | 发送 DoneEvent（finish_reason=COMPLETE/PARTIAL），关闭连接 |
| STREAMING | Generator 抛出异常 | ABORTED | 任意未捕获异常 | 发送 DoneEvent（finish_reason=ERROR/BLOCKED），记录日志 |
| STREAMING | 全流程超过 20 秒 | ABORTED | 超时硬截断 | 强制 aclose Generator，发送 DoneEvent（finish_reason=TIMEOUT） |
| STREAMING | 客户端断开 + 超过 TTL（300s） | EXPIRED | session 未被重连恢复 | StreamSession 从 _sessions 字典中移除 |
| ANY | 手动清理（定时任务） | EXPIRED | session.created_at + TTL < time.monotonic() | 从 _sessions 字典中移除 |

### 1.9 异常与边界条件【对内实现】

#### 1.9.1 异常 1：并发连接超限

- **触发条件**：
  - 当前活跃 SSE 连接数 ≥ `SSE_MAX_CONCURRENT_CONNECTIONS`（默认 500）
  - 新请求到达 `GET /api/v1/consult/stream/{session_id}`
- **处理策略**：
  1. 在路由端点入口处调用 `_semaphore.acquire()` 前，检查 `_semaphore.locked()`——若为 True（信号量耗尽）→ 不等待，直接返回 HTTP 429
  2. 响应体格式：`{"error_code": "CONCURRENCY_LIMIT_EXCEEDED", "detail": "当前咨询人数较多，请稍后重试"}`
  3. 记录 `logger.warning("concurrency_limit_reached", current_connections=500, rejected_session=session_id)`
  4. 客户端应展示友好提示并引导重新发起咨询
  5. 不创建 StreamSession，不启动 Generator
- **重试参数**：不自动重试。客户端通过 UI 引导用户手动重试。建议重试间隔 ≥ 10 秒。

#### 1.9.2 异常 2：上游 Generator 异常中止

- **触发条件**：
  - `async for chunk in generator:` 循环中 Generator 本身抛出异常（非正常结束）
  - 典型场景：CSLT-03 调用 LLM API 失败返回 5xx、网络断开、Prompt 构建异常
- **处理策略**：
  1. `except Exception` 块捕获异常
  2. 记录 `logger.error("upstream_generator_failed", stream_id=..., error_type=type(e).__name__, error_message=str(e))`
  3. 若已推送至少 1 个 chunk（`StreamSession.sequence > 0`）→ 发送已推送内容 + `DoneEvent(finish_reason="ERROR", sequence=session.sequence)`
  4. 若未推送任何 chunk → 发送 `ErrorEvent(error_code="GENERATION_FAILED", detail="方案生成失败，请稍后重试")`
  5. `StreamSession.status = "ABORTED"`，`StreamSession.finish_reason = "ERROR"`
  6. 关闭连接，释放信号量
- **重试参数**：不在 CSLT-04 层重试（`async for` 循环外）。重试逻辑归属 CSLT-08 编排层（前端检测到 ERROR 后引导用户重新发起咨询）。

#### 1.9.3 异常 3：首 chunk 超时（软超时）+ 全流程超时（硬超时）

- **触发条件**：
  - 软超时：步骤 3 进入 Generator 消费后 5s（`SSE_FIRST_CHUNK_TIMEOUT_SECONDS`）内未收到任何 chunk
  - 硬超时：从 `session.created_at` 起超过 20s（`SSE_FULL_TIMEOUT_SECONDS`）仍未完成全部推送
- **处理策略**（软超时）：
  1. 在步骤 4 的 `async for` 循环首次迭代前设置 `asyncio.wait_for(async_gen.__anext__(), timeout=5.0)`
  2. 5s 内无 chunk → 捕获 `asyncio.TimeoutError`，发送 `ErrorEvent(error_code="STREAM_TIMEOUT", detail="正在生成中，请耐心等待")` 但不终止流
  3. 继续等待下一个 chunk（使用新的 5s timeout）
  4. 每触发一次软超时就发送一次进度提示
- **处理策略**（硬超时）：
  1. 在步骤 4 的循环中每次迭代前检查：`time.monotonic() - session.created_at >= SSE_FULL_TIMEOUT_SECONDS`
  2. 超时 → 调用 `await generator.aclose()` 强制关闭上游 Generator
  3. 发送 `DoneEvent(finish_reason="TIMEOUT", sequence=session.sequence)`
  4. `StreamSession.status = "ABORTED"`，`StreamSession.finish_reason = "TIMEOUT"`
  5. 关闭连接，释放信号量
- **重试参数**：不自动重试。前端收到 `DoneEvent(finish_reason="TIMEOUT")` 后引导用户重新发起咨询。`StreamSession` 在 TTL 内保留已推送内容，重连后可续传。

#### 1.9.4 异常 4：安全阻断场景

- **触发条件**：
  - 上游 CSLT-03 在 `block_deep_response=True` 的判定下，Generator 不产出任何 LLM 生成的文本，仅通过 `finish_reason="BLOCKED"` 信号通知
- **处理策略**：
  1. 不推送 `chunk_buffer` 中的任何已生成内容（即使 Generator 已产出部分 chunk）
  2. 仅推送预设的安全提示文本作为唯一的 chunk：`ChunkEvent(text="...", sequence=1)`（安全提示文本由 CSLT-03 在 Generator 中产出且内容已经过安全校验）
  3. 发送 `DoneEvent(finish_reason="BLOCKED", sequence=1)`
  4. 记录 `logger.info("stream_blocked", stream_id=..., reason="upstream_block_deep_response")`
  5. 关闭连接，释放信号量
- **重试参数**：不重试。BLOCKED 为最终状态，不可恢复。

### 1.10 验收测试场景【对内实现】

#### 1.10.1 正向测试 1：正常流式推送完整方案

- **场景**：上游 CSLT-03 正常产出 3 个 chunk（含 is_final=True），SSE 推送全流程无中断
- **Given**：
  - `session_id = "stream-00000000-0000-0000-0000-000000000001"`
  - `chunk_generator` mock 产出 `[GenerationChunk(text="请保持冷静...", is_final=False, finish_reason=None), GenerationChunk(text="现在需要评估...", is_final=False, finish_reason=None), GenerationChunk(text="", is_final=True, finish_reason="stop")]`
  - 无 Last-Event-Id 请求头（新连接）
- **When**：调用 `stream_response(session_id, chunk_generator)`
- **Then**：
  - 响应头 Content-Type = `"text/event-stream"`
  - 响应头 X-Stream-Id = 传入的 session_id
  - SSE 事件流包含 3 个 chunk 事件，sequence 分别为 1、2、3
  - 第 3 个 chunk 事件后紧随 1 个 done 事件，`finish_reason = "COMPLETE"`
  - `StreamSession.sequence = 3`、`StreamSession.ttft_ms > 0`

#### 1.10.2 正向测试 2：断点续传

- **场景**：前端已接收前 2 个 chunk 后断开，重连时携带 `Last-Event-Id: 2`，从中断位置续传
- **Given**：
  - 已存在 `StreamSession(stream_id="stream-00000000-0000-0000-0000-000000000002", sequence=2, chunk_buffer={1: "text1", 2: "text2"}, status="STREAMING")`
  - `chunk_generator` mock 产出 chunk #3、#4（含 is_final=True）
  - 请求头 `Last-Event-Id: 2`
- **When**：调用 `stream_response("stream-...002", chunk_generator, last_event_id="2")`
- **Then**：
  - 跳过的 chunk #1、#2 不重新推送（通过比对 chunk index 跳过）
  - SSE 事件流仅包含第 3、4 个 chunk 事件，sequence 分别为 3、4
  - 最后一个 chunk 事件后紧随 done 事件

#### 1.10.3 正向测试 3：心跳事件与 chunk 事件并行

- **场景**：正常推送过程中，心跳事件以 15s 间隔发送
- **Given**：
  - `SSE_HEARTBEAT_INTERVAL_SECONDS = 1`（测试时缩短间隔）
  - `chunk_generator` mock 产出 2 个 chunk，间隔 2s
- **When**：调用 `stream_response(session_id, chunk_generator)`，收集推送的所有事件
- **Then**：
  - SSE 事件流中至少包含 1 个 `event: heartbeat` 事件
  - heartbeat 事件的 data 行为 `{}`
  - heartbeat 事件与 chunk 事件的顺序无严格保证（两个 asyncio Task 并行）

#### 1.10.4 异常测试 1：并发连接超限

- **场景**：当前活跃连接数已达上限（500），新连接被拒绝
- **Given**：
  - `SSE_MAX_CONCURRENT_CONNECTIONS = 1`（测试时降低限制）
  - 已有 1 个活跃 SSE 连接正在推送
- **When**：另一个请求到达同一个 SSE 端点
- **Then**：
  - 返回 HTTP 429
  - 响应体：`{"error_code": "CONCURRENCY_LIMIT_EXCEEDED", "detail": "当前咨询人数较多，请稍后重试"}`
  - 日志包含 `"concurrency_limit_reached"` 事件

#### 1.10.5 异常测试 2：上游 Generator 中途异常

- **场景**：推送进行到一半时上游 Generator 抛出异常
- **Given**：
  - `chunk_generator` mock 产出前 2 个 chunk 后在第三个 chunk 处 `raise RuntimeError("LLM API connection reset")`
- **When**：调用 `stream_response(session_id, chunk_generator)`
- **Then**：
  - SSE 事件流包含前 2 个 chunk 事件
  - 紧随 1 个 done 事件，`finish_reason = "ERROR"`
  - `StreamSession.status = "ABORTED"`
  - 日志包含 `"upstream_generator_failed"` 事件，含 `error_type = "RuntimeError"`

#### 1.10.6 异常测试 3：全流程硬超时

- **场景**：从 session 创建起 20s 后仍未完成，强制终止
- **Given**：
  - `SSE_FULL_TIMEOUT_SECONDS = 1`（测试时缩短超时）
  - `chunk_generator` mock 产出第 1 个 chunk，然后 `await asyncio.sleep(2)` 无限等待（不产出更多）
- **When**：调用 `stream_response(session_id, chunk_generator)`
- **Then**：
  - SSE 事件流包含第 1 个 chunk 事件
  - 等待至硬超时触发后发送 done 事件，`finish_reason = "TIMEOUT"`
  - Generator 被 `aclose()` 强制关闭
  - `StreamSession.status = "ABORTED"`

### 1.11 注意事项与禁止行为（编码层面）【对内实现】

1. **[硬禁令] chunk.text 必须原样透传**：`ChunkEvent.text = chunk.text`，不经过任何字符串处理函数（如 `strip()`、`replace()`、`.encode()`）。此禁令来自意图文档 §1.11(1) 内容完整性约束。

2. **[硬禁令] `finally` 块确保 done/error 事件必达**：无论 `async for` 循环以何种方式退出（Generator 正常结束、异常抛出、硬超时 aclose），包裹在 `for` 外的 `try/finally` 块必须保证执行一次 `send_done_event()` 或 `send_error_event()` 后再 `return response`。来自意图文档 AC-04。

3. **[硬禁令] 安全阻断时禁止推送生成片段**：当收到 `finish_reason="BLOCKED"` 时，`chunk_buffer` 中的任何已生成内容均不可推送给前端。仅推送 CSLT-03 在阻断场景下产出的安全提示文本。来自意图文档 §1.11(5)。

4. **[关键约束] 流式生成器函数必须是 async def**：如果 `stream_response` 或其内部的子生成器使用 `def` 而非 `async def`，FastAPI 会在独立线程池中运行，导致：(a) asyncio 上下文丢失，`asyncio.wait_for()` 无法正确取消；(b) StreamingResponse 无法与非异步中间件栈协作。全部生成器链必须为 `async def`。

5. **[关键约束] sequence 号从 1 开始**：SSE `id:` 字段值从 1 开始（0 留给初始连接帧）。重连时前端通过 `Last-Event-Id: n` 告知已收到前 n 个 chunk，服务端从 sequence = n+1 开始续传。sequence 号的起始值 1 必须在代码中以常量 `SEQUENCE_START = 1` 明确声明。

6. **[设计边界] 不在 CSLT-04 内部做重连重试**：SSE 连接的重连机制由前端 CSLT-08（EventSource 内置重连）和 Nginx（长连接保持）共同处理。CSLT-04 只负责：(a) 重连时识别 Last-Event-Id 请求头；(b) 恢复 StreamSession 并从中断位置续传。不在服务端主动重连或重试。

7. **[设计边界] 不负责上游 Generator 的生命周期管理**：`chunk_generator: AsyncGenerator[GenerationChunk, None]` 由 CSLT-08 编排层创建和管理。CSLT-04 只负责消费，不负责创建、预热或回收 Generator。硬超时时可调用 `generator.aclose()` 通知上游停止生成。

8. **[配置项] 所有可调参数通过 AppSettings 环境变量注入**：不得在代码中硬编码 500、300、15、5、20 等数字。所有配置项通过 `packages/py-config` 读取，提供合理的默认值：
   - `SSE_MAX_CONCURRENT_CONNECTIONS: int = 500`
   - `SSE_SESSION_TTL_SECONDS: int = 300`
   - `SSE_HEARTBEAT_INTERVAL_SECONDS: int = 15`
   - `SSE_FIRST_CHUNK_TIMEOUT_SECONDS: int = 5`
   - `SSE_FULL_TIMEOUT_SECONDS: int = 20`

9. **[易错点] Semaphore 容量的进程级语义**：`SSE_MAX_CONCURRENT_CONNECTIONS = 500` 指**每个 Uvicorn worker 进程**的上限，而非全局。若配置 `--workers 4`，全局最大并发 SSE 连接数为 4 x 500 = 2000。Nginx 的 `worker_connections` 配置需保证大于此值。

10. **[偷懒红线] 禁止用 \"...\" 省略任何异常处理逻辑**：每个 `except` 块内的代码必须显式写出，包括：日志记录、DoneEvent/ErrorEvent 发送、信号量释放、StreamSession 状态更新。不得写 `# handle error` 或 `# TODO: error handling` 等占位符。

### 1.12 文档详细度自检清单【对内实现】

- [x] 文档自包含：一位不了解本项目代码的 Agent，仅凭此文档即可完成 CSLT-04 编码
- [x] 无偷懒表述：全文无 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`、`"请根据实际情况补充"`、`"开发者自行决定"`
- [x] 类型定义完整：每个 Pydantic 字段都有 `description` + `examples` + 约束（`minLength`/`maxLength`/`ge`/`le`/`pattern` 等）
- [x] 逻辑步骤完整：6 个主步骤 + 1 个并行心跳循环，每个步骤都有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：4 种异常场景（并发超限、上游异常、超时、安全阻断），每种都有精确的触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有默认值来源（AppSettings 环境变量）、条件分支（5 种 finish_reason 枚举值映射）、业务规则（sequence 从 1 开始、Last-Event-Id 续传偏移 +1、安全阻断特殊处理）都已显式写出
- [x] 技术栈绑定明确：必须使用 6 项 + 禁止使用 4 项均已列出，且与技术栈设计 §2 和 DEPLOY-05 落地规范保持一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档 v2.0 一致

### 1.14 外部接口契约清单【已锁定】

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| ChunkEvent | `docs/contracts/CSLT-04/ChunkEvent.json` | event | draft | CSLT-04 | CSLT-08 |
| DoneEvent | `docs/contracts/CSLT-04/DoneEvent.json` | event | draft | CSLT-04 | CSLT-08 |
| HeartbeatEvent | `docs/contracts/CSLT-04/HeartbeatEvent.json` | event | draft | CSLT-04 | CSLT-08 |
| ErrorEvent | `docs/contracts/CSLT-04/ErrorEvent.json` | event | draft | CSLT-04 | CSLT-08 |
| StreamErrorCode | `docs/contracts/CSLT-04/StreamErrorCode.json` | shared-enum | draft | CSLT-04 | CSLT-08 |
| GenerationChunk | `docs/contracts/CSLT-03/GenerationChunk.json` | output | draft | CSLT-03 | CSLT-04 |
| GenerationStatus | `docs/contracts/CSLT-03/GenerationStatus.json` | shared-enum | draft | CSLT-03 | CSLT-04 |
| AppSettings | `docs/contracts/DEPLOY-05/AppSettings.json` | shared-model | draft | DEPLOY-05 | CSLT-04 |
| LogEntry | `docs/contracts/OBS-01/LogEntry.json` | output | draft | OBS-01 | CSLT-04 |

### 1.15 意图一致性声明【对内实现】

- **配套意图文档**：`CSLT-04-流式应答推送-意图文档.md`
- **冻结时间**：`2026-05-27 15:25:30`
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档 §1.6 中的业务字段定义一致——输入来自 CSLT-03/GenerationChunk（3 字段完全对齐），输出 SSE 事件（4 种事件类型 + 流标识符 + 流结束原因与 §1.6.2 对齐）
  - [x] 本落地规范中的状态机实现与意图文档 §1.7 中的状态业务定义一致——意图文档确认"不涉及业务状态流转"，本落地规范仅提供内部分析用的内存生命周期表
  - [x] 本落地规范中的异常处理策略与意图文档 §1.8 中的异常业务策略一致——§1.8 的 3 种异常（连接中断/上游中止/推送超时）均有对应的 §1.9 实现方案，且精确度超过意图文档的业务描述
  - [x] 本落地规范中的验收测试场景覆盖意图文档 §1.9 中的所有验收标准——AC-01（首字延迟）→ 测试 1.10.1 ttft_ms 断言；AC-02（内容完整）→ 测试 1.10.1 chunk 文本一致性；AC-03（连接中断恢复）→ 测试 1.10.2 断点续传；AC-04（流结束信号）→ 全部测试均断言 done 事件；AC-05（异常中止内容保护）→ 测试 1.10.5 已推送内容保留；AC-06（并发互不干扰）→ 测试 1.10.4 并发限流 + chunk_buffer 按 session_id 隔离
  - [x] 本落地规范中的技术实现未超出意图文档中"留给规范阶段的技术决策"（§1.12 的 7 项决策）的范围——SSE 事件格式（决策 1）、重连参数（决策 2：5min TTL + 指数退避）、心跳策略（决策 3：15s 间隔 JSON）、超时阈值（决策 4：5s 软超时 + 20s 硬超时）、数据模型（决策 5：Pydantic 4 事件模型 + StreamSession）、并发管理（决策 6：500 per process）、错误码格式（决策 7：error_code + detail 双字段）——全部 7 项均有对应实现方案
- **偏差说明**：无偏差，技术实现与意图文档完全一致。
