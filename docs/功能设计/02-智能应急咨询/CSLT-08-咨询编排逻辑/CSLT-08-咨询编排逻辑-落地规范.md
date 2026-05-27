## 1 功能点：CSLT-08 咨询编排逻辑 — 落地规范

> **文档生成时间**：`2026-05-27 21:50:00`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-27 21:50:00` | AI Assistant | 初始版本，基于已冻结意图文档 v2.0、设计文档 v1.0、契约协调报告全量生成 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `CSLT-08-咨询编排逻辑-设计文档.md`。

### 1.1 技术栈绑定【对内实现】

- **必须使用**：
  - `Taro >= 4.0`：微信小程序跨端框架，`Taro.request` 用于 HTTP 请求，`Taro.navigateTo` 用于页面跳转，`Taro.setStorageSync`/`Taro.getStorageSync` 用于持久化
  - `React >= 18.0`：UI 框架，Hook 写法（`useCallback`、`useMemo`、`useEffect`）
  - `Zustand >= 5.0`：前端状态管理，使用 `create()` 创建 Store，`persist` 中间件持久化消息列表
  - `TypeScript >= 5.0`：类型系统，所有 Store/接口/工具函数必须有类型标注
  - `@campfire/shared`（项目级共享包，推断）：如存在则从中导入 `BehaviorTypeCategory`、`CrisisLevel` 等共享枚举；如尚不存在则在 `logics/consult/types/` 中自维护枚举映射
  - `logics/shared/services/httpClient.ts`：统一 HTTP 客户端，Token 自动注入和 401 续期

- **禁止使用**：
  - 禁止使用 `EventSource` API 或任何浏览器原生 SSE 库——Taro 环境不支持，使用 fetch streaming 自解析
  - 禁止使用 `xstate` 或其他状态机库——8 状态规模不需要外部库，查找表即可
  - 禁止在 Store action 中直接操作 Taro 页面实例或 DOM——所有 UI 控制通过 Hook 返回值暴露
  - 禁止使用 `asyncio` 或任何 Python 库——纯前端 TypeScript 模块
  - 禁止在 Store 中硬编码中文提示文案——使用 `ConsultErrorCode` 枚举 + 映射表统一管理

### 1.2 文件归属【对内实现】

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 状态管理 Store | `apps/mini-program/src/logics/consult/store/useConsultStore.ts` | Zustand Store：管理全部 8 状态 + 消息列表 + SSE 流式数据。导出 `useConsultStore` hook 和 `transitionTo`、`submitConsult`、`addMessage` 等 action |
| TypeScript 类型定义 | `apps/mini-program/src/logics/consult/types/index.ts` | 全部前端类型定义：`ConsultSessionState`、`ConsultSessionStateData`、`MessageItem`、`PlanSection`、`StructuredPlan`、`TicketGuide`、`ConsultSubmitRequest`、`ConsultErrorCode`、`StateTransitionError` |
| SSE 解析器 | `apps/mini-program/src/logics/consult/services/sseParser.ts` | `SseStreamParser` 类：fetch streaming 响应体的 SSE 协议手动解析，含 chunk 边界检测、心跳判定、指数退避重连 |
| API 服务层 | `apps/mini-program/src/logics/consult/services/consultApi.ts` | `consultApi` 对象：封装咨询相关全部 HTTP 请求（POST 提交咨询、GET 历史列表、GET 历史详情），通过 `httpClient` 发请求 |
| useConsult Hook | `apps/mini-program/src/logics/consult/hooks/useConsult.ts` | 导出 `useConsult()` Hook：CSLT-07 的唯一桥接接口，通过 Zustand selector 暴露状态和操作方法 |
| 状态转换守卫 | `apps/mini-program/src/logics/consult/store/stateMachine.ts` | `LEGAL_TRANSITIONS` 查找表 + `getErrorMessage(errorCode)` 文案映射 + `createMessageItem()` 工厂函数 |
| 单元测试 | `apps/mini-program/src/logics/consult/__tests__/useConsultStore.test.ts` | Zustand Store 的单元测试：状态转换合法/非法路径、消息裁剪、并发防护 |
| SSE 解析器测试 | `apps/mini-program/src/logics/consult/__tests__/sseParser.test.ts` | SSE 解析器测试：chunk 边界、跨 chunk 事件拼接、心跳、重连逻辑 |
| 集成测试 | `apps/mini-program/src/logics/consult/__tests__/useConsult.integration.test.ts` | useConsult Hook 集成测试：完整咨询流程、异常恢复、工单引导触发 |

### 1.3 输入定义（契约引用格式）【已锁定】

**BehaviorTypeCategory**（七类行为类型，来源 CSLT-01）
- 【契约引用】`docs/contracts/CSLT-01/BehaviorTypeCategory.json`
- 本模块作为该契约的定义方：否（CSLT-01 定义）
- 消费方：CSLT-08（家属在 `selecting_behavior` 状态下的勾选枚举值来源）
- 前端映射：TypeScript union type `'SELF_INJURY' | 'AGGRESSION' | 'ELOPEMENT' | 'MEDICATION' | 'EMOTIONAL_MELTDOWN' | 'STEREOTYPY' | 'OTHER'`

**CrisisLevel**（三级危机等级，来源 CSLT-01）
- 【契约引用】`docs/contracts/CSLT-01/CrisisLevel.json`
- 本模块作为该契约的定义方：否（CSLT-01 定义）
- 消费方：CSLT-08（通过 API 响应间接接收，用于应急模式 UI 切换）

**ChunkEvent**（SSE 文本增量事件，来源 CSLT-04）
- 【契约引用】`docs/contracts/CSLT-04/ChunkEvent.json`
- 本模块作为该契约的定义方：否（CSLT-04 定义）
- 消费方：CSLT-08（SSE 解析器逐行解析 `text` 和 `sequence` 字段，追加到 `accumulatedText`）

**DoneEvent**（SSE 流终止事件，来源 CSLT-04）
- 【契约引用】`docs/contracts/CSLT-04/DoneEvent.json`
- 本模块作为该契约的定义方：否（CSLT-04 定义）
- 消费方：CSLT-08（收到后触发 `transitionTo('completed')`）

**ErrorEvent**（SSE 错误事件，来源 CSLT-04）
- 【契约引用】`docs/contracts/CSLT-04/ErrorEvent.json`
- 本模块作为该契约的定义方：否（CSLT-04 定义）
- 消费方：CSLT-08（读取 `error_code` 判断错误类型并展示对应提示）

**HeartbeatEvent**（SSE 心跳保活事件，来源 CSLT-04）
- 【契约引用】`docs/contracts/CSLT-04/HeartbeatEvent.json`
- 本模块作为该契约的定义方：否（CSLT-04 定义）
- 消费方：CSLT-08（用于连接活性监控，15s 无事件判定为僵死）

**StreamErrorCode**（SSE 错误码枚举，来源 CSLT-04）
- 【契约引用】`docs/contracts/CSLT-04/StreamErrorCode.json`
- 本模块作为该契约的定义方：否（CSLT-04 定义）
- 消费方：CSLT-08（读取 ErrorEvent.error_code 时引用此枚举值）

**ValidationVerdict**（置信度校验结论，来源 CSLT-05）
- 【契约引用】`docs/contracts/CSLT-05/ValidationVerdict.json`
- 本模块作为该契约的定义方：否（CSLT-05 定义）
- 消费方：CSLT-08（读取 `ConfidenceValidationOutput.verdict` 时引用此枚举值）

**ConfidenceValidationOutput**（置信度校验输出，来源 CSLT-05）
- 【契约引用】`docs/contracts/CSLT-05/ConfidenceValidationOutput.json`
- 本模块作为该契约的定义方：否（CSLT-05 定义）
- 消费方：CSLT-08（在 API 响应中接收，读取 `confidence_score`、`verdict`、`ticket_triggered`、`ticket_creation_failed`）

**ConsultationHistoryCreate**（咨询归档写入模型，来源 CSLT-06）
- 【契约引用】`docs/contracts/CSLT-06/ConsultationHistoryCreate.json`
- 本模块作为该契约的定义方：否（CSLT-06 定义）
- 消费方：CSLT-08（每次咨询 `completed` 后组装此对象并通过 POST 写入 CSLT-06）

**ConsultationHistoryListItem**（咨询历史列表条目，来源 CSLT-06）
- 【契约引用】`docs/contracts/CSLT-06/ConsultationHistoryListItem.json`
- 本模块作为该契约的定义方：否（CSLT-06 定义）
- 消费方：CSLT-08（历史列表查询的响应数据类型）

**ConsultationHistoryDetail**（咨询历史详情，来源 CSLT-06）
- 【契约引用】`docs/contracts/CSLT-06/ConsultationHistoryDetail.json`
- 本模块作为该契约的定义方：否（CSLT-06 定义）
- 消费方：CSLT-08（历史详情查询的响应数据类型，只读渲染）

**httpClient**（前端 HTTP 客户端，来源 AUTH-06）
- 【契约引用】`docs/contracts/AUTH-06/httpClient.json`
- 本模块作为该契约的定义方：否（AUTH-06 定义）
- 消费方：CSLT-08（通过 `httpClient.request` 发送所有 API 请求）

**SessionState (AUTH-06)**（认证会话状态，来源 AUTH-06）
- 【契约引用】`docs/contracts/AUTH-06/SessionState.json`
- 本模块作为该契约的定义方：否（AUTH-06 定义）
- 消费方：CSLT-08（通过 `useAuth()` Hook 感知登录/登出/续期中状态变更）
- 注意：此 `SessionState` 与 CSLT-08 自有的 `ConsultSessionState` 不同，前者管理认证会话（authenticated/refreshing/unauthenticated），后者管理咨询业务会话（8 种业务状态）

**内部输入类型**（不对外暴露）：

```typescript
// logics/consult/types/index.ts

