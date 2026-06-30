// @contract
/**
 * CSLT-08 咨询编排逻辑 —— 全部前端 TypeScript 类型定义。
 *
 * 本文件是 CSLT-08 自产的类型定义集中文件，包含：
 * - 外部契约类型的本地 type alias 映射（CSLT-01/04/05/06）
 * - SSE 事件载荷类型
 * - 咨询会话状态与消息类型
 * - 异常错误码枚举与异常类
 * - useConsult Hook 的完整返回值接口
 *
 * 设计依据：CSLT-08 落地规范 §1.3 §1.4
 * 契约对齐：docs/contracts/CSLT-08/_module-index.json（reference_only）
 */

// ============================================================================
// 外部契约类型（本地 type alias 映射）
// ============================================================================

/**
 * 行为类型分类（CSLT-01 契约）。
 * 七类预设选项，家属可多选 ≥1 项。
 * 契约文件：docs/contracts/CSLT-01/BehaviorTypeCategory.json
 */
export type BehaviorTypeCategory =
  | 'SELF_INJURY'
  | 'AGGRESSION'
  | 'ELOPEMENT'
  | 'MEDICATION'
  | 'EMOTIONAL_MELTDOWN'
  | 'STEREOTYPY'
  | 'OTHER';

/**
 * 危机等级（CSLT-01 契约）。
 * 三级：轻度（建议观察）、中度（需干预）、重度（需紧急响应）。
 * 契约文件：docs/contracts/CSLT-01/CrisisLevel.json
 */
export type CrisisLevel = 'mild' | 'moderate' | 'severe';

/**
 * SSE 流式推送错误码（CSLT-04 契约）。
 * 用于 ErrorEvent.error_code 字段。
 * 契约文件：docs/contracts/CSLT-04/StreamErrorCode.json
 */
export type StreamErrorCode =
  | 'SESSION_NOT_FOUND'
  | 'GENERATION_FAILED'
  | 'STREAM_TIMEOUT'
  | 'CONCURRENCY_LIMIT_EXCEEDED'
  | 'INTERNAL_ERROR';

/**
 * 置信度后校验判定结论（CSLT-05 契约）。
 * 契约文件：docs/contracts/CSLT-05/ValidationVerdict.json
 */
export type ValidationVerdict = 'PASS' | 'APPEND_WARNING' | 'FORCE_BLOCK';

/**
 * 咨询历史列表条目（CSLT-06 契约）。
 * 契约文件：docs/contracts/CSLT-06/ConsultationHistoryListItem.json
 */
export interface ConsultationHistoryListItem {
  /** 咨询记录 UUID v4 */
  id: string;
  /** 咨询发生时间（服务端时间） */
  consultation_time: string;
  /** 家属输入的行为描述全文 */
  behavior_description: string;
  /** 危机分级判定结果 */
  crisis_level: CrisisLevel;
  /** 是否已提交反馈 */
  has_feedback: boolean;
  /** 行为标签（后端可直接返回中文标签，如 ['自伤行为','情绪崩溃']） */
  tags?: string[];
}

/**
 * 咨询历史完整详情（CSLT-06 契约）。
 * 契约文件：docs/contracts/CSLT-06/ConsultationHistoryDetail.json
 */
export interface ConsultationHistoryDetail {
  id: string;
  request_id: string;
  user_id: string;
  crisis_level: CrisisLevel;
  behavior_description: string;
  consultation_time: string;
  generated_plan: string;
  plan_sections?: Record<string, string[]>;
  source_list: string[];
  disclaimer: string;
  generation_time_ms: number;
  is_partial: boolean;
  referenced_slice_ids: string[];
  referenced_cases?: ReferencedCase[];
  /** 本次咨询引用切片关联的 L2 卡片摘要 */
  associated_cards?: AssociatedCard[];
  /** 行为标签（与列表项保持一致，后端可选返回） */
  tags?: string[];
  finish_reason: string;
  ttft_ms: number;
  has_feedback: boolean;
  token_input?: number | null;
  token_output?: number | null;
  device_info?: {
    platform?: string;
    device_brand?: string;
    os_version?: string;
    app_version?: string;
  } | null;
}

