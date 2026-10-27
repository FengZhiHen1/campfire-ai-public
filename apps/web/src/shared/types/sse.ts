/**
 * 模块: shared/types/sse
 * 职责: 咨询面 SSE 流式事件的线格式类型——事件联合、SSE 帧信封与消息 part 形状
 * 数据来源:
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 4.2、7 节（传输编码与 part 表）
 *   - docs/技术设计/technical-details/通用基座.md: MUST — 第 7.1/7.2/7.3 节（三个事件载荷）
 * 边界:
 *   - 依赖: 无（纯类型模块，无运行时校验；OpenAPI 就绪后本文件改为生成物）
 *   - 被依赖: features/consult 的 domain 与 infrastructure 的 SSE 解码
 * 禁止行为:
 *   - 禁止在此定义业务模型（业务模型手写于各特性 domain，两者之间显式映射）
 *   - 禁止发明契约未定义的字段或事件名（事件名即线上契约，改名等于改契约）
 */

/** 运行结束原因。形状见 HTTP与SSE契约第 4.2 节终态事件（取值对齐 agent/runtime/events.py）。 */
export type RunEndReason = 'completed' | 'timeout' | 'cancelled';

/** 运行失败码。形状见 HTTP与SSE契约第 4.2 节与第 8 节失败语义。 */
export type RunFailureCode =
  | 'model_unavailable'
  | 'injection_failed'
  | 'session_write_failed'
  | 'context_overflow'
  | 'internal';

/** 模型失败细分原因；仅 code 为 model_unavailable 时带。形状见 HTTP与SSE契约第 4.2 节。 */
export type ModelFailureReason =
  | 'timeout'
  | 'rate_limited'
  | 'authentication'
  | 'connection'
  | 'provider_error'
  | 'unknown';

/** 工具失败错误码。形状见 HTTP与SSE契约第 4.2 节 tool_call_finished 与通用基座第 5 节。 */
export type ToolErrorCode =
  | 'tool_not_registered'
  | 'tool_not_available'
  | 'tool_requires_approval'
  | 'tool_invalid_arguments'
  | 'tool_failed'
  | 'tool_interrupted';

