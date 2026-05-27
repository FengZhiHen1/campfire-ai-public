## 1 功能点：CSLT-08 咨询编排逻辑 — 设计文档（瘦身版）

> **文档生成时间**：`2026-05-27 21:47:34`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-27 21:47:34` | AI Assistant | 初始版本，基于 s06 技术预研报告（7 项自主决策 + 3 项业务矛盾标记）和已冻结意图文档 v2.0 全量生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `CSLT-08-咨询编排逻辑-意图文档.md`（已冻结于 `2026-05-27 21:37:16`）
> - 本模块的精确编码规格见 `CSLT-08-咨询编排逻辑-落地规范.md`

### 1.1 技术实现思路

CSLT-08 是智能应急咨询模块的前端 L1b 逻辑层枢纽，采用 **Zustand Store Slice + 状态转换表 + fetch Streaming SSE 自定义解析器** 的核心模式，管理家属从打开咨询页面到获得 AI 应急方案的完整会话生命周期。

**为什么选择 Zustand 单一 Store 而非 useReducer 或 XState**：CSLT-08 需要管理的状态跨度大——8 种业务状态、消息列表（最大 200 条）、SSE 流式文本累加、段落解析结果、工单引导标记。这些状态需要被不同组件消费（CSLT-07 的多个子组件通过 `useConsult()` Hook 读取），Zustand 5.x 的 selector 模式天然支持细粒度订阅——消息列表变更不会触发仅关心会话状态的组件重渲染，反之亦然。useReducer 的 Context 传递方式在复杂状态订阅场景下性能较差（任何字段变更都会触发所有 Consumer 渲染），而 XState 引入额外库体积且心智模型与项目统一的 Zustand 生态重叠。单一 Store 的设计也与项目结构 §6.1 对 logics/consult/store/ 的目录规划一致。

**为什么使用 fetch Streaming 自解析 SSE 而非浏览器原生 EventSource**：微信小程序 Taro 运行时环境不支持 `EventSource` API。采用 `Taro.request` 的 `enableChunked` 模式或直接使用 fetch API 流式读取响应体，手动解析 SSE 协议格式（`event:` / `data:` / `id:` 行分隔）。自实现解析器可以精确控制 chunk 边界检测、心跳间隔判定（15s 无事件视为连接僵死）、以及指数退避重连（1s/2s/5s）。同时能以 `lastEventId`（映射 CSLT-04 的 `sequence` 序列号）在重连时向服务端传递续传位置。这一方案虽比原生 EventSource 多约 80 行解析代码，但换来了 Taro 环境的完整兼容性和精细的流控制能力。如果未来微信小程序原生支持 EventSource，只需替换适配层，Store 和业务逻辑不受影响。

**五阶段流程编排的核心数据流**：家属的咨询体验被组织为五个串联阶段，每个阶段由一个 `ConsultSessionState` 状态标识和驱动：

1. **前置选择**（`idle` → `selecting_behavior` → `idle`/`submitting`）：家属勾选行为类型（七类 BehaviorTypeCategory 枚举，可多选至少一项），键入行为描述文本。输入校验在 Store 中通过 computed selector 驱动（行为类型非空且描述去除首尾空白后非空），按钮置灰状态由该校验结果派生，不发起请求。
2. **提交请求**（`submitting` → `streaming`/`submit_failed`）：通过 `httpClient`（AUTH-06 提供 Token 自动注入）POST 后端咨询入口 API，组装 `ConsultSubmitRequest`（含行为类型列表和行为描述文本）为请求体。请求成功且 SSE 首个 chunk 到达后，状态切至 `streaming`；请求失败（网络异常或 HTTP 5xx）则切至 `submit_failed`，但用户输入保留在 Store 中不丢失。
3. **流式消费**（`streaming` → `completed`/`stream_failed`）：SSE 解析器逐行解析 `chunk` 事件，将 `text` 字段追加到 `accumulatedText`，通过正则检测四段式 Markdown 标题行（`## 即时安全干预动作` / `## 情绪安抚话术` / `## 后续观察指标` / `## 就医判断标准`）判定段落边界，将文本分配至对应 `PlanSection`。`done` 事件到达后状态切至 `completed`；连接中断且 3 次重连耗尽后切至 `stream_failed`。
4. **结果展示**（`completed` → `ticket_guide`/`selecting_behavior`）：后端在 SSE `done` 事件之后立即通过最终 API 响应携带 CSLT-05 的 `ConfidenceValidationOutput`。全局置信度校验结果到达时，Store 即时计算工单引导标记（`confidenceScore < 0.7` 或 `validationVerdict === 'FORCE_BLOCK'` 时展示），并通过 `ticket_guide_shown` 布尔标记去重——确保工单卡片在一次会话中仅展示一次。家属可选择点击"联系专家"跳转至 TICK-09 工单模块，或点击"开始新咨询"切回 `selecting_behavior`。
5. **异常恢复**（`submit_failed`/`stream_failed` → `idle`/`submitting`）：提交失败时展示重试和返回按钮，用户输入保留；流传输失败时已接收的部分内容以 `isPartial=true` 标记保留在消息列表中，不完整方案段落标注 `isCompleted=false`。