/** 咨询输入表单状态 */
interface ConsultInputState {
  /** 家属勾选的行为类型列表，至少 1 项 */
  behaviorTypeSelection: BehaviorTypeCategory[];
  /** 家属输入的行为描述文本，去除首尾空白后非空 */
  behaviorDescription: string;
}

/** 提交给后端 API 的咨询请求体 */
interface ConsultSubmitRequest {
  behavior_type_selection: BehaviorTypeCategory[];
  behavior_description: string;
}

/** 消息条目唯一标识，格式 msg-{uuid4} */
type MessageId = string;
```

### 1.4 输出定义（契约引用格式）【已锁定】

**useConsult Hook 返回值**（CSLT-08 对 CSLT-07 的唯一输出接口）
- 本模块作为该接口的定义方：是（CSLT-08 定义并实现）
- 类型名称：`UseConsultReturn`（前端 TypeScript 接口）
- 消费方：CSLT-07（应急咨询界面通过 `useConsult()` Hook 消费全部状态和操作方法）

**内部输出类型**（完整定义）：

```typescript
// logics/consult/types/index.ts

/** 咨询会话业务状态 */
type ConsultSessionState =
  | 'idle'
  | 'selecting_behavior'
  | 'submitting'
  | 'streaming'
  | 'completed'
  | 'ticket_guide'
  | 'submit_failed'
  | 'stream_failed';

/** 消息发送方 */
type MessageSender = 'user' | 'system';

/** 消息类型 */
type MessageType = 'user_input' | 'system_plan' | 'system_prompt' | 'ticket_card';

/** 单条消息 */
interface MessageItem {
  /** 消息唯一标识，格式 msg-{uuid4} */
  id: MessageId;
  /** 发送方 */
  sender: MessageSender;
  /** 消息文本内容 */
  content: string;
  /** ISO 8601 时间戳 */
  timestamp: string;
  /** 消息类型 */
  messageType: MessageType;
  /** 消息元数据（可选） */
  metadata?: {
    /** 段落标题，仅 system_plan 消息有值 */
    sectionTitle?: string;
    /** 段落是否已完成 */
    isCompleted?: boolean;
    /** 是否不完整（流传输失败场景） */
    isPartial?: boolean;
    /** 是否为 AI 原始建议（区别于系统追加的安全提示） */
    isOriginal?: boolean;
  };
}

/** 单个方案段落 */
interface PlanSection {
  /** 段落标题（四段之一） */
  title: string;
  /** 文本内容列表，每个元素为一个已完成的句子 */
  contents: string[];
  /** 段落是否已全部接收完成 */
  isCompleted: boolean;
}

/** 四段式结构化方案 */
interface StructuredPlan {
  sections: PlanSection[];
}

/** 工单引导标记 */
interface TicketGuide {
  /** 是否应展示工单引导卡片 */
  show: boolean;
  /** 风险等级：普通或高风险 */
  riskLevel: TicketRiskLevel;
}

/** 工单引导风险等级 */
type TicketRiskLevel = 'normal' | 'high_risk';

/** 咨询会话完整状态（驱动 UI 的数据结构） */
interface ConsultSessionStateData {
  /** 当前会话状态 */
  sessionState: ConsultSessionState;
  /** 当前勾选的行为类型（跨步骤保持） */
  behaviorTypeSelection: BehaviorTypeCategory[];
  /** 当前输入的行为描述（跨步骤保持） */
  behaviorDescription: string;
  /** 已接收的完整文本（SSE 累积） */
  accumulatedText: string;
  /** 已解析的四段式方案段落 */
  planSections: PlanSection[];
  /** SSE 流最后接收的 sequence 号，初始 0 */
  lastSequence: number;
  /** 危机等级（API 响应后填充） */
  crisisLevel?: CrisisLevel;
  /** 置信度分数（API 响应后填充） */
  confidenceScore?: number;
  /** 校验结论（API 响应后填充） */
  validationVerdict?: ValidationVerdict;
  /** 工单引导状态 */
  ticketGuide: TicketGuide;
  /** 整个会话的消息列表 */
  messages: MessageItem[];
  /** 当前错误码（有错误时填充） */
  errorCode?: ConsultErrorCode;
  /** 工单引导是否已展示过（去重标记） */
  ticketGuideShown: boolean;
}