/**
 * 置信度后校验输出（CSLT-05 契约）。
 * 契约文件：docs/contracts/CSLT-05/ConfidenceValidationOutput.json
 */
export interface ConfidenceValidationOutput {
  /** 综合置信度评分 0.00-1.00 */
  confidence_score: number;
  /** 判定结论 */
  verdict: ValidationVerdict;
  /** 经处理后的完整方案文本 */
  modified_plan_text: string;
  /** 是否触发工单创建 */
  ticket_triggered: boolean;
  /** 工单创建是否失败（默认 false） */
  ticket_creation_failed?: boolean;
  /** 降级原因说明（正常复合评分时为 null） */
  degradation_note?: string | null;
  /** 校验总耗时毫秒 */
  validation_time_ms: number;
}

/**
 * 咨询历史归档写入模型（CSLT-06 契约）。
 * 契约文件：docs/contracts/CSLT-06/ConsultationHistoryCreate.json
 */
export interface ConsultationHistoryCreate {
  request_id: string;
  user_id: string;
  crisis_level: CrisisLevel;
  behavior_description: string;
  consultation_time: string;
  generated_plan: string;
  plan_sections?: Record<string, string[]>;
  source_list: string[];
  disclaimer: string;
  generation_time_ms: number;
  is_partial: boolean;
  referenced_slice_ids: string[];
  finish_reason: string;
  ttft_ms: number;
  has_feedback?: boolean;
  token_input?: number | null;
  token_output?: number | null;
  device_info?: {
    platform?: string;
    device_brand?: string;
    os_version?: string;
    app_version?: string;
  } | null;
}

// ============================================================================
// SSE 事件载荷类型（CSLT-04 契约映射）
// ============================================================================

/** ChunkEvent 的 data 字段载荷（CSLT-04 契约） */
export interface ChunkEventPayload {
  /** 当前 chunk 的文本增量（仅内容文本，JSON 语法已剥离） */
  text: string;
  /** 单调递增序列号，从 1 开始 */
  sequence: number;
  /** 所属段落标题，前端据此增量追加到对应 planSections。null 表示非内容文本 */
  section?: string | null;
}

/** DoneEvent 的 data 字段载荷（CSLT-04 契约） */
export interface DoneEventPayload {
  /** 流终止原因 */
  finish_reason: 'COMPLETE' | 'PARTIAL' | 'BLOCKED' | 'TIMEOUT' | 'ERROR';
  /** 最后成功推送的 sequence 号（可选） */
  sequence?: number;
  /** 被引用案例切片 ID 列表 */
  referenced_slice_ids?: string[];
  /** 危机分级结果 */
  crisis_level?: string;
  /** 参考案例简要信息 */
  referenced_cases?: ReferencedCase[];
  /** 置信度评分 */
  confidence_score?: number;
  /** 校验判定结论 */
  verdict?: string;
  /** 是否触发工单 */
  ticket_triggered?: boolean;
  /** 四段式结构化数据（后端 JSON 解析后下发） */
  sections?: Record<string, string[]>;
}

/** ErrorEvent 的 data 字段载荷（CSLT-04 契约） */
export interface ErrorEventPayload {
  /** 机器可读错误码 */
  error_code: StreamErrorCode;
  /** 人类可读错误详情 */
  detail: string;
}

// ============================================================================
// CSLT-08 自产前端类型
// ============================================================================

/** 情绪等级 */
export type EmotionLevel = '轻' | '中' | '重';

/** 参考案例简要信息 */
export interface ReferencedCase {
  slice_id: string;
  case_id: string;
  case_title: string;
  slice_text: string;
}