**消息列表的生命周期管理**：消息列表上限 200 条，通过 Zustand `persist` 中间件持久化到 Taro Storage。裁剪策略为截断式——当消息数达到 200 条的瞬间（在 `addMessage` action 中检测），调用 `messages.slice(50)` 移除最早 50 条，裁剪后保持 150 条。裁剪操作在内存中先行完成，中间件的异步写 Storage 紧随其后，两者之间不产生新的消息插入窗口（因为裁剪在 `set()` 原子操作内完成）。

**降级与容错设计**：整个编排流程有三层降级保障。(1) SSE 连接中断时，3 次指数退避重连（1s/2s/5s），每次重连携带 `Last-Event-Id`（映射已接收的最大 sequence 号）告知 CSLT-04 从中断位置续传。(2) SSE 流 20s 无数据时触发软超时——在前端推送"正在生成建议，请稍候"进度提示，但不终止连接。(3) 工单兜底：CSLT-05 输出 `ticket_creation_failed=true`（后端已重试 3 次失败）时，前端仍展示手动发起工单的引导提示——降级为家属手动触发而非全自动创建，确保安全底线不丢失。

（与意图文档一致性说明）: 以上五阶段流程精确对应意图文档 §1.5 用户旅程的 8 个步骤。八种状态的合法转换路径和咨询互斥规则（§1.7）通过 §1.4 状态机设计严格兑现。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：CSLT-01~06 设计文档与落地规范（全部已冻结）、AUTH-06 落地规范、PROF-07 意图文档、TICK-09 意图文档、项目结构设计 §6.1（L1b logics/consult/）、技术栈设计 §2、契约索引 `_contracts.md`（17 个已发布模块）
- **兼容性结论**：**无冲突**。CSLT-08 是纯前端逻辑层模块，不定义新的后端 API 契约。全部输入类型（`BehaviorTypeCategory`、`CrisisLevel`、`ChunkEvent`/`DoneEvent`/`ErrorEvent`/`HeartbeatEvent`、`ValidationVerdict`、`ConsultationHistoryCreate` 等）均直接消费已有模块的已锁定契约，无新增类型冲突。兼容性保障方式：(1) 后端契约类型在前端通过 TypeScript 接口精确映射，映射关系的维护集中在 `logics/consult/types/` 单一文件中；(2) SSE 事件格式与 CSLT-04 契约的 `ChunkEvent`/`DoneEvent`/`ErrorEvent`/`HeartbeatEvent` JSON Schema 严格对齐，字段名和下划线命名风格保持一致；(3) 状态枚举值（如 `BehaviorTypeCategory` 的 `SELF_INJURY` 等）使用后端契约的原始字符串值，不进行二次映射。