/** 前端异常错误码枚举 */
enum ConsultErrorCode {
  INPUT_VALIDATION_FAILED = 'INPUT_VALIDATION_FAILED',
  SUBMIT_NETWORK_ERROR = 'SUBMIT_NETWORK_ERROR',
  SUBMIT_SERVER_ERROR = 'SUBMIT_SERVER_ERROR',
  SSE_CONNECTION_BROKEN = 'SSE_CONNECTION_BROKEN',
  SSE_NO_DATA_TIMEOUT = 'SSE_NO_DATA_TIMEOUT',
  CONCURRENT_SUBMIT_BLOCKED = 'CONCURRENT_SUBMIT_BLOCKED',
  TICKET_CREATION_FAILED = 'TICKET_CREATION_FAILED',
}

/** 状态转换异常 */
class StateTransitionError extends Error {
  fromState: ConsultSessionState;
  toState: ConsultSessionState;
  constructor(from: ConsultSessionState, to: ConsultSessionState) {
    super(`非法状态转换: ${from} -> ${to}`);
    this.name = 'StateTransitionError';
    this.fromState = from;
    this.toState = to;
  }
}

/** useConsult Hook 的完整返回值类型 */
interface UseConsultReturn {
  // ---------- 只读状态（CSLT-07 渲染用） ----------
  /** 当前会话业务状态 */
  sessionState: ConsultSessionState;
  /** 消息列表 */
  messages: MessageItem[];
  /** 四段式方案段落（流式接收中实时更新） */
  planSections: PlanSection[];
  /** 已累积的原始文本 */
  accumulatedText: string;
  /** 工单引导标记 */
  ticketGuide: TicketGuide;
  /** 当前错误码 */
  errorCode?: ConsultErrorCode;
  /** 输入是否有效（行为类型 ≥1 且描述非空） */
  isInputValid: boolean;
  /** 是否处于活跃咨询中（禁止新提交） */
  isConsultActive: boolean;

  // ---------- 操作方法（CSLT-07 绑定到按钮/事件） ----------
  /** 开始新咨询：idle -> selecting_behavior */
  startConsult: () => void;
  /** 更新行为类型选择（selecting_behavior 状态下可用） */
  setBehaviorTypes: (types: BehaviorTypeCategory[]) => void;
  /** 更新行为描述文本 */
  setBehaviorDescription: (desc: string) => void;
  /** 提交咨询：selecting_behavior -> submitting */
  submitConsult: () => Promise<void>;
  /** 取消行为选择：selecting_behavior -> idle */
  cancelSelection: () => void;
  /** 重试提交：submit_failed -> submitting */
  retrySubmit: () => Promise<void>;
  /** 返回空闲：submit_failed | stream_failed -> idle */
  goBackToIdle: () => void;
  /** 重试流式接收：stream_failed -> submitting（重新生成） */
  retryStream: () => Promise<void>;
  /** 开始新一轮咨询：completed | ticket_guide -> selecting_behavior */
  startNewConsult: () => void;
  /** 跳转工单模块：ticket_guide 状态下触发 Taro.navigateTo */
  goToTicket: () => void;
  /** 获取错误提示文案 */
  getErrorMessage: (code: ConsultErrorCode) => string;
  /** 获取历史咨询列表 */
  fetchHistoryList: (page: number, pageSize: number) => Promise<ConsultationHistoryListItem[]>;
  /** 获取历史咨询详情（只读） */
  fetchHistoryDetail: (consultationId: string) => Promise<ConsultationHistoryDetail>;
}
```

### 1.5 核心逻辑步骤【对内实现】

1. **步骤 1：开始新咨询**
   - **操作对象**：`sessionState` 状态字段
   - **具体操作**：调用 `startConsult()` action，检查当前状态为 `idle`，调用 `transitionTo('selecting_behavior')`，清空 `behaviorTypeSelection` 和 `behaviorDescription`，初始化 `messages` 为空数组（若从历史只读页面进入则保留当前消息）
   - **输入来源**：CSLT-07 组件触发（家属点击"开始咨询"按钮）
   - **输出去向**：状态变为 `selecting_behavior`，CSLT-07 通过 `useConsult()` 感知状态变更后渲染行为类型选择界面
   - **失败行为**：若非 `idle` 状态调用，静默忽略（不抛异常），因按钮已隐藏不可点击

2. **步骤 2：输入校验**
   - **操作对象**：`behaviorTypeSelection` 数组 + `behaviorDescription` 字符串
   - **具体操作**：`isInputValid` 为 Zustand computed selector，计算规则为 `behaviorTypeSelection.length >= 1 && behaviorDescription.trim() !== ''`。此 selector 在每次 `setBehaviorTypes()` 或 `setBehaviorDescription()` 后自动重新计算
   - **输入来源**：CSLT-07 组件通过 `setBehaviorTypes(types)` 和 `setBehaviorDescription(desc)` 更新 Store 字段
   - **输出去向**：`isInputValid` 布尔值驱动 CSLT-07 提交按钮的 `disabled` 属性
   - **失败行为**：校验不通过时按钮置灰，不发起请求。CSLT-07 根据缺失项展示对应提示（"请至少选择一种行为类型"/"请填写行为描述"）

3. **步骤 3：提交咨询请求**
   - **操作对象**：`ConsultSubmitRequest` 请求体 + HTTP POST 请求
   - **具体操作**：
     a. `submitConsult()` action 入口检查 `get().sessionState`，若为 `submitting` 或 `streaming` → 设置 `errorCode = CONCURRENT_SUBMIT_BLOCKED` 并 return
     b. 调用 `transitionTo('submitting')`
     c. 组装请求体 `{ behavior_type_selection: get().behaviorTypeSelection, behavior_description: get().behaviorDescription }`
     d. 通过 `httpClient.request({ method: 'POST', url: '/api/v1/consult', data: requestBody, timeout: 10000 })` 发出请求
     e. 请求成功 → 进入步骤 4（建立 SSE 连接）
     f. 请求失败 → 根据错误类型设置 `errorCode`（网络异常 → `SUBMIT_NETWORK_ERROR`，HTTP 5xx → `SUBMIT_SERVER_ERROR`），调用 `transitionTo('submit_failed')`
   - **输入来源**：Store 中的 `behaviorTypeSelection` 和 `behaviorDescription`
   - **输出去向**：API 响应触发步骤 4 的 SSE 连接建立，或转入 `submit_failed` 状态
   - **失败行为**：不自动重试（由用户点击"重试"触发）；用户输入保留在 Store 中不丢失

4. **步骤 4：建立 SSE 连接并流式消费**
   - **操作对象**：`SseStreamParser` 实例 + `accumulatedText` + `planSections` + `messages` + `lastSequence`
   - **具体操作**：
     a. 创建 `SseStreamParser` 实例，传入配置 `{ reconnectMaxRetries: 3, reconnectDelays: [1000, 2000, 5000], heartbeatTimeout: 15000, connectTimeout: 10000, streamNoDataTimeout: 20000 }`
     b. 调用 `transitionTo('streaming')`
     c. 调用 `parser.connect(url, { headers: { 'Last-Event-Id': String(get().lastSequence) } })` 发起连接
     d. 解析器内部事件处理：
        - `onChunk(data: ChunkEvent)` → 追加 `data.text` 到 `accumulatedText`，更新 `lastSequence = data.sequence`；调用 `parseSections(accumulatedText)` 重新解析段落边界；若首个 chunk（`lastSequence === 0`），在 `messages` 中创建 `system_plan` 类型消息并初始化段落标题
        - `onDone(data: DoneEvent)` → 调用 `transitionTo('completed')`；进入步骤 5
        - `onError(data: ErrorEvent)` → 根据 `data.error_code` 设置对应 `errorCode`；若为非致命错误（如 `STREAM_TIMEOUT`），记录日志不中断；若为致命错误（如 `GENERATION_FAILED`），设置 `transitionTo('stream_failed')`
        - `onHeartbeat()` → 重置心跳计时器
        - `onReconnect(attempt: number)` → 不改变状态，仅更新重连计数（供 CSLT-07 展示重连中的提示）
        - `onReconnectFailed()` → 调用 `transitionTo('stream_failed')`，标记 `planSections` 中所有未完成段落的 `isPartial = true`
        - `onNoDataTimeout()` → 设置 `errorCode = SSE_NO_DATA_TIMEOUT`（软提示，不终止连接）
     e. 段落解析逻辑（`parseSections`）：使用正则 `/#{1,3}\s*(即时安全干预动作|情绪安抚话术|后续观察指标|就医判断标准)/g` 检测标题行，将累积文本按标题切分为四段，更新 `planSections`
   - **输入来源**：SSE 端点 `/api/v1/consult/stream` 的 event-stream 响应体
   - **输出去向**：`accumulatedText`、`planSections`、`messages` 实时更新，CSLT-07 通过 selector 订阅后渲染
   - **失败行为**：3 次重连耗尽 → `transitionTo('stream_failed')`，已接收内容保留，`isPartial = true`

