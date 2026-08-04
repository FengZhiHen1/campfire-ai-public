# AI 服务接口契约

> **本文唯一拥有**：AI 服务 HTTP 接口的契约层——统一 SSE 流式协议（事件类型族、sequence 与断点续传、终态语义）、统一错误语义与错误体、请求/响应契约规则、观测约定（trace_id/Token/审计）、按面端点组织视图与 Skill 映射。
> **状态**：架构基线（2026-08-04，[ADR-015](./决策/ADR-015-统一AI服务接口契约.md)）。
> **依据**：[Agent 基座](./Agent基座.md)（分面执行策略、Skill 清单、安全与可观测原则）、[Agent内核框架](./Agent内核框架.md)（内核事件总线，SSE 事件的映射接缝）。
> **不拥有**：端点业务语义、请求/响应字段、业务规则与数据模型（归各[机制文档](./机制/README.md)）；运行时架构与工具/Skill 清单（归 [Agent 基座](./Agent基座.md)）；流式装配实现（内核事件总线 → text/event-stream，归[项目结构](./项目结构/目录骨架.md)）。

## 一、设计原则

1. **契约层统一、端点按面保留**：SSE 事件协议、错误语义、契约校验、观测约定全平台一套；端点按执行面组织（应急面/异步面）、按能力保留语义，OpenAPI 可读——与基座「统一内核 + 分面自治」同构；
2. **一套 SSE 协议承载两种形态**：生成型（用户在线等待的文本流：应急首份方案/追问/科普问答 → `chunk` 增量）与任务型（后台 Agent 任务：案例提取/预审/工单预组装/趋势复盘 → `accepted → progress → result`）；
3. **执行面与接口形态解耦**：接口形态由用户交互语义决定（在线等待 = 生成型、后台任务 = 任务型），不由执行引擎决定——`knowledge-qa` 由异步面 Skill 执行，但接口为生成型流式；
4. **两段式建连**：POST 创建/触发（校验 + 安全前置 → 返回 `session_id` / `task_id`）→ GET 事件流连接（原生 EventSource 兼容、自动重连、Last-Event-Id 断点续传）；
5. **契约驱动**：请求/响应体一律 `py-schemas` Pydantic 契约；结构化输出（四段式、L2 卡片、预审报告、复盘报告、工单摘要）经契约校验后才以 `result` 事件发出，不合格输出阻断并记录（与基座输出校验一致）；
6. **安全前置统一**：红线关键词门、PII 检测、免责声明注入为 API 层统一前置（依赖注入/中间件），在创建/触发端点上生效，端点实现不各自实现；
7. **可观测统一**：trace_id 贯通请求、事件与错误体；Token/成本按 Skill/面聚合；工具调用审计复用内核事件总线（[Agent 基座](./Agent基座.md) §六）。

## 二、端点组织

### 2.1 端点族与 Skill 映射

| Skill | 执行面 | 接口形态 | 创建/触发端点（POST） | 事件流端点（GET） |
|---|---|---|---|---|
| `emergency-consult`（首份方案） | 应急面 | 生成型 | `POST /api/v1/consult/stream` | `GET /api/v1/consult/stream/{session_id}` |
| `emergency-consult`（追问轮） | 应急面 | 生成型 | `POST /api/v1/consult/stream/{session_id}/followup` | 同上（会话内继续） |
| `case-extraction` | 异步面 | 任务型 | L1 叙事上传端点（上传后自动触发，见[标准案例库](./机制/标准案例库/README.md)） | `GET /api/v1/tasks/{task_id}/events` |
| `review-assist` | 异步面 | 任务型 | 审核提交端点（专家提交审核后自动触发，见[标准案例库·生产与审核流程](./机制/标准案例库/生产与审核流程.md)） | 同上 |
| `ticket-enrich` | 异步面 | 任务型 | 工单创建端点（`POST /api/v1/tickets`，创建后自动触发） | 同上 |
| `trend-report` | 异步面 | 任务型 | `POST /api/v1/profiles/{id}/trend-report`（显式触发；M5 机制文档待编写，端点族归属 profile） | 同上 |
| `knowledge-qa` | 异步面 | 生成型 | `POST /api/v1/knowledge/ask` | 同上 |

> 触发编排（提交后何时触发提取/预审、任务串联顺序）归各[机制文档](./机制/README.md)拥有；本表只声明「哪个端点触发、事件从哪个端点消费」。

### 2.2 查询端点（非流式，JSON）

- `GET /api/v1/consult/history`、`GET /api/v1/consult/{id}` — 应急会话查询（语义见[智能应急咨询](./机制/智能应急咨询.md) §六）
- `GET /api/v1/tasks/{task_id}` — 任务状态与结果补查（断连后的兜底读取）

查询端点遵循本文错误语义与观测约定，不引入流式。

## 三、统一 SSE 流式协议

### 3.1 传输与建连