- **复用的已有设计**：
  - CSLT-01 `BehaviorTypeCategory`（七类行为类型枚举）和 `CrisisLevel`（三级危机等级）
  - CSLT-04 SSE 四种事件类型（`ChunkEvent`/`DoneEvent`/`ErrorEvent`/`HeartbeatEvent`）及 `StreamErrorCode` 枚举
  - CSLT-05 `ValidationVerdict`（通过/追加警告/强制阻断）和 `ConfidenceValidationOutput` 结构
  - CSLT-06 `ConsultationHistoryCreate` 归档写入模型、`ConsultationHistoryListItem`/`ConsultationHistoryDetail` 查询响应模型
  - AUTH-06 `httpClient`（Token 自动注入）和 `tokenManager`（Token 存储与刷新）
  - 项目级 `PaginatedResponse` 分页类型（历史列表查询）

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| CSLT-07 应急咨询界面 | 下游渲染消费（L1a 依赖 L1b） | 通过 `useConsult()` Hook 向 CSLT-07 暴露消息列表、会话状态、流式进度、工单引导标记、操作方法（`submitConsult`、`retryConsult`、`startNewConsult` 等）。Hook 返回值的类型定义见落地规范 §1.7 |
| CSLT-04 流式应答推送 | 下游服务消费（SSE 流） | 通过 fetch streaming API 连接 `/api/v1/consult/stream` 端点，手动解析 SSE 协议。接收 `ChunkEvent`（文本增量）、`DoneEvent`（流终止）、`ErrorEvent`（错误）、`HeartbeatEvent`（保活）。连接超时 10s，流无数据软超时 20s |
| CSLT-01 危机分级判定 | 下游服务消费（后端 Pipeline 内部调用） | 前端提交时组装 `CrisisJudgmentRequest`（行为类型 + 描述文本）通过 POST API 传入，后端 Pipeline 内部调用 CSLT-01。前端不直接调用 CSLT-01——结果通过 API 响应携带 |
| CSLT-05 置信度后校验 | 下游服务消费（后端 Pipeline 内部调用） | 接收 API 响应中的 `ConfidenceValidationOutput`（confidence_score、verdict、ticket_triggered）。在前端 Store 中基于这些值计算工单引导标记，不直接调用 CSLT-05 接口 |
| CSLT-06 咨询历史管理 | 双向交互 | **归档写入**：每次咨询 completed 后通过 POST `/api/v1/consultations` 传入 `ConsultationHistoryCreate`，携带 `request_id` 幂等键；**历史查询**：GET 列表和详情，只读渲染 |
| TICK-09 工单交互逻辑 | 下游触发（前端路由跳转） | 工单引导卡片中"联系专家"按钮点击后，通过 `Taro.navigateTo` 跳转至工单模块路由，传递当前咨询的上下文参数（`request_id`）。不直接调用 TICK-09 的 Store 或 API |
| AUTH-06 认证会话管理 | 横向基础设施依赖 | 依赖 `httpClient` 的请求拦截器自动注入 JWT Access Token 和 401 自动续期。依赖 `tokenManager` 保证 API 调用携带有效认证凭证 |
| PROF-07 档案数据逻辑 | 条件调用依赖 | 冷启动检测：新用户无档案时通过 PROF-07 触发档案引导流程。事件沉淀：每次咨询后通过 PROF-07 弹出微问卷 |

### 1.4 状态机设计（技术实现策略）

CSLT-08 管理咨询会话的 8 种业务状态（`ConsultSessionState` 联合类型），12 条法定转换路径（`LEGAL_TRANSITIONS` 映射表）。

**技术实现策略**：在 Zustand Store 中，状态转换为纯函数校验模式——`transitionTo(newState)` action 内先通过 `get()` 读取当前状态，查 `LEGAL_TRANSITIONS[currentState]` 判断 `newState` 是否在允许列表中。若非法，抛出 `StateTransitionError` 并记录结构化日志；若合法，通过 `set()` 原子更新状态字段。

**为什么用查找表而非 if/switch**：8 个状态 × 12 条转换的规模下，查找表的可读性和可维护性优于嵌套分支。新增状态或转换路径时只需修改一处数据定义，控制流代码不变。查找表本身是纯数据，可被单元测试遍历验证。

**并发防护**：利用 Zustand `set()` 的原子更新特性，在 `transitionTo` 中先 `get()` 后 `set()` 两个操作，虽然在单次 action 内但跨两次调用——需要通过 `get()` 验证的当前状态与 `set()` 写入之间不会被其他 action 修改（Zustand 批量更新机制保证同一事件循环内的 action 按提交顺序执行）。同状态重复转换（如连续两次 `transitionTo('streaming')`）通过 `if (get().sessionState === newState) return` 提前返回，静默忽略，避免不必要的日志噪音和界面闪烁。

**咨询互斥的技术实现**：在 `submitConsult` action 入口，通过 `get().sessionState` 检查——若当前状态为 `submitting` 或 `streaming`，直接返回错误（携带统一提示文案键值 `CONCURRENT_SUBMIT_BLOCKED`），不进入任何异步操作。此检查在 action 的最外层执行，不存在绕过窗口。