5. **步骤 5：处理咨询结果与工单引导**
   - **操作对象**：`ConfidenceValidationOutput`（API 响应体中携带）+ `ticketGuide` + `ticketGuideShown`
   - **具体操作**：
     a. SSE `done` 事件后，从同一 API 响应的 JSON body 中提取 `ConfidenceValidationOutput`
     b. 存储 `confidenceScore`、`validationVerdict`、`crisisLevel` 到 Store
     c. 计算工单引导：`shouldShow = (confidenceScore < 0.7 || validationVerdict === 'FORCE_BLOCK') && !ticketGuideShown`
     d. 若 `shouldShow`：调用 `transitionTo('ticket_guide')`，设置 `ticketGuide = { show: true, riskLevel: validationVerdict === 'FORCE_BLOCK' ? 'high_risk' : 'normal' }`，`ticketGuideShown = true`
     e. 若 `ticket_creation_failed === true`：设置 `errorCode = TICKET_CREATION_FAILED`，但仍展示手动工单引导提示（降级保障）
     f. 生成 `system_plan` 消息（或更新已有消息的 `isCompleted = true`），包含完整四段文本
     g. 触发归档：调用步骤 6
   - **输入来源**：API 响应的 JSON body（`ConfidenceValidationOutput` 结构）
   - **输出去向**：状态变为 `completed` 或 `ticket_guide`，CSLT-07 渲染结果和/或工单卡片
   - **失败行为**：若 API 响应中缺少置信度数据（异常），默认 `ticketGuide.show = false`（不做误触发），记录警告日志

6. **步骤 6：归档咨询记录**
   - **操作对象**：`ConsultationHistoryCreate` + POST 请求
   - **具体操作**：
     a. 组装 `ConsultationHistoryCreate` 对象（字段映射：`user_id` ← 从 `useAuth()` 获取，`consultation_time` ← `new Date().toISOString()`，`crisis_level` ← Store 中的 `crisisLevel`，`user_input` ← `behaviorDescription`，`retrieved_cases` ← API 响应中提取的案例切片 ID 列表，`generated_plan_text` ← `accumulatedText`，`disclaimer` ← API 响应中提取，`generation_id` ← API 响应中提取，`confidence_score` ← Store 中的 `confidenceScore`，`validation_verdict` ← Store 中的 `validationVerdict`，`request_id` ← 步骤 3 生成的 UUID v4）
     b. 通过 `httpClient.request({ method: 'POST', url: '/api/v1/consultations', data: historyCreate })` 发出写入请求
     c. 写入成功 → 不做额外操作（静默完成）
     d. 写入失败 → 记录日志（`logger.warn('archive_failed', { request_id })`），不阻塞用户继续浏览——本次咨询结果已在消息列表中，仅历史记录缺失
   - **输入来源**：Store 中的咨询数据 + API 响应中的生成元数据
   - **输出去向**：CSLT-06 的 consultations 表
   - **失败行为**：非阻塞——写入失败不阻断用户浏览当前结果或开始新咨询

7. **步骤 7：消息列表裁剪**
   - **操作对象**：`messages` 数组
   - **具体操作**：在 `addMessage()` action 末尾检查 `get().messages.length >= 200`，若达到阈值 → 调用 `set({ messages: get().messages.slice(50) })`（截断最早 50 条，保留 150 条）
   - **输入来源**：当前 `messages` 数组
   - **输出去向**：裁剪后的 `messages` 数组 + Zustand persist 中间件异步写 Taro Storage
   - **失败行为**：Zustand `set()` 为同步原子操作，不产生失败路径。若 persist 中间件写 Storage 失败（如存储空间满），仅记录日志不抛异常，本次会话数据在内存中不受影响

### 1.6 接口契约（对外暴露的公共接口）【已锁定】

#### 1.6.1 接口 1：useConsult