/** 关联 L2 卡片摘要（由引用切片反查） */
export interface AssociatedCard {
  card_id: string;
  title: string;
  behavior_type: string;
  severity: string;
  scene: string;
  review_status: string;
}

/**
 * 咨询会话业务状态（8 状态联合类型）。
 * 状态转换表定义于 LEGAL_TRANSITIONS，共 17 条合法路径。
 */
export type ConsultSessionState =
  | 'idle'
  | 'selecting_behavior'
  | 'submitting'
  | 'streaming'
  | 'completed'
  | 'ticket_guide'
  | 'submit_failed'
  | 'stream_failed';

/** 消息发送方 */
export type MessageSender = 'user' | 'system';

/** 消息类型 */
export type MessageType = 'user_input' | 'system_plan' | 'system_prompt' | 'ticket_card';

/** 消息条目唯一标识，格式 msg-{uuid4} */
export type MessageId = string;

/**
 * 单条消息。
 * 支持四种类型：用户输入(user_input)、系统方案(system_plan)、
 * 系统提示(system_prompt)、工单卡片(ticket_card)。
 */
export interface MessageItem {
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

/**
 * 单个方案段落。
 * 四段之一：即时安全干预动作 / 情绪安抚话术 / 后续观察指标 / 就医判断标准。
 */
export interface PlanSection {
  /** 段落标题（四段之一） */
  title: string;
  /** 文本内容列表，每个元素为一个已完成的句子 */
  contents: string[];
  /** 段落是否已全部接收完成 */
  isCompleted: boolean;
  /** 是否不完整（流传输失败场景，SSE 连接中断且重连耗尽时标记） */
  isPartial?: boolean;
}

// TODO: StructuredPlan 已移除——无外部消费，待实际使用时恢复

/** 工单引导风险等级 */
export type TicketRiskLevel = 'normal' | 'high_risk';

/**
 * 工单引导标记。
 * 置信度 < 0.7 或 verdict === 'FORCE_BLOCK' 时展示。
 */
export interface TicketGuide {
  /** 是否应展示工单引导卡片 */
  show: boolean;
  /** 风险等级 */
  riskLevel: TicketRiskLevel;
}

// TODO: ConsultSessionStateData 已移除——结构重复于 useConsultStore.ConsultSessionStoreState，待外部消费时恢复

/**
 * 前端异常错误码枚举（7 个错误码）。
 * 所有中文文案通过 getErrorMessage() 映射表统一管理，禁止硬编码。
 */
export enum ConsultErrorCode {
  /** 输入校验不通过（行为类型未选或描述为空） */
  INPUT_VALIDATION_FAILED = 'INPUT_VALIDATION_FAILED',
  /** 提交请求网络异常（无网络连接 / DNS 解析失败 / 超时） */
  SUBMIT_NETWORK_ERROR = 'SUBMIT_NETWORK_ERROR',
  /** 提交请求服务端错误（HTTP 5xx） */
  SUBMIT_SERVER_ERROR = 'SUBMIT_SERVER_ERROR',
  /** SSE 连接中断且 3 次重连均失败 */
  SSE_CONNECTION_BROKEN = 'SSE_CONNECTION_BROKEN',
  /** SSE 流 20s 无数据软超时 */
  SSE_NO_DATA_TIMEOUT = 'SSE_NO_DATA_TIMEOUT',
  /** 并发提交被阻止（submitting/streaming 状态下触发 submitConsult） */
  CONCURRENT_SUBMIT_BLOCKED = 'CONCURRENT_SUBMIT_BLOCKED',
  /** 工单创建失败（后端已重试 3 次失败） */
  TICKET_CREATION_FAILED = 'TICKET_CREATION_FAILED',
}

/**
 * 状态转换异常。
 * 当尝试进行非法状态转换时由 transitionTo() 抛出。
 */
export class StateTransitionError extends Error {
  /** 转换前的状态 */
  fromState: ConsultSessionState;
  /** 试图转换到的状态 */
  toState: ConsultSessionState;