```
idle ──start_consult──▶ selecting_behavior ──cancel──▶ idle
                            │
                            └──submit──▶ submitting ──sse_connected──▶ streaming
                                              │                          │
                                              └──request_fail──▶         ├──sse_done──▶ completed
                                                 submit_failed           │                  │
                                                 │  │                    │                  ├──ticket_trigger──▶ ticket_guide
                                                 │  └──retry──▶          │                  │                        │
                                                 │     submitting        │                  └──start_new──▶          │
                                                 └──go_back──▶ idle      │               selecting_behavior ◀───────┘
                                                                         └──sse_fail──▶
                                                                            stream_failed
                                                                            │          │
                                                                            └──retry──▶ submitting
                                                                            │
                                                                            └──go_back──▶ idle
```

**状态持久化决策**：`sessionState` 字段不持久化——会话状态时效性强，页面关闭后从 CSLT-06 历史只读浏览，不存在恢复需求。`messages` 消息列表（当前会话）通过 Zustand `persist` 中间件持久化到 Taro Storage，页面关闭后重新打开可恢复，但新咨询时清空。

### 1.5 设计原则兑现清单（技术视角）

| 原则编号 | 原则名称 | 技术响应 |
|----------|----------|----------|
| 2.1 | 单一职责 | CSLT-08 仅负责"应急咨询前端流程编排与状态管理"。不负责 UI 渲染（归属 CSLT-07）、SSE 协议传输（归属 CSLT-04）、危机判定逻辑（归属 CSLT-01）、内容生成质量（归属 CSLT-03）、置信度校验（归属 CSLT-05）、数据持久化（归属 CSLT-06）。五阶段编排中每个阶段通过明确的状态转换隔离，阶段间互不越界 |
| 2.2 | 接口隔离 | 对上游 CSLT-07，仅通过 `useConsult()` Hook 暴露稳定接口——Hook 返回类型为精确类型（含 sessionState、messages、planSections、ticketGuide 等），不暴露 Store 实例或内部 action 实现。CSLT-07 组件通过 selector 精准订阅所需字段，单个字段变更不触发无关组件的重渲染 |
| 2.3 | 分层恪守 | CSLT-08 位于 L1b（前端逻辑层），严格遵守项目结构 §9.4 的 views/logics 分层规则——不包含任何 JSX/TSX 渲染代码、不引用 Taro UI 组件库、不包含样式定义。所有 UI 状态变更通过 Hook 返回值驱动 CSLT-07 的表现层渲染，不直接操作 DOM 或 Taro 页面实例 |
| 3.1 | 异常可见 | 全部 6 类前端异常场景（输入校验不通过、提交网络错误、提交服务端错误、SSE 连接中断、SSE 流无数据超时、工单创建失败）均在 Store 中有明确的错误状态或标记字段，通过 `ConsultErrorCode` 枚举映射唯一的中文提示文案键值。异常发生时，状态转换（提交失败/流传输失败）对 CSLT-07 完全可见，不静默吞掉异常 |
| 3.2 | 可观测性 | 关键操作通过 `console.debug` 输出结构化日志，包含：状态转换（fromState、toState、timestamp）、SSE 事件接收（sequence、text_length、latency_ms）、消息裁剪触发（before_count、after_count）、工单引导触发（trigger_reason、confidence_score）。日志仅用于开发调试，生产环境可通过条件编译去除 |
| 4.1 | 资源可控 | 消息列表硬上限 200 条（触发后裁至 150 条，详见 §1.1）；SSE 重连上限 3 次（指数退避 1s/2s/5s，不无限重试）；流无数据软超时 20s（仅推送提示不终止连接）；连接超时 10s（与 httpClient 默认一致）；同一时刻仅允许一个活跃咨询会话（互斥规则） |