```typescript
/**
 * 应急咨询编排逻辑的对外接口 Hook。
 * CSLT-07 应急咨询界面通过此 Hook 获取全部咨询状态与操作方法。
 *
 * @returns UseConsultReturn - 包含只读状态和操作方法的完整接口
 *
 * @sideEffects
 *   - Store 状态变更通过 Zustand selector 触发组件重渲染
 *   - submitConsult() 发起 HTTP 请求并建立 SSE 连接
 *   - startNewConsult() 清空当前会话状态并重置消息列表
 *
 * @threadSafety
 *   本 Hook 内部通过 Zustand 的原子 `set()` 保证状态一致性。
 *   submitConsult() 内置并发防护（检查 submitting/streaming 状态）。
 *   多个 CSLT-07 子组件同时通过 selector 订阅不同字段，互不干扰。
 *
 * @example
 *   const { sessionState, messages, submitConsult, startNewConsult } = useConsult();
 */
export function useConsult(): UseConsultReturn;
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `useConsult` —— 语义化，表达"使用咨询功能"的 Hook 调用 |
| **输入类型** | 无参数（从 Zustand Store 内部读取状态） |
| **输出类型** | `UseConsultReturn`（详见 §1.4 的完整类型定义） |
| **异常类型** | 不抛出异常——所有错误通过 `errorCode` 字段和状态转换表达 |
| **副作用** | 发起 HTTP 请求、建立 SSE 连接、写入 Taro Storage（persist）、触发组件重渲染 |
| **幂等性** | `submitConsult()` 在 `submitting`/`streaming` 状态下重复调用被静默阻止。`startNewConsult()` 在非 `idle`/`completed`/`ticket_guide`/`submit_failed`/`stream_failed` 状态下不执行 |
| **并发安全** | 状态转换通过 `transitionTo()` 的 guard 函数 + Zustand `set()` 原子更新保证并发安全 |

### 1.7 依赖与集成接口（本模块调用的外部接口）【已锁定】

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 前端框架 | Taro 4.x | `Taro.request(options)` / `Taro.navigateTo({ url })` / `Taro.setStorageSync(key, data)` / `Taro.getStorageSync(key)` | HTTP 请求、页面跳转、数据持久化 | `docs/篝火智答-项目结构.md` §6.1 L1b |
| 状态管理 | Zustand 5.x | `create()` / `persist()` | Store 创建和持久化中间件 | `docs/篝火智答-项目结构.md` §6.1 logics/*/store/ |
| HTTP 客户端 | AUTH-06 httpClient | `httpClient.request({ method, url, data, timeout })` | 统一 HTTP 请求（Token 注入 + 401 续期） | `docs/篝火智答-项目结构.md` §6.1 logics/shared/services/httpClient.ts |
| 认证 Hook | AUTH-06 useAuth | `useAuth()` 返回 `{ sessionState, user, ... }` | 获取当前用户身份和认证状态 | `docs/篝火智答-项目结构.md` §6.1 logics/shared/hooks/useAuth.ts |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| CSLT-04 流式应答推送 | `GET /api/v1/consult/stream?session_id={id}`，响应 `text/event-stream` | SSE 流式消费四类事件（chunk/done/error/heartbeat） | ✅ 设计完成，待实现（可 mock SSE 事件） |
| CSLT-06 咨询历史管理 | `POST /api/v1/consultations`（归档写入），`GET /api/v1/consultations?page={n}&page_size={m}`（列表），`GET /api/v1/consultations/{id}`（详情） | 咨询完成后归档、历史浏览 | ✅ 设计完成，待实现（可 mock API 响应） |
| TICK-09 工单交互逻辑 | `Taro.navigateTo({ url: '/pages/tickets/detail?request_id={id}' })` | 工单引导卡片"联系专家"按钮触发路由跳转 | ❌ 未开始（可 mock 路由跳转） |
| PROF-07 档案数据逻辑 | 通过事件总线或回调触发：`onConsultCompleted(requestId)` | 咨询完成后触发冷启动检测和微问卷 | ❌ 未开始（可 mock 回调） |
| AUTH-06 认证会话管理 | `httpClient`（Token 注入 + 401 续期），`useAuth()`（认证状态感知） | 确保 API 调用携带有效认证凭证 | ✅ 部分实现（httpClient.ts / tokenManager.ts 已存在） |

### 1.8 状态机【对内实现】

| 当前状态 | 触发事件 | 下一状态 | 前置条件 | 副作用 |
|----------|----------|----------|----------|--------|
| `idle` | `startConsult` | `selecting_behavior` | 当前状态为 `idle` | 清空 `behaviorTypeSelection`、`behaviorDescription`；初始化 `messages` |
| `selecting_behavior` | `cancelSelection` | `idle` | 当前状态为 `selecting_behavior` | 保留用户输入（不丢失） |
| `selecting_behavior` | `submitConsult` | `submitting` | `isInputValid === true` 且当前状态为 `selecting_behavior` | 生成 `request_id`（UUID v4）；组装 `ConsultSubmitRequest`；POST 咨询 API |
| `submitting` | `sse_stream_connected` | `streaming` | API 响应成功且 SSE 首个 chunk 到达 | 创建 `SseStreamParser` 实例；初始化 `accumulatedText`、`planSections`、`lastSequence = 0` |
| `submitting` | `submit_request_failed` | `submit_failed` | API 请求失败（网络异常或 HTTP 5xx） | 设置 `errorCode`（SUBMIT_NETWORK_ERROR / SUBMIT_SERVER_ERROR）；用户输入保留 |
| `streaming` | `sse_done` | `completed` | DoneEvent 到达且 finish_reason 非 error | 存储置信度数据；计算工单引导标记；触发归档写入 |
| `streaming` | `sse_connection_failed` | `stream_failed` | SSE 连接中断且 3 次重连均失败 | 标记 `planSections` 中未完成段落 `isPartial = true`；设置 `errorCode = SSE_CONNECTION_BROKEN` |
| `completed` | `ticket_trigger` | `ticket_guide` | `(confidenceScore < 0.7 或 validationVerdict === 'FORCE_BLOCK')` 且 `ticketGuideShown === false` | 设置 `ticketGuide = { show: true, riskLevel }`；`ticketGuideShown = true` |
| `completed` | `startNewConsult` | `selecting_behavior` | 家属点击"开始新咨询"按钮 | 清空当前会话状态和消息列表；重置所有字段 |
| `ticket_guide` | `startNewConsult` | `selecting_behavior` | 家属点击"开始新咨询"或忽略工单卡片 | 清空当前会话状态和消息列表 |
| `submit_failed` | `retrySubmit` | `submitting` | 家属点击"重试"按钮 | 重新执行步骤 3（提交请求）；`request_id` 重新生成 |
| `submit_failed` | `goBackToIdle` | `idle` | 家属点击"返回"按钮 | 保留用户输入（不丢失——家属回到 idle 后再次开始咨询时恢复上次输入） |
| `stream_failed` | `retryStream` | `submitting` | 家属点击"重新生成"按钮 | 新方案作为新消息追加到 `messages`（不覆盖历史）；`request_id` 重新生成 |
| `stream_failed` | `goBackToIdle` | `idle` | 家属点击"退出"按钮 | 保留消息列表（已接收的部分内容仍可浏览） |

**实现约束**：
- 状态转换表定义为 `LEGAL_TRANSITIONS: Record<ConsultSessionState, ConsultSessionState[]>`，12 条合法路径
- 若 `newState === currentState`，`transitionTo()` 静默忽略（不抛异常，不记录日志）
- 若 `newState` 不在 `LEGAL_TRANSITIONS[currentState]` 中，抛出 `StateTransitionError`
- 并发防护：`submitConsult()` 入口先通过 `get().sessionState` 检查是否为 `submitting`/`streaming`，若是则设置 `errorCode = CONCURRENT_SUBMIT_BLOCKED` 并 return
- `transitionTo()` 内部仅做校验 + `set()` 写入，不包含异步操作

### 1.9 异常与边界条件【对内实现】

#### 1.9.1 异常 1：输入校验不通过

- **触发条件**：
  - `behaviorTypeSelection.length === 0`（家属未勾选任何行为类型）
  - `behaviorDescription.trim() === ''`（行为描述文本为空或仅含空白字符）
- **处理策略**：
  1. `isInputValid` computed selector 自动计算为 `false`
  2. CSLT-07 订阅 `isInputValid` 后将提交按钮置为 `disabled`
  3. CSLT-07 根据 Store 中的字段状态渲染具体缺失提示（`behaviorTypeSelection` 为空 → "请至少选择一种行为类型"；`behaviorDescription` 为空 → "请填写行为描述"）
  4. 家属补充完整后 `isInputValid` 自动变为 `true`，按钮恢复可点击
  5. **不进入任何后续步骤**
- **重试参数**：不适用。不发起请求。

#### 1.9.2 异常 2：提交请求失败

- **触发条件**：
  - `Taro.request` 抛出网络异常（如无网络连接、DNS 解析失败）
  - HTTP 响应状态码为 5xx（如 500、502、503）
  - 连接超时（>10s 无响应）
- **处理策略**：
  1. 捕获异常并分类：网络异常 → `SUBMIT_NETWORK_ERROR`；HTTP 5xx → `SUBMIT_SERVER_ERROR`；超时 → `SUBMIT_NETWORK_ERROR`
  2. 调用 `transitionTo('submit_failed')`
  3. 设置 `errorCode` 为对应枚举值
  4. CSLT-07 渲染错误提示（通过 `getErrorMessage(errorCode)` 获取文案）和"重试"/"返回"按钮
  5. 用户输入（`behaviorTypeSelection` 和 `behaviorDescription`）保留在 Store 中不丢失
  6. 记录日志：`console.debug('submit_failed', { errorCode, timestamp: Date.now() })`
- **重试参数**：不自动重试。由家属点击"重试"按钮触发 `retrySubmit()`，重新执行步骤 3，`request_id` 重新生成。无手动重试上限。

#### 1.9.3 异常 3：SSE 连接中断且重连耗尽

- **触发条件**：
  - SSE 连接在 `streaming` 状态中断（`readyState === CLOSED` 或 fetch 流读取异常）
  - 自动重连 3 次均失败（重连间隔：1s / 2s / 5s，指数退避）
- **处理策略**：
  1. `SseStreamParser` 触发 `onReconnectFailed` 回调
  2. 调用 `transitionTo('stream_failed')`
  3. 遍历 `planSections`，将所有 `isCompleted === false` 的段落标记 `isPartial = true`
  4. 在 `messages` 中追加一条 `system_prompt` 类型消息：`content = "生成中断，以下为不完整建议，可能缺失部分段落"`
  5. 设置 `errorCode = SSE_CONNECTION_BROKEN`
  6. CSLT-07 渲染"重新生成"和"退出"按钮
  7. 在尚未收到任何 chunk 时中断（`lastSequence === 0`）→ 不保留空消息，仅展示"生成失败，请稍后重试"
- **重试参数**：最大 3 次自动重连，间隔 [1000ms, 2000ms, 5000ms]。每次重连携带 `Last-Event-Id: {lastSequence}` 请求头。3 次耗尽后不再自动重连，家属手动"重新生成"触发重新发起提交。

#### 1.9.4 异常 4：重复提交（并发防护）

- **触发条件**：
  - 家属在当前状态为 `submitting` 或 `streaming` 时再次触发 `submitConsult()`（如快速双击、异步延迟重入）
- **处理策略**：
  1. `submitConsult()` action 入口：`const current = get().sessionState; if (current === 'submitting' || current === 'streaming') { set({ errorCode: 'CONCURRENT_SUBMIT_BLOCKED' }); return; }`
  2. 设置 `errorCode = CONCURRENT_SUBMIT_BLOCKED`
  3. CSLT-07 渲染提示："当前正在生成建议，请等待完成后再发起新的咨询"
  4. 不发起新 HTTP 请求，不改变状态
- **重试参数**：不适用。当前咨询完成（`completed`/`submit_failed`/`stream_failed`）后自动解除阻止。

#### 1.9.5 边界条件：消息列表超限裁剪

- **触发条件**：`addMessage()` action 执行后 `messages.length >= 200`
- **处理策略**：
  1. 在 `set()` 原子操作内执行 `messages.slice(50)`，截断最早 50 条
  2. 裁剪后消息数 ≤ 150 条
  3. Zustand `persist` 中间件自动同步裁剪后的数组到 Taro Storage
  4. 裁剪不影响当前 `streaming` 状态下的 SSE 消费（异步操作与裁剪无竞态——裁剪在 `set()` 内同步完成，SSE 解析器下一次 `addMessage` 所见即为裁剪后的数组）
- **重试参数**：不涉及重试。每次 `addMessage` 后自动检测。

#### 1.9.6 边界条件：SSE 流无数据软超时

- **触发条件**：SSE 流建立后 20s 内无任何 chunk 或 heartbeat 事件到达
- **处理策略**：
  1. `SseStreamParser` 触发 `onNoDataTimeout` 回调
  2. 设置 `errorCode = SSE_NO_DATA_TIMEOUT`
  3. CSLT-07 渲染进度提示："正在生成建议，请稍候"（非阻塞，不终止连接）
  4. 若后续数据到达，清除 `errorCode`（恢复为 `undefined`）
  5. 不改变 `sessionState`（仍为 `streaming`）
- **重试参数**：不终止连接，不重连。纯用户提示。

### 1.10 验收测试场景

#### 1.10.1 正向测试 1：完整咨询流程成功

- **场景**：家属完整走完从行为选择到查看结果的咨询全流程
- **Given**：
  - 家属已登录（AUTH-06 `SessionState = 'authenticated'`）
  - 后端 API 和 SSE 服务均正常运行（mock）
  - 当前 `sessionState = 'idle'`
- **When**：
  1. 调用 `startConsult()` → 状态切至 `selecting_behavior`
  2. 调用 `setBehaviorTypes(['EMOTIONAL_MELTDOWN', 'AGGRESSION'])`
  3. 调用 `setBehaviorDescription('孩子放学后尖叫并推倒桌上物品，持续约十分钟')`
  4. 调用 `submitConsult()` → 状态切至 `submitting`，然后 `streaming`
  5. 模拟 SSE 流推送 6 个 chunk（分别对应四段文本，包含各段标题行），最后推送 `done` 事件
  6. 模拟 API 响应携带 `ConfidenceValidationOutput { confidence_score: 0.85, verdict: 'PASS', ticket_triggered: false }`
- **Then**：
  - `sessionState` 为 `completed`
  - `planSections.length === 4`，每个段落的 `isCompleted === true`
  - `messages` 包含 `user_input` 消息（含行为描述）和 `system_plan` 消息（含完整四段文本）
  - `ticketGuide.show === false`（置信度 > 0.7 且无高风险命中）
  - `errorCode === undefined`

#### 1.10.2 正向测试 2：工单引导触发（低置信度）

- **场景**：置信度不足时自动触发工单引导
- **Given**：
  - 咨询流程已完成（`sessionState = 'completed'`，步骤同上）
  - API 响应携带 `ConfidenceValidationOutput { confidence_score: 0.62, verdict: 'APPEND_WARNING', ticket_triggered: true }`
- **When**：API 响应处理逻辑执行
- **Then**：
  - `sessionState` 为 `ticket_guide`
  - `ticketGuide.show === true`
  - `ticketGuide.riskLevel === 'normal'`
  - `ticketGuideShown === true`
  - 消息列表中包含工单引导卡片消息

#### 1.10.3 正向测试 3：历史只读浏览

- **场景**：家属浏览往期咨询记录，不触发新生成
- **Given**：
  - 咨询历史中有 1 条历史记录
  - 当前 `sessionState = 'idle'`
- **When**：调用 `fetchHistoryDetail('consult-xxx')`
- **Then**：
  - 返回的 `ConsultationHistoryDetail` 包含完整咨询数据
  - `sessionState` 不改变（保持 `idle`）
  - 不建立 SSE 连接
  - 不发起 POST 咨询请求

#### 1.10.4 异常测试 1：输入校验阻止空提交

- **场景**：家属未选择行为类型时提交按钮不可用
- **Given**：
  - `sessionState = 'selecting_behavior'`
  - `behaviorTypeSelection = []`（未勾选任何行为类型）
  - `behaviorDescription = '一些描述'`
- **When**：CSLT-07 读取 `isInputValid`
- **Then**：
  - `isInputValid === false`
  - 提交按钮为 `disabled` 状态
  - 调用 `submitConsult()` 被不执行（action 入口校验 `isInputValid` 为 false）

#### 1.10.5 异常测试 2：SSE 连接中断与重连

- **场景**：SSE 流传输中断但重连成功
- **Given**：
  - `sessionState = 'streaming'`
  - 已接收 3 个 chunk（`lastSequence = 3`，`accumulatedText` 包含部分内容）
  - SSE 连接在第 4 个 chunk 前断开
- **When**：`SseStreamParser` 检测到连接中断，自动重连
- **Then**：
  - 第 1 次重连在 1s 后发起，携带 `Last-Event-Id: 3`
  - 重连成功后继续接收 chunk，`lastSequence` 从 4 开始递增
  - `sessionState` 保持 `streaming` 不变
  - 重连成功后 `accumulatedText` 和 `planSections` 连续递增无跳变

#### 1.10.6 异常测试 3：流传输失败后部分内容保留

- **场景**：SSE 重连 3 次均失败后展示不完整方案
- **Given**：
  - `sessionState = 'streaming'`
  - 已接收 5 个 chunk（前两段已完整：即时安全干预动作 + 情绪安抚话术）
  - 第 3 次重连失败
- **When**：`SseStreamParser` 触发 `onReconnectFailed`
- **Then**：
  - `sessionState` 为 `stream_failed`
  - `planSections[0].isCompleted === true`（第一段完整）
  - `planSections[1].isCompleted === true`（第二段完整）
  - `planSections[2].isPartial === true`（后续段落不完整）
  - `messages` 末尾包含 `system_prompt` 消息："生成中断，以下为不完整建议..."
  - 家属可重新生成（`retryStream`）或退出（`goBackToIdle`）

#### 1.10.7 异常测试 4：并发提交被阻止

- **场景**：家属在咨询进行中尝试发起新咨询
- **Given**：
  - `sessionState = 'streaming'`
- **When**：调用 `submitConsult()`（模拟快速双击或异步延迟重入）
- **Then**：
  - `errorCode === ConsultErrorCode.CONCURRENT_SUBMIT_BLOCKED`
  - 未发起新 HTTP 请求
  - `sessionState` 保持 `streaming` 不变
  - CSLT-07 渲染提示："当前正在生成建议，请等待完成后再发起新的咨询"

### 1.11 注意事项与禁止行为（编码层面）【对内实现】

1. **[强制约束 — 状态转换唯一入口]** 所有 `sessionState` 变更必须通过 `transitionTo(newState: ConsultSessionState)` 执行。禁止在任何组件、Hook 或 action 中直接调用 `set({ sessionState: 'xxx' })`。违者将在 code review 中被拒绝。

2. **[强制约束 — SSE 解析器的跨平台兼容]** `SseStreamParser` 必须在微信小程序 iOS 和 Android 双端测试通过。关键兼容点：(a) 跨 chunk 边界的事件拼接——iOS 可能将 `data: {"text":"hello"}\n\ndata: {"text":"world"}\n\n` 合并到单次回调；(b) `\r\n` vs `\n` 换行符处理——两平台可能不一致，解析器需同时兼容 `\r\n\r\n` 和 `\n\n` 作为事件分隔符；(c) fetch API 的 `response.body.getReader()` 在 Taro 中的可用性——若不可用，降级为 `Taro.request` 的 `onChunkReceived` 回调。

3. **[强制约束 — 不可绕过互斥检查]** `submitConsult()` 入口的并发防护检查不可被注释、移除或通过参数跳过。即便是调试模式或单元测试 mock，也应保留此检查——否则可能在异步竞态下产生重复请求。

4. **[易错点 — 段落正则匹配]** `parseSections()` 的正则模式 `/## 即时安全干预动作|## 情绪安抚话术|## 后续观察指标|## 就医判断标准/` 依赖 CSLT-03 Prompt 模板的固定标题格式。若 CSLT-03 修改了标题文案（如改为"## 第一步：安全干预"），CSLT-08 的正则必须同步更新。建议在代码中以常量 `SECTION_TITLE_PATTERNS` 集中管理此映射，并在注释中标注"与 CSLT-03 Prompt 模板同步"。