  constructor(from: ConsultSessionState, to: ConsultSessionState) {
    super(`非法状态转换: ${from} -> ${to}`);
    this.name = 'StateTransitionError';
    this.fromState = from;
    this.toState = to;
    Object.setPrototypeOf(this, StateTransitionError.prototype);
  }
}

/**
 * useConsult Hook 的完整返回值类型。
 * CSLT-08 对 CSLT-07 的唯一输出接口，包含 21 个字段/方法。
 *
 * 设计依据：CSLT-08 落地规范 §1.4
 * 消费方：CSLT-07（应急咨询界面）
 */
export interface UseConsultReturn {
  // ---------- 只读状态（CSLT-07 渲染用） ----------
  /** 当前会话业务状态 */
  sessionState: ConsultSessionState;
  /** 当前勾选的行为类型列表 */
  behaviorTypeSelection: BehaviorTypeCategory[];
  /** 当前输入的行为描述文本 */
  behaviorDescription: string;
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
  /** 输入是否有效（行为类型 ≥1 或描述非空，满足其一即可提交） */
  isInputValid: boolean;
  /** 是否处于活跃咨询中（禁止新提交） */
  isConsultActive: boolean;
  /** 情绪等级选择 */
  emotionLevel?: EmotionLevel;
  /** 关联档案 ID */
  selectedProfileId?: string;
  /** 参考案例列表 */
  referencedCases: ReferencedCase[];
  /** 危机等级 */
  crisisLevel?: CrisisLevel;
  /** 综合置信度评分 0.00-1.00（后端 SSE done 事件下发） */
  confidenceScore?: number;

  // ---------- 操作方法（CSLT-07 绑定到按钮/事件） ----------
  /** 开始新咨询：idle -> selecting_behavior */
  startConsult: () => void;
  /** 更新行为类型选择（selecting_behavior 状态下可用） */
  setBehaviorTypes: (types: BehaviorTypeCategory[]) => void;
  /** 更新行为描述文本 */
  setBehaviorDescription: (desc: string) => void;
  /** 设置情绪等级 */
  setEmotionLevel: (level: EmotionLevel) => void;
  /** 设置关联档案 */
  setSelectedProfile: (profileId: string | undefined) => void;
  /** 提交咨询：selecting_behavior -> submitting */
  submitConsult: () => Promise<void>;
  /** 取消行为选择：selecting_behavior -> idle */
  cancelSelection: () => void;
  /** 重试提交：submit_failed -> submitting */
  retrySubmit: () => Promise<void>;
  /** 返回修改：submit_failed | stream_failed -> selecting_behavior */
  goBackToSelecting: () => void;
  /** 重试流式接收：stream_failed -> submitting（重新生成） */
  retryStream: () => Promise<void>;
  /** 开始新一轮咨询：completed | ticket_guide -> selecting_behavior */
  startNewConsult: () => void;
  /** 跳转工单模块：ticket_guide 状态下触发 Taro.navigateTo */
  goToTicket: () => void;
  /** 获取错误提示文案 */
  getErrorMessage: (code: ConsultErrorCode | string) => string;
  /** 获取历史咨询列表 */
  fetchHistoryList: (page: number, pageSize: number) => Promise<ConsultationHistoryListItem[]>;
  /** 获取历史咨询详情（只读） */
  fetchHistoryDetail: (consultationId: string) => Promise<ConsultationHistoryDetail>;
}

// ============================================================================
// 内部输入类型（不对外暴露）
// ============================================================================

// TODO: ConsultInputState 已移除——无外部消费，待实际使用时恢复

/**
 * 提交给后端 API 的咨询请求体。
 */
export interface ConsultSubmitRequest {
  /** 行为类型列表（snake_case 对齐后端） */
  behavior_type_selection: BehaviorTypeCategory[];
  /** 行为描述文本 */
  behavior_description: string;
}