> 原则编号参考项目级设计原则体系（技术栈设计 §4）。

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| 状态管理 | Zustand 5.x 单一 Store Slice | useReducer + Context | Zustand selector 模式支持细粒度订阅，8 状态 + 消息列表 + SSE 状态的跨组件共享效率优于 Context。项目技术栈已确定 Zustand 5.x，不引入新库。参见 tech-decision-report 决策 1 |
| SSE 消费方式 | fetch streaming API + 自实现 SSE 解析器 | 浏览器 EventSource API | Taro 小程序环境不支持原生 EventSource。自实现解析器可精确控制 chunk 边界、心跳检测和错误处理。约 80 行额外代码换取完整跨平台兼容性。参见 tech-decision-report 决策 2 |
| 段落边界检测 | 正则匹配 CSLT-03 固定 Markdown 标题行 | LLM 意图识别 / NLP 语义切分 | CSLT-03 Prompt 模板中四段标题为固定硬编码字符串，正则 O(n) 匹配即可，无需引入 NLP 或 LLM 的额外调用延迟和成本。依赖风险：CSLT-03 修改 Prompt 模板时需同步更新正则模式。参见 tech-decision-report 决策 3 |
| 状态机实现 | LEGAL_TRANSITIONS 查找表 + transitionTo() guard | XState 状态机库 | 8 状态 12 转换的规模不需要引入外部状态机库。查找表为纯数据，可读性强、易于测试。XState 增加约 19KB（gzip 后）构建体积，且心智模型与项目统一的 Zustand 生态重叠。参见 tech-decision-report 决策 5 |
| 工单引导触发 | 置信度校验结论到达时立即触发 + Store 去重标记 | SSE 流结束后延迟触发 | 置信度数据在 SSE `done` 事件之后的 API 响应中携带，自然到达时间为流结束时刻。延迟触发无获得额外收益，反而增加等待体验。`ticket_guide_shown` 去重标记确保同一会话多次收到置信度结果（如重连后重复推送）不会重复展示工单卡片。参见 tech-decision-report 决策 6 |
| 消息持久化 | Zustand persist 中间件 + Taro Storage 适配器 | 手动读写 Taro Storage / 不可持久化 | Zustand 5.x 内建 persist 中间件，仅需自定义 `storage` 适配器（`createJSONStorage` + `Taro.getStorageSync`/`setStorageSync`）即可开箱使用。内存 + 持久化双副本：运行时零序列化开销，仅变更时异步写 Storage。参见 tech-decision-report 决策 7 |
| 页面结构 | 单页面内步骤切换（通过 `visible` 控制） | 独立路由页面跳转 | 行为类型选择 → 描述输入 → 等待生成三步之间共享状态（选择结果需传给输入步骤），Zustand Store 天然支持跨步骤状态保持，不依赖路由参数传递。单页面避免小程序页面栈深度限制（Taro 默认最多 10 层）和返回时的状态丢失。此决策涉及产品交互模式（受意图文档约束），留待用户确认（见 §1.7 待裁决项 2） |

### 1.7 注意事项与禁止行为（设计层面）

1. **[设计边界 — 后端逻辑归属]** CSLT-08 不负责后端 RAG 检索（CSLT-02）、LLM 生成（CSLT-03）、危机判定（CSLT-01）和置信度校验（CSLT-05）的具体业务逻辑。CSLT-08 仅通过组装前端输入参数、调用后端统一 API、消费 SSE 流和 API 响应来间接协调这些模块的协作。禁止在 Store 或 Hook 中实现任何语义检索、文本生成、关键词匹配判定的逻辑。

2. **[设计边界 — UI 归属]** CSLT-08 不包含任何 UI 渲染代码。消息气泡样式、按钮样式、应急模式颜色切换、流式文本的逐句动画——这些全部归属 CSLT-07。CSLT-08 仅提供数据（`planSections`、`sessionState`、`ticketGuide`）和操作方法，由 CSLT-07 通过 `useConsult()` Hook 读取并自行决定渲染方式。

3. **[设计边界 — 认证归属]** CSLT-08 不直接管理 Token 和登录状态。所有 API 调用通过 `httpClient`（AUTH-06 提供）完成，Token 注入、401 自动续期、续期失败跳转登录页等全部由 AUTH-06 在拦截器层面处理。CSLT-08 的代码中不应出现 `Taro.getStorageSync('access_token')` 等直接操作 Token 的调用。

4. **[易错点 — 状态机并发]** `transitionTo` action 内部仅做校验 + 状态写入，不应包含异步操作。所有异步操作（API 调用、SSE 连接）应在业务 action（如 `submitConsult`）中完成，成功后调用 `transitionTo` 完成状态转换。禁止在 `transitionTo` 中发起网络请求，也禁止在异步操作完成前调用 `transitionTo`——这会导致状态与实际业务进展不一致。