5. **[易错点 — messageId 的唯一性]** `createMessageItem()` 使用 `msg-${uuid4()}` 生成消息 ID。不要使用自增数字或 `Date.now()` 作为 ID——在快速连续添加消息时可能产生碰撞。`uuid` 生成使用 `crypto.randomUUID()`（若 Taro 环境支持）或 `Math.random().toString(36).substring(2) + Date.now().toString(36)` 降级方案。

6. **[易错点 — Zustand persist 的 Storage 键名]** `persist` 中间件的 `name` 配置项设为 `'consult-session'`，Storage 写入键名自动为 `consult-session`（Zustand 默认以 name 为键）。确保此键名不与项目中其他 Store 的 persist 键名冲突（如 AUTH-06 的 `'auth-session'`、PROF-07 的 `'profile-session'`）。

7. **[禁止行为 — 禁止在 action 中直接操作 Storage]** 所有持久化操作由 Zustand `persist` 中间件自动完成。禁止在 `addMessage()` 或其他 action 中手动调用 `Taro.setStorageSync()`——否则会导致 Storage 与内存状态不一致。

8. **[禁止行为 — 禁止在 Hook 中发起副作用]** `useConsult()` Hook 本身是纯 selector 封装——仅读取 Store 状态并返回。禁止在 Hook 函数体内放置 `useEffect` 或其他副作用逻辑。副作用统一在 Store action 或 `SseStreamParser` 事件回调中执行。