- 媒体类型 `text/event-stream`（W3C SSE），UTF-8；事件流连接端点一律 **GET**（EventSource 兼容，自动重连）；
- 创建/触发端点（POST）经校验与安全前置后返回 `session_id` / `task_id`，客户端凭 id 连接事件流；
- 重连：请求头 `Last-Event-Id: {sequence}`，服务端从 sequence+1 续传；任务型重连时若任务已完成，重发 `result`；生成型会话已终态则直接返回 `done`。

### 3.2 事件外壳

每个事件：`event: {type}` + `id: {sequence}` + `data: {json}`。`sequence` 为会话/任务内单调递增整数（重连续传的锚点）。

### 3.3 事件类型族

| 事件 | 适用形态 | data 字段 | 语义 |
|---|---|---|---|
| `accepted` | 任务型 | `{task_id}` | 任务已受理（POST 响应已含 task_id 时用于重连场景） |
| `progress` | 任务型 | `{stage, detail?}` | 阶段/工具执行进度，映射内核 `turn_start` / `tool_execution_*` 事件 |
| `chunk` | 生成型 | `{text}` | 文本增量，客户端增量渲染 |
| `result` | 两种 | `{contract, payload}` | 最终结构化产出，经 Pydantic 契约校验后发出；`contract` 指向 py-schemas 契约名 |
| `heartbeat` | 两种 | `{}` | 连接保活，15s 间隔 |
| `done` | 两种 | `{finish_reason}` | 正常终态，其后关闭连接 |
| `error` | 两种 | `{error_code, detail}` | 错误终态，其后关闭连接（错误体见 §四） |

### 3.4 事件序列（终态二选一：`done` / `error`）

- **生成型**：`chunk`（×N）→ [`result`] → `done`｜`error`；追问轮为通用 Agent 会话自由文本，不套输出契约，无 `result`（[Agent 基座](./Agent基座.md) §5.1）；
- **任务型**：`accepted` → `progress`（×N）→ `result` → `done`｜`error`。

## 四、统一错误语义

### 4.1 HTTP 状态码（创建/触发/查询端点）

| 状态码 | 语义 |
|---|---|
| 400 | 请求格式/参数非法（如 id 格式） |
| 401 / 403 | 未认证 / 无权限（六角色显式 RBAC，见[认证与访问](./机制/认证与访问.md)） |
| 404 | 会话/任务/资源不存在或已过期 |
| 409 | 状态冲突（如对已终态会话提交追问） |
| 422 | 请求体 Pydantic 契约校验失败（沿用 SEC-05 `ValidationErrorResponse` 格式） |
| 429 | 限流（Redis 滑动窗口：用户级 30 req/min、IP 级 100 req/min） |
| 503 | 服务不可用（LLM/检索/存储不可达） |
| 504 | 处理超时（创建阶段同步前置超时） |

### 4.2 统一错误体

```json
{ "error_code": "MODULE_SCENARIO", "detail": "中文描述", "trace_id": "…" }
```

- `error_code` 命名：`{模块}_{场景}`（如 `CONSULT_SESSION_EXPIRED`、`TASK_NOT_FOUND`、`LLM_UNAVAILABLE`、`OUTPUT_SCHEMA_VIOLATION`）；
- SSE 握手阶段的 HTTP 错误（404 任务不存在 / 429 并发超限）经响应状态码返回；流内错误一律 `error` 事件携带同一错误体。

## 五、请求/响应契约规则

- 全部请求/响应体由 `py-schemas` 唯一拥有（DSR-002），FastAPI 据此生成 OpenAPI；
- 结构化输出契约（四段式、L2 卡片、预审报告、复盘报告、工单摘要）经 Skill metadata `output-schema` 声明（[Agent 基座](./Agent基座.md) §四），`result` 事件在契约校验通过后发出；校验失败 → `error`（`OUTPUT_SCHEMA_VIOLATION`）+ 记录；
- 输入校验失败 → 422，格式沿用 SEC-05。

## 六、观测约定

- **trace_id**：请求头 `X-Trace-Id` 贯通（未携带则服务端生成）；SSE 事件与错误体携带；
- **Token/成本**：按 Skill/面维度聚合统计（复用[Agent 基座](./Agent基座.md) §六 Token 追踪），`result` 事件可附 usage 明细；
- **审计**：工具调用审计沿用 py-logger，trace_id 贯通事件流与内核事件总线。

## 七、范围与非目标

- **范围**：AI 生成类端点（6 个 Skill 对应端点族）+ 会话/任务查询端点；错误体与 trace_id 约定对全平台 API 通用；
- **非目标**：非 AI CRUD 端点（档案、认证、工单流转、科普文章管理）保持普通 REST 形态，不引入 SSE；不定义模块业务规则与数据模型（归机制文档）；不定义内核/运行时架构（归 [Agent 基座](./Agent基座.md)）；不定义流式装配实现（归[项目结构](./项目结构/目录骨架.md) streaming/）。