5. **[易错点 — SSE 解析的跨平台差异]** 微信小程序 iOS 和 Android 对 `Taro.request` 的流式响应处理行为有差异——iOS 端可能将多个 SSE 事件合并到单次回调，Android 端可能对二进制帧的缓冲策略不同。自实现的 SSE 解析器必须在两个平台上做充分兼容性测试——特别是行分隔符（`\n\n`）的识别和跨 chunk 边界的事件拼接。若平台限制无法通过 `Taro.request` 实现可靠流传输，降级方案为通过 `wx.connectSocket` WebSocket 通道模拟文本流，但需同步调整 CSLT-08 适配层，其他业务逻辑不变。

6. **[禁止行为 — 绕过状态机]** 禁止在任何组件、Hook 或 action 中直接修改 `sessionState` 字段（`set({ sessionState: 'xxx' })`）。所有状态变更必须通过 `transitionTo(newState)` 执行，确保 `LEGAL_TRANSITIONS` 校验被强制执行。即便是内部测试 mock，也应遵循此规则——否则可能在热更新或异步竞态下绕过守卫。

7. **[禁止行为 — 无限制重试]** 禁止在 SSE 重连逻辑中设置无上限重试或过短间隔。重连策略硬编码为 3 次上限（1s/2s/5s 指数退避），不可通过配置项或参数调整——这是为了保护后端 CSLT-04 的资源不被恶意或意外的大量重连请求淹没，也与意图文档 AC-03 的"3 次重连内"验收标准一致。

8. **[待裁决项 1 — 网络超时阈值]** 当前设计采用：连接超时 10s（与 `httpClient` 默认一致）、流无数据软超时 20s（超过 SSE 心跳 15s 的缓冲区间）。这是基于 CSLT-03 全流程 15s 超时和 CSLT-04 心跳 15s 间隔的合理推断，但具体毫秒阈值需用户确认——过短可能导致正常场景误中断，过长影响用户等待体验。此数值不影响架构设计，可在落地规范阶段通过配置项最终确定。

9. **[待裁决项 2 — 页面结构]** 当前设计采用：单页面内步骤切换（行为类型选择 → 描述输入 → 等待生成三者位于同一 Taro 页面，通过 `visible` 控制步骤切换），利用 Zustand Store 保持跨步骤状态。备选方案：三个独立页面通过 `Taro.navigateTo` 路由跳转，通过 Store 共享状态。两种方案的技术复杂度相近，当前选择基于避免小程序页面栈深度限制的考量，但最终方案涉及产品交互模式，需用户确认。

10. **[待裁决项 3 — 异常提示文案]** 当前设计采用以下默认文案（由 `ConsultErrorCode` 枚举映射）：
  - `INPUT_VALIDATION_FAILED` → "请至少选择一种行为类型，并填写行为描述"
  - `SUBMIT_NETWORK_ERROR` → "网络连接失败，请检查网络后重试"
  - `SUBMIT_SERVER_ERROR` → "服务暂时不可用，请稍后重试"
  - `SSE_CONNECTION_BROKEN` → "生成中断，以下为不完整建议，可能缺失部分段落"
  - `SSE_NO_DATA_TIMEOUT` → "正在生成建议，请稍候"
  - `CONCURRENT_SUBMIT_BLOCKED` → "当前正在生成建议，请等待完成后再发起新的咨询"
  - `TICKET_CREATION_FAILED` → "如需专家帮助，可手动发起工单"

  应急场景下家属处于焦虑状态，文案措辞涉及产品体验和情感关怀，需产品方确认。此文案清单不影响架构决策，可在落地规范阶段或前端实现阶段最终确定。

### 1.8 引用：配套意图文档

- **意图文档**：`CSLT-08-咨询编排逻辑-意图文档.md`
- **冻结时间**：`2026-05-27 21:37:16`（v2.0）
- **本次设计依赖的技术预研报告**：`.tmp/reports/tech-decision-report-CSLT-08.md`（s06-spec-research 产出，7 项自主决策 + 3 项业务矛盾标记）
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。8 种业务状态与 12 条法定转换路径（§1.4）精确对应意图文档 §1.7 的状态转换定义；五阶段流程编排（§1.1）精确对应意图文档 §1.5 用户旅程的 8 个步骤；3 种异常策略（§1.3 依赖表 + §1.7 待裁决项）覆盖意图文档 §1.8 的全部异常场景。如有歧义，以意图文档为准。