9. **[设计边界提醒]** CSLT-08 不负责：(a) 后端 API 的具体路由定义和响应格式设计（归属各后端模块）、(b) 消息气泡样式和动画（归属 CSLT-07）、(c) Token 管理和登录状态（归属 AUTH-06）、(d) 工单创建和分配逻辑（归属 TICK-01~05）。

10. **[待裁决项提醒]** 设计文档 §1.7 标注的 3 项待裁决（超时阈值 10s/20s、页面结构 单页步骤切换 vs 独立路由、异常提示文案措辞）在编码时均使用当前默认值。待产品确认后可仅调整常量/文案文件，不影响代码结构。

### 1.12 文档详细度自检清单【对内实现】

- [ ] 文档自包含：一位不了解本项目代码的 Agent，仅凭此文档即可完成编码
- [ ] 无偷懒表述：全文无"等等"、"..."、"其他字段"、"类似"、"同上"、"参考其他模块"、"请根据实际情况补充"、"开发者自行决定"
- [ ] 类型定义完整：每个 TypeScript 类型字段都有 JSDoc 描述 + 业务约束说明
- [ ] 逻辑步骤完整：7 个步骤，每个都有操作对象、具体操作、输入来源、输出去向、失败行为
- [ ] 异常处理完整：6 种异常/边界场景，每种都有精确的触发阈值（具体数值）、逐步处理策略、精确重试参数
- [ ] 无隐藏假设：所有默认值来源（超时 10s/20s/1s/2s/5s 等）、条件分支（confidenceScore < 0.7）、业务规则都已显式写出
- [ ] 技术栈绑定明确：必须使用的 6 项和禁止使用的 6 项均已列出，与项目技术栈设计文档一致
- [ ] 意图一致性：已确认技术实现与已冻结的意图文档一致

