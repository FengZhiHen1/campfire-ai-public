## 1 功能点：CSLT-04 流式应答推送 — 设计文档（瘦身版）

> **文档生成时间**：`2026-05-27 17:05:28`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-27 17:05:28` | AI Assistant | 初始版本，基于 s06 技术预研报告（6 项自主决策 + 4 项待上层裁决）和已冻结意图文档 v2.0 全量生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `CSLT-04-流式应答推送-意图文档.md`（已冻结于 `2026-05-27 15:25:30`）
> - 本模块的精确编码规格见 `CSLT-04-流式应答推送-落地规范.md`

### 1.1 技术实现思路

流式应答推送采用 **FastAPI StreamingResponse + W3C SSE 标准** 的核心模式，将上游 CSLT-03 产出的 GenerationChunk AsyncGenerator 逐 chunk 消费后封装为 SSE 事件流推送至前端。

**为什么选择 SSE 而非 WebSocket**：CSLT-04 的数据流是纯粹的单向推送（服务端→客户端），客户端只需接收文本，不需要向服务端发送消息。SSE 原生支持自动重连（`Last-Event-Id` 机制）和文本流式消费（`EventSource` API），协议开销比 WebSocket 小得多（无需二进制帧封装、无需 Pong 心跳应答）。WebSocket 的双工通道在本场景中属于过度设计——引入的额外握手开销、帧协议解析和连接管理复杂度不会换来任何实际收益。此外，Nginx 对 SSE 的配置（`proxy_buffering off`）已由 DEPLOY-02 预置完成，无需额外基础设施投入。

**为什么在 CSLT-04 层消费 AsyncGenerator 而非在 CSLT-03 内部直接推 SSE**：这是职责分离的设计选择。CSLT-03 只负责"生成文本内容"——它的 AsyncGenerator yield 的是领域对象 GenerationChunk（含 text、is_final、finish_reason），不关心传输协议。CSLT-04 专门负责将领域对象映射为传输层的事件格式（SSE text/event-stream），完成序列化、心跳保活、断点续传、异常降级等协议层面的工作。如果未来需要支持另一种传输协议（如 gRPC server-streaming 供管理后台使用），只需在 CSLT-04 中新增一个协议适配器，CSLT-03 完全不受影响。反之，如果 CSLT-03 的生成逻辑需要升级（如更换 LLM 提供商），CSLT-04 的 SSE 推送逻辑也不受影响。

**AsyncGenerator 消费的核心数据流**：CSLT-04 在接口入口处接收 session_id 和 CSLT-03 的 AsyncGenerator 引用，使用 `async for` 逐 chunk 消费。每收到一个 chunk，将其 `text` 字段写入 SSE `data` 行，格式为 `event: chunk\ndata: {"text":"...","sequence":n}\n\n`。收到 `is_final=True` 的 chunk 后，发送 `done` 事件并关闭连接。整体数据流：CSLT-03 AsyncGenerator → CSLT-04 `async for` 循环 → `StreamingResponse` 的异步迭代器 → Nginx 透传 → 前端 EventSource 消费。

**sequence 序列号的设计作用**：每个 `chunk` 事件携带一个从 1 开始单调递增的 `sequence` 整数字段。它的作用有三个：(1) 前端可通过比对最后收到的 sequence 与新 chunk 的 sequence 是否连续，检测是否发生丢帧；(2) 重连时前端将 `Last-Event-Id` 设为最后成功收到的 sequence，CSLT-04 据此跳过已推送的 chunk，从中断位置续传；(3) 序列号在服务端内存中维护（每个 stream 会话独立计数器），无需持久化——连接断开且 stream 过期后整个会话计数即释放。

**连接管理的内部状态**：CSLT-04 为每个推送会话维护一个内存中的 `StreamSession` 对象，包含 stream_id（UUID）、已推送的 chunk 缓冲区（dict[int, str]，key 为 sequence 号）、首 chunk 发送时间戳（TTFT 计算用）、连接创建时间（全部署期超时判定用）。连接断开后 `StreamSession` 保留 TTL（推荐 5 分钟，见 §1.6 决策 1），超时后自动清理。

**异常降级的 try/finally 保证**：在 `async for` 循环外包裹 `try/finally` 块。无论上游 Generator 正常结束、抛出异常还是超时截断，`finally` 块确保发送 `done` 或 `error` 事件——这满足了意图文档 AC-04 的要求"每次推送终止时家属端必然收到明确的流结束事件"。如果 `finally` 块本身执行中再次异常（如连接已断开无法写入），仅记录结构化日志后静默退出，不再尝试通知前端。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：
  - CSLT-03 应急方案生成-设计文档.md + 落地规范.md（已冻结）
  - CSLT-01 危机分级判定-设计文档.md + 落地规范.md（已冻结）
  - CSLT-02 RAG语义检索-设计文档.md + 落地规范.md（已冻结）
  - DEPLOY-02 反向代理路由-设计文档.md + 落地规范.md（已冻结）
  - DEPLOY-05 环境配置管理-落地规范.md（已冻结）
  - OBS-01 结构化日志-落地规范.md（已冻结）
  - SEC-04 防刷限流-落地规范.md（已冻结）
  - 全部 24 份已冻结落地规范（详见 s05 材料准备报告）
  - `docs/contracts/CSLT-03/GenerationChunk.json`（maturity: draft）
  - `docs/contracts/CSLT-03/GenerationStatus.json`（maturity: draft）
  - `infrastructure/nginx/conf.d/campfire.conf`（实际 Nginx 配置）

- **兼容性结论**：**无冲突**。逐项验证如下：
  - **CSLT-03 GenerationChunk**：CSLT-03 设计文档 §1.1 明确标注"每个 GenerationChunk yield 给下游 CSLT-04"，CSLT-04 作为消费者通过 `async for` 消费 AsyncGenerator，接口方向一致。GenerationChunk 的三个字段（text / is_final / finish_reason）与本模块意图文档 §1.6.1 的输入定义完全对齐。
  - **CSLT-03 GenerationStatus**：GenerationStatus 的五种状态值（COMPLETE / PARTIAL / BLOCKED / TIMEOUT / ERROR）将在本模块的 `done` 事件 `finish_reason` 字段中原样映射，无需引入新的或修改的枚举值。GenerationStatus 的 `x-consumers` 已包含 CSLT-04。
  - **DEPLOY-02 Nginx SSE 路由**：`campfire.conf` 中 SSE location 的 `proxy_buffering off`、`proxy_http_version 1.1`、`proxy_read_timeout 3600s`、`proxy_ignore_client_abort off` 全部正确配置，无需任何修改。CSLT-04 的 SSE 连接超时（最长 ≈20s）远小于 Nginx 的 `proxy_read_timeout 3600s`，安全裕度充足。
  - **DEPLOY-05 环境配置管理**：CSLT-04 新增的配置项（`SSE_MAX_CONCURRENT_CONNECTIONS`）将遵循 DEPLOY-05 的 `AppSettings` Pydantic model 模式，通过环境变量注入。
  - **SEC-04 防刷限流**：SSE 端点 `/api/v1/consult/stream/{session_id}` 的限流由 SEC-04 统一处理，CSLT-04 不自行实现限流逻辑。
  - **OBS-01 结构化日志**：CSLT-04 使用 `packages/py-logger` 记录结构化日志（trace_id、stream_id、event_type、chunk_count、ttft_ms），与 OBS-01 日志接口对齐。

- **复用的已有设计**：
  - CSLT-03/GenerationChunk：输入数据标准（text / is_final / finish_reason）
  - CSLT-03/GenerationStatus：`done` 事件 finish_reason 的枚举值来源
  - DEPLOY-02 Nginx SSE 配置：无需新增路由 location
  - DEPLOY-05/AppSettings：配置项管理模式（环境变量 → Pydantic model）
  - OBS-01/LogEntry：结构化日志格式

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| CSLT-03（应急方案生成） | 上游数据来源 | 通过 `AsyncGenerator[GenerationChunk, None]` 接口消费流式文本增量。使用 `async for chunk in generator:` 逐 chunk 接收。chunk.text 为当前 delta 文本，chunk.is_final 标记流结束，chunk.finish_reason 传递终止原因（stop / length / timeout） |
| CSLT-08（咨询编排逻辑） | 下游数据消费 | 前端通过 `EventSource` API 或 React `useSSEStream` Hook 连接 `/api/v1/consult/stream/{session_id}`，消费本模块推送的 SSE 事件流。重连时通过 `Last-Event-Id` 请求头传递 sequence 号实现断点续传 |
| FastAPI StreamingResponse | 框架依赖 | 使用 `StreamingResponse(generator(), media_type="text/event-stream")` 将异步迭代器包装为 HTTP 响应。响应头注入：`Content-Type: text/event-stream`、`Cache-Control: no-cache`、`Connection: keep-alive`、`X-Accel-Buffering: no` |
| Nginx 反向代理 | 基础设施依赖 | SSE 路由 `/api/v1/consult/stream` 已由 DEPLOY-02 在 `campfire.conf` 中预配置 `proxy_buffering off` + `proxy_read_timeout 3600s`。CSLT-04 无需修改 Nginx 配置 |
| Uvicorn ASGI Server | 运行时依赖 | 应用的 ASGI 运行时，asyncio 事件循环支持数千并发连接。4 workers x 500 connections/worker = 2000 并发 SSE 连接理论峰值 |
| `packages/py-schemas` | 内部包依赖 | SSE 事件 Pydantic 模型（ChunkEvent、DoneEvent、HeartbeatEvent、ErrorEvent）的 JSON 序列化 |
| `packages/py-logger` | 内部包依赖 | 推送过程的结构化日志记录（stream_id、chunk_count、ttft_ms、error_type 等字段） |
| `packages/py-config` | 内部包依赖 | 环境配置读取（`SSE_MAX_CONCURRENT_CONNECTIONS`、`SSE_SESSION_TTL_SECONDS`） |

精确的函数签名、SSE 事件 JSON Schema、错误码枚举见落地规范。

### 1.4 状态机设计（技术实现策略，如适用）

本功能点不涉及业务状态流转，故无需状态机。意图文档 §1.7 已确认："本功能点作为纯数据推送通道，不涉及业务状态流转"。

技术实现层面，推送会话的**内部生命周期**（纯内存，不持久化到数据库）如下：

```
CREATED ──第一个chunk已推送──▶ STREAMING ──is_final=true 收到──▶ COMPLETED
    │                              │                                   
    │                              ├──上游 Generator 异常──▶ ABORTED
    │                              │                                   
    │                              └──客户端断开 + 超时过期──▶ EXPIRED
    │
    └──上游 Generator 未启动就异常──▶ ABORTED