/** 一次运行的 token 计量。形状见 HTTP与SSE契约第 4.2 节终态事件。 */
export interface RunUsage {
  requests: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

/**
 * 一次压缩的计量，只带计数与用量、不带摘要正文。
 * 形状见 HTTP与SSE契约第 4.2 节终态事件（compactions）。
 */
export interface CompactionFacts {
  performed: boolean;
  window_tokens_before: number;
  window_tokens_after: number;
  released_tokens: number;
  compacted_items: number;
  retained_items: number;
  attempts: number;
  failed_attempts: number;
  previous_summary_merged: boolean;
  summary_input_tokens: number;
  summary_output_tokens: number;
  summary_elapsed_seconds: number;
  prompt_cache_hit_tokens: number;
  prompt_cache_miss_tokens: number;
  reason: string | null;
  detail: string;
}

/**
 * 引用索引里的一条记录。
 * 形状见 HTTP与SSE契约第 7 节 citation 行与资料与案例检索第 3 节返回契约。
 */
export interface CitationRecord {
  citation_id: string;
  run_id: string;
  source: string;
  reference: string;
  recorded_at: string;
  summary: string | null;
}

/** 一条未确认的候选产出，供面呈现为待确认。形状见 HTTP与SSE契约第 4.2 节 candidate。 */
export interface CandidatePayload {
  reference: string;
  summary: string;
}

/** 运行开始。形状见 HTTP与SSE契约第 4.2 节与通用基座第 7 节事件表。 */
export interface RunStartedEvent {
  type: 'run_started';
  run_id: string;
  session_id: string;
  surface: string | null;
  model: string;
  activated_skills: string[];
  injection_sources: string[];
  appended_messages: number;
}

/** 文本增量。形状见 HTTP与SSE契约第 4.2 节。 */
export interface TextDeltaEvent {
  type: 'text_delta';
  delta: string;
}

/**
 * 模型思考过程的文本增量（中间态，非结论）。
 * 形状见通用基座第 7.1 节。
 *
 * **2026-10-06 订正**：本行原写「该事件在 SDK 事件流里的键名未实测」——**已实测解除**：
 * T27 抓取的原始 SSE 帧里 `reasoning_delta` 出现 **2134 次**（原证物 `probes/step0-sse-frames.txt`），键名确证。
 * **⚠ 但「取不到时不产出」这条纪律仍然有效** —— 它是对**未来实现**的要求（不得用文本增量冒充），
 * 不是对现状的描述。
 */
export interface ReasoningDeltaEvent {
  type: 'reasoning_delta';
  delta: string;
}

/** 进度提示，用于长等待。形状见 HTTP与SSE契约第 4.2 节。 */
export interface ProgressEvent {
  type: 'progress';
  message: string;
}

/** 模型发起了一次工具调用。形状见 HTTP与SSE契约第 4.2 节。 */
export interface ToolCallStartedEvent {
  type: 'tool_call_started';
  tool_name: string;
  call_id: string;
}

/** 一次工具调用结束（成功或被拒绝）。形状见 HTTP与SSE契约第 4.2 节。 */
export interface ToolCallFinishedEvent {
  type: 'tool_call_finished';
  tool_name: string;
  call_id: string;
  ok: boolean;
  error_code: ToolErrorCode | null;
  summary: string;
}

/** 一条可引用依据。形状见 HTTP与SSE契约第 4.2 节与第 7 节 citation part。 */
export interface CitationEvent {
  type: 'citation';
  citation: CitationRecord;
}

/** 一条未确认的候选产出。形状见 HTTP与SSE契约第 4.2 节；候选不进历史（第 7 节）。 */
export interface CandidateEvent {
  type: 'candidate';
  candidate: CandidatePayload;
}

/** 结构化提问里的一道题。形状见通用基座第 7.2 节。 */
export interface QuestionOption {
  label: string;
  description?: string;
}

/** 结构化提问里的一组题。形状见通用基座第 7.2 节。 */
export interface QuestionItem {
  id: string;
  prompt: string;
  options: QuestionOption[];
  allow_skip: boolean;
}

/**
 * Agent 向使用者发起的一组结构化提问。
 * 形状见通用基座第 7.2 节（咨询面契约第 4.2 节注明本事件载荷归基座）。
 * 运行结束于提问而非暂停；回答经发消息端点的 answers 字段回传。
 */
export interface QuestionEvent {
  type: 'question';
  batch_id: string;
  items: QuestionItem[];
}

/** 行动卡的一个分节。形状见通用基座第 7.3 节。 */
export interface ActionCardSection {
  key: string;
  heading: string;
  lines: string[];
}

/** 行动卡的一个键值状态。形状见通用基座第 7.3 节。 */
export interface ActionCardState {
  key: string;
  value: string;
}

/** 行动卡的一条逐条标注；target 指向某条 line 的序号。形状见通用基座第 7.3 节。 */
export interface ActionCardAnnotation {
  target: string;
  kind: string;
}

/**
 * 一次结构化的卡片段输出（通用信封，不含领域词）。
 * 形状见通用基座第 7.3 节；运行不因卡片结束，同一会话可出现多张。
 */
export interface ActionCardEvent {
  type: 'action_card';
  card_id: string;
  title: string;
  sections: ActionCardSection[];
  states: ActionCardState[];
  annotations: ActionCardAnnotation[];
}

/** 运行正常结束（含触顶），带结束原因与引用清单。形状见 HTTP与SSE契约第 4.2 节。 */
export interface RunFinishedEvent {
  type: 'run_finished';
  reason: RunEndReason;
  citations: CitationRecord[];
  usage: RunUsage;
  elapsed_seconds: number;
  compactions: CompactionFacts[];
}

/** 运行异常结束，带错误码。形状见 HTTP与SSE契约第 4.2 节与第 8 节失败语义。 */
export interface RunFailedEvent {
  type: 'run_failed';
  code: RunFailureCode;
  detail: string;
  citations: CitationRecord[];
  usage: RunUsage;
  elapsed_seconds: number;
  model_reason: ModelFailureReason | null;
  compactions: CompactionFacts[];
}

/**
 * 一次运行可能发出的事件全集（判别联合，按 type 区分）。
 * 形状见 HTTP与SSE契约第 4.2 节映射表与通用基座第 7 节事件表。
 */
export type RunEvent =
  | RunStartedEvent
  | TextDeltaEvent
  | ReasoningDeltaEvent
  | ProgressEvent
  | ToolCallStartedEvent
  | ToolCallFinishedEvent
  | CitationEvent
  | CandidateEvent
  | QuestionEvent
  | ActionCardEvent
  | RunFinishedEvent
  | RunFailedEvent;

/**
 * 事件名联合，取自 RunEvent 的判别字段。
 * 线上 event 行与 data.type 恒等（HTTP与SSE契约第 4.2 节）。
 */
export type RunEventName = RunEvent['type'];

/**
 * 一帧 SSE 的解析结果。
 * 形状见 HTTP与SSE契约第 4.2 节：每条事件三行（id / event / data），id 为本次运行内单调递增序号。
 * id 同时是断线续传的唯一依据，因此它是首等字段而不是附带信息。
 */
export interface SseFrame {
  id: number;
  event: RunEventName;
  data: RunEvent;
}

/** 消息 part 的判别类型。形状见 HTTP与SSE契约第 7 节消息 part 形状表。 */
export type MessagePart =
  | TextPart
  | ReasoningPart
  | ToolCallPart
  | CitationPart
  | QuestionPart
  | QuestionRecordPart
  | ActionCardPart;

/** 文本 part。形状见 HTTP与SSE契约第 7 节 text 行。 */
export interface TextPart {
  type: 'text';
  text: string;
}

/** 思考 part。形状见 HTTP与SSE契约第 7 节 reasoning 行与通用基座第 7.1 节。 */
export interface ReasoningPart {
  type: 'reasoning';
  delta: string;
}

/** 工具调用 part。形状见 HTTP与SSE契约第 7 节 tool_call 行。 */
export interface ToolCallPart {
  type: 'tool_call';
  tool_name: string;
  ok: boolean;
  summary: string;
}

/** 引用 part。形状见 HTTP与SSE契约第 7 节 citation 行；跟消息同生命周期。 */
export interface CitationPart {
  type: 'citation';
  citation: CitationRecord;
}

/**
 * 提问 part（**流出侧 / 事件**形状）。形状见 HTTP与SSE契约第 7 节 question 行与通用基座第 7.2 节。
 *
 * 它描述「刚向使用者发出、尚未作答」的提问——发出即结束运行，因此载荷里**没有**
 * 「已作答」字段。历史水合的提问是另一个 part 类型（见 `QuestionRecordPart`）。
 */
export interface QuestionPart {
  type: 'question';
  batch_id: string;
  items: QuestionItem[];
}

/**
 * 水合侧专有的提问记录 part。形状见 HTTP与SSE契约第 7 节 `question-record` 行。
 *
 * 与 `QuestionPart` 的唯一差别是多一个三态的 `answered`：
 * - `true`  ⇒ 已作答 ⇒ 只读记录；
 * - `false` ⇒ 未作答 ⇒ **可作答**（刷新后仍能补答，这是本 part 存在的理由）；
 * - `null`  ⇒ **无法判定** ⇒ 只读记录（**fail-closed**）。
 *
 * `answered` **由服务端判定**，前端只读、不得自行推断（契约 §三 硬边界：
 * 「不许让前端猜」）。前端尤其不得用「后面没有消息就算未作答」这类自算。
 */
export interface QuestionRecordPart {
  type: 'question-record';
  batch_id: string;
  items: QuestionItem[];
  answered: boolean | null;
}

/** 行动卡 part。形状见 HTTP与SSE契约第 7 节 action_card 行与通用基座第 7.3 节。 */
export interface ActionCardPart {
  type: 'action_card';
  card_id: string;
  title: string;
  sections: ActionCardSection[];
  states: ActionCardState[];
  annotations: ActionCardAnnotation[];
}