### 1.14 外部接口契约清单【已锁定】

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| BehaviorTypeCategory | `docs/contracts/CSLT-01/BehaviorTypeCategory.json` | shared-enum | draft | CSLT-01 | CSLT-07, CSLT-08 |
| CrisisLevel | `docs/contracts/CSLT-01/CrisisLevel.json` | shared-enum | draft | CSLT-01 | CSLT-03, CSLT-05, TICK-01, TICK-02, CSLT-08 |
| ChunkEvent | `docs/contracts/CSLT-04/ChunkEvent.json` | event | draft | CSLT-04 | CSLT-08 |
| DoneEvent | `docs/contracts/CSLT-04/DoneEvent.json` | event | draft | CSLT-04 | CSLT-08 |
| ErrorEvent | `docs/contracts/CSLT-04/ErrorEvent.json` | event | draft | CSLT-04 | CSLT-08 |
| HeartbeatEvent | `docs/contracts/CSLT-04/HeartbeatEvent.json` | event | draft | CSLT-04 | CSLT-08 |
| StreamErrorCode | `docs/contracts/CSLT-04/StreamErrorCode.json` | shared-enum | draft | CSLT-04 | CSLT-08 |
| ValidationVerdict | `docs/contracts/CSLT-05/ValidationVerdict.json` | shared-enum | draft | CSLT-05 | CSLT-08, CSLT-06 |
| ConfidenceValidationOutput | `docs/contracts/CSLT-05/ConfidenceValidationOutput.json` | output | draft | CSLT-05 | CSLT-08, CSLT-06, TICK-01 |
| ConsultationHistoryCreate | `docs/contracts/CSLT-06/ConsultationHistoryCreate.json` | input | draft | CSLT-06 | CSLT-08 |
| ConsultationHistoryListItem | `docs/contracts/CSLT-06/ConsultationHistoryListItem.json` | output | draft | CSLT-06 | CSLT-08, TICK-01 |
| ConsultationHistoryDetail | `docs/contracts/CSLT-06/ConsultationHistoryDetail.json` | output | draft | CSLT-06 | CSLT-08 |
| httpClient | `docs/contracts/AUTH-06/httpClient.json` | shared-model | draft | AUTH-06 | CSLT-08, PROF-07, CASE-09, TICK-09, KNOW-07 |
| SessionState | `docs/contracts/AUTH-06/SessionState.json` | shared-enum | draft | AUTH-06 | AUTH-05, CSLT-07, CSLT-08, ... |
| useAuthReturn | `docs/contracts/AUTH-06/useAuthReturn.json` | shared-model | draft | AUTH-06 | CSLT-08, ... |
| TokenPair | `docs/contracts/AUTH-06/TokenPair.json` | shared-model | draft | AUTH-06 | CSLT-08, ... |

> CSLT-08 为前端 L1b 纯消费者模块，不定义新的后端 API JSON Schema 契约。自产 7 个前端 TypeScript 类型（ConsultSessionState, ConsultErrorCode, PlanSection, TicketGuide, ConsultSubmitRequest, StateTransitionError, LEGAL_TRANSITIONS）记录于 `docs/contracts/CSLT-08/_module-index.json`（reference_only）。

### 1.15 意图一致性声明

- **配套意图文档**：`CSLT-08-咨询编排逻辑-意图文档.md`
- **冻结时间**：`2026-05-27 21:37:16`（v2.0）
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档 §1.6 中的业务字段定义一致（5 输入 + 5 输出全部精确映射）
  - [x] 本落地规范中的状态机实现与意图文档 §1.7 中的状态业务定义一致（8 状态 + 12 条法定转换路径一一对应）
  - [x] 本落地规范中的异常处理策略与意图文档 §1.8 中的 3 种异常业务策略一致
  - [x] 本落地规范中的验收测试场景覆盖意图文档 §1.9 中的 7 条验收标准（AC-01~07 全部覆盖）
  - [x] 本落地规范中的技术实现未超出意图文档 §1.12 中"留给规范阶段的技术决策"的范围（10 项技术决策全部通过 s06 技术预研确定）
- **偏差说明**：无偏差，技术实现与意图文档完全一致。