```

- **CREATED**：`StreamSession` 已创建但尚未开始消费 AsyncGenerator。等待 CSLT-08 编排层调用生成入口后触发 Generator 启动。
- **STREAMING**：正在 `async for` 消费 Generator 并推送 SSE 事件。此状态下 `sequence` 计数器随每个 chunk 事件递增。
- **COMPLETED**：收到 `is_final=True` 的 chunk，已发送 `done` 事件，SSE 连接正常关闭。
- **ABORTED**：上游 Generator 异常或提前终止，已发送 `done` 事件（finish_reason=error/blocked），SSE 连接关闭。
- **EXPIRED**：客户端在 STREAMING 期间断开连接，`StreamSession` 在 TTL（推荐 5 分钟）后超时清理。

状态转换无持久化需求，严格限定在单进程内存范围内。流断开后的重连由 CSLT-08 前端负责发起，本模块仅保留已推送进度供续传查询。

### 1.5 设计原则兑现清单（技术视角）

| 原则编号 | 原则名称 | 技术响应 |
|----------|----------|----------|
| 1.1 | 内容完整性 | 传输层禁止对 CSLT-03 产出的 chunk.text 做任何修改、截断或格式转换——`async for` 循环内的 chunk.text 原样封装进 SSE data，不经过任何文本处理管道 |
| 2.1 | 单一职责 | CSLT-04 仅负责"将 GenerationChunk 流映射为 SSE 事件流"。不负责内容生成质量（归属 CSLT-03）、内容安全性（归属 SEC-02）、前端渲染（归属 CSLT-08）、连接认证（由 AUTH-04 JWT 中间件处理） |
| 2.2 | 接口隔离 | 上游接口仅依赖 `AsyncGenerator[GenerationChunk, None]` 和 `stream_id: str` 两个输入，不依赖 CSLT-03 的任何内部实现细节（如 Prompt 构建、LLM 客户端实例）。下游接口仅暴露 SSE 标准格式，不暴露服务端实现语言或框架特征 |
| 2.3 | 协议透明 | 对外使用 W3C 标准 SSE 协议（`text/event-stream`），不引入私有事件类型或非标准字段名。任何支持 `EventSource` API 的客户端均可消费 |
| 3.1 | 异常可见 | 所有异常（Generator 抛出、连接断开、超时终止）均通过结构化日志 + SSE `error`/`done` 事件双通道输出，不静默吞掉异常 |
| 3.2 | 性能可观测 | 记录每个推送会话的 TTFT（首 chunk 延迟）、总时长、chunk 数量、终止原因，通过 OBS-01 的 LogEntry 格式输出，可导入 Prometheus 指标系统 |
| 4.1 | 资源可控 | 并发 SSE 连接数通过 `asyncio.Semaphore` 在路由入口限流，超限时返回 HTTP 429 而非排队等待。session 缓冲区（chunk 历史）在会话过期后自动释放 |
| 5.1 | 安全阻断隔离 | 当上游 CSLT-03 返回 `GenerationStatus=BLOCKED` 时，本模块仅推送预设的安全提示文本（通过 `finish_reason="blocked"` 标记），不推送任何被阻断前的生成片段。此行为受意图文档 §1.11(5) 约束 |

> 原则编号参考技术栈设计 §4（设计原则体系）。

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| 传输协议 | SSE（W3C text/event-stream）| WebSocket | SSE 原生支持自动重连（Last-Event-Id）和文本流消费（EventSource），协议开销小；WebSocket 的双工通道在本场景中过度设计，额外握手和帧解析无实际收益。Nginx SSE 配置已预置完成，零额外投入 |
| AsyncGenerator 消费位置 | 在 CSLT-04 独立消费（async for） | 在 CSLT-03 内部直接推 SSE | 职责分离：CSLT-03 产出领域对象（GenerationChunk），CSLT-04 适配传输协议。未来如需支持其他协议（gRPC、长轮询等），仅需新增 CSLT-04 适配器，CSLT-03 不受影响 |
| 响应封装 | FastAPI StreamingResponse | 裸 asyncio 协程手动管理 | StreamingResponse 自动注入 SSE 响应头（Content-Type/缓存控制），与 FastAPI 中间件栈（CORS/JWT 认证/限流）无缝集成 |
| 断点续传机制 | SSE Last-Event-Id 标准机制 | 自定义 query param（?from_seq=n） | Last-Event-Id 是 SSE 标准内建的重连机制，EventSource API 在断线后自动携带，无需前端手动构造 URL。减少 CSLT-08 的实现复杂度 |
| 软超时 + 进度提示 | 首 chunk 5s 软超时后推送进度提示（不终止流）| 直接硬超时终止流 | 意图文档 §1.8.3 要求"超过合理等待时间后主动告知家属正在生成中"——软超时触发进度提示而非终止，家属看到系统仍在工作、减少焦虑 | 
| 流过期 TTL | 5 分钟 | 30 秒（快速释放）；无限期（不过期） | 5 分钟覆盖大部分网络波动场景（小程序切后台、手机信号切换），远小于 Nginx proxy_read_timeout 3600s 的安全裕度；无限期不释放可能导致内存泄露 |
| 心跳保活 | 15 秒间隔 SSE 心跳事件 | TCP keepalive（操作系统级）；无心跳 | TCP keepalive 不可编程且部分中间件不可靠；15 秒间隔在 20-30s 常见的移动网络 keepalive 超时前足够安全，每条心跳约 100 字节开销极低 |
| `done` 事件 finish_reason 枚举 | 直接复用 CSLT-03 GenerationStatus 的值 | CSLT-04 自定义枚举 | 减少一层映射转换，前端只需理解一组状态值。若 CSLT-03 新增状态，CSLT-04 自动透传，无需同步更新 |
| 错误码格式 | `{error_code: string, detail: string}` 双字段 | 仅 HTTP status code | 参考项目已落地的错误类型（PROF-01 的 `ProfileLimitExceededError` 等），双字段格式兼容 OBS-01 结构化日志的 error 字段约定，便于前端按 error_code 精确区分处理逻辑 |

> "心跳保活间隔"、"流过期 TTL"、"首 chunk 软超时阈值"、"并发连接数上限"四项决策的技术推断基于报告 §5 推荐默认值，最终确认权归属用户。

### 1.7 注意事项与禁止行为（设计层面）

1. **[硬禁令] 禁止修改上游文本**：CSLT-04 不得对 CSLT-03 产出的 chunk.text 做任何增删改、截断、编码转换或格式化。文本必须原样透传。此禁令来自意图文档 §1.11(1) 内容完整性约束。

2. **[关键约束] `done` 事件必定发送**：无论流正常结束、上游异常中止还是超时截断，`try/finally` 块必须保证发送一个 `done` 或 `error` 事件后再关闭 SSE 连接。此约束来自意图文档 AC-04"流结束信号可靠"。

3. **[硬禁令] 安全阻断时禁止推送生成片段**：当上游 CSLT-03 返回 `GenerationStatus=BLOCKED` 时，CSLT-04 只能推送预设的安全提示文本，不得推送任何被阻断前已生成的内容片段。此约束来自意图文档 §1.11(5)"安全阻断内容隔离"。

4. **[设计边界] 不负责推送内容的安全性判断**：CSLT-04 不分析、不审查、不过滤 chunk.text 的语义内容。内容安全的阻断和过滤是 SEC-02 的职责，CSLT-04 只负责透传。CSLT-04 的"阻断"行为仅响应上游 CSLT-03 的 `GenerationStatus=BLOCKED` 信号。

5. **[设计边界] 不负责前端 SSE 消费实现**：CSLT-04 不关心前端使用 `EventSource` API、`fetch` 流式读取还是 `useSSEStream` Hook。它只负责产出符合 W3C 标准的 SSE 事件流。前端消费逻辑归属 CSLT-08。

6. **[设计边界] 不负责 SSE 连接的认证鉴权**：SSE 端点 `/api/v1/consult/stream/{session_id}` 的 JWT 认证和角色鉴权由 AUTH-04 的中间件（`require_role` Depends）统一处理，在请求到达 CSLT-04 路由处理函数之前已完成。CSLT-04 不在内部重复验证用户身份。

7. **[易错点] sequence 号从 1 开始递增**：SSE `id:` 字段从 1 开始（0 留给初始化事件），每个 `chunk` 事件的 `data.sequence` 与 `id:` 值保持一致。重连时 `Last-Event-Id` 的值为最后成功接收的 sequence 号，CSLT-04 据此跳过 <= 该值的已推送 chunk。注意：`Last-Event-Id` 在 SSE 标准中是上一个事件的 id 值，因此重连后从 `sequence + 1` 开始续传。

8. **[易错点] StreamingResponse 的生成器函数必须是 async def**：如果使用 `def` 返回同步生成器，FastAPI 会在单独的线程池中运行，导致 asyncio 上下文丢失（`asyncio.wait_for` 在同步线程中无法取消）。必须使用 `async def` 返回异步迭代器。

9. **[禁止行为] 禁止在 SSE 事件流中注入非标准数据**：不使用 `event:` 和 `data:` 之外的 SSE 字段（除 `id:` 用于断点续传和 `retry:` 用于向客户端建议重连间隔外）。不在 `data` 字段中嵌入 HTML、JavaScript 或其他非 JSON 内容。

10. **[配置项] 所有可调参数通过环境变量注入**：`SSE_MAX_CONCURRENT_CONNECTIONS`（默认 500）、`SSE_SESSION_TTL_SECONDS`（默认 300）、`SSE_HEARTBEAT_INTERVAL_SECONDS`（默认 15）、`SSE_FIRST_CHUNK_TIMEOUT_SECONDS`（默认 5）均为环境变量可配置，与 DEPLOY-05 的 AppSettings 模式一致。

### 1.8 引用：配套意图文档

- **意图文档**：`CSLT-04-流式应答推送-意图文档.md`
- **冻结时间**：`2026-05-27 15:25:30`
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。所有 6 项验收标准（AC-01~AC-06）均有对应的技术方案覆盖：AC-01（首字延迟）通过 TTFT 监控和 StreamingResponse 即时推送保障；AC-02（内容完整传输）通过禁止修改上游文本的硬禁令保障；AC-03（连接中断恢复）通过 SSE Last-Event-Id 断点续传机制保障；AC-04（流结束信号可靠）通过 try/finally 块保障；AC-05（异常中止内容保护）通过 done 事件发送已推送内容和中止原因保障；AC-06（并发推送互不干扰）通过独立 StreamSession 对象和 sequence 号隔离保障。3 种异常策略（连接中断、上游中止、推送超时）均有对应的技术实现方案。如有歧义，以意图文档为准。
