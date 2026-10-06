/**
 * 模块: shared/types/consult
 * 职责: 咨询面 HTTP 载荷的线格式类型——会话、发消息、订阅、应急入口与引导跳过
 * 数据来源:
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 3、4、5、6 节
 * 边界:
 *   - 依赖: shared/types/sse（事件与 part 形状归该文件）
 *   - 被依赖: features/consult 的 domain 与 infrastructure
 * 禁止行为:
 *   - 禁止在此复制 SSE 事件或 part 的形状（归 sse.ts，单一定义点）
 *   - 禁止把 HTTP 状态码语义写进载荷类型（错误码语义见契约第 2、8 节）
 */

import type { MessagePart } from './sse';

/** 创建会话响应。形状见 HTTP与SSE契约第 3.1 节。 */
export interface CreateSessionResponse {
  session_id: string;
  support_object_id: string | null;
  onboarding_pending: boolean;
}

/** 会话列表里的一条。形状见 HTTP与SSE契约第 3.2 节。 */
export interface SessionSummary {
  session_id: string;
  title: string;
  support_object_name: string | null;
  updated_at: string;
  last_message_preview: string | null;
}

/** 会话列表响应。形状见 HTTP与SSE契约第 3.2 节；limit 默认 20、上限 50。 */
export interface ListSessionsResponse {
  items: SessionSummary[];
  next_cursor: string | null;
}

/** 历史水合里的一条消息。形状见 HTTP与SSE契约第 3.3 节。 */
export interface HydratedMessage {
  id: string;
  role: 'user' | 'assistant';
  parts: MessagePart[];
}

/** 历史水合响应。形状见 HTTP与SSE契约第 3.3 节；顺序即会话真源顺序。 */
export interface ListMessagesResponse {
  session_id: string;
  messages: HydratedMessage[];
}

/** 一组提问里的一道回答。形状见 HTTP与SSE契约第 4.1 节与通用基座第 7.2 节。 */
export interface QuestionAnswer {
  id: string;
  value?: string;
  skipped?: boolean;
}

/** 普通消息形态的发消息请求。形状见 HTTP与SSE契约第 4.1 节。 */
export interface SendMessageRequest {
  content: string;
  skill?: string | null;
  client_message_id: string;
}

/** 一组提问回答形态的发消息请求。形状见 HTTP与SSE契约第 4.1 节。 */
export interface SendAnswersRequest {
  answers: QuestionAnswer[];
  /**
   * 本组提问的批次标识（可选）。
   *
   * ★ 出网键名逐字是 `batch_id`（snake_case），与前端内部的 `batchId` 不同名是刻意的：
   * 契约是 snake_case、前端惯用 camelCase，转换点必须在序列化边界一处完成
   * （`application/usecases.ts` 组装载荷处），不得散落。
   *
   * 可选（用户 2026-10-06 裁决）：缺失时服务端退回「位置窗口 × 表头」判定，
   * 旧客户端不得因此被拒——它不是破坏性变更。
   *
   * 值的两条来源语义不同（服务端职责，前端只如实回传、不做归属判断）：
   * 实时路径是裸 uuid hex（服务端只能排除）；水合路径是 `hydrated-<call_id>`
   * （服务端能剥前缀正向归属）。
   */
  batch_id?: string;
  skill?: string | null;
  client_message_id: string;
}

/**
 * 发消息请求：两种形态二选一，服务端按字段判别。
 * 形状见 HTTP与SSE契约第 4.1 节。
 */
export type PostMessageRequest = SendMessageRequest | SendAnswersRequest;

/** 发消息响应（202 只表示已受理，使用者消息尚未落库）。形状见 HTTP与SSE契约第 4.1 节。 */
export interface PostMessageResponse {
  run_id: string;
  session_id: string;
}

/** 应急入口请求里的一项采集。形状见 HTTP与SSE契约第 5 节。 */
export interface EmergencyItem {
  key: string;
  value?: string;
  values?: string[];
  skipped: boolean;
}

/** 应急入口请求。形状见 HTTP与SSE契约第 5 节；八项 key 的取值词表归 emergency-consulting。 */
export interface EmergencyRequest {
  support_object_id?: string;
  items: EmergencyItem[];
}

/** 应急入口响应（一次调用完成建会话、落首条消息与启动运行）。形状见 HTTP与SSE契约第 5 节。 */
export interface EmergencyResponse {
  session_id: string;
  run_id: string;
}

/** 引导跳过响应。形状见 HTTP与SSE契约第 6 节；幂等，已是终态仍返回 200。 */
export interface OnboardingSkipResponse {
  state: 'skipped';
}

/** 订阅事件流的路径参数与续传头。形状见 HTTP与SSE契约第 4.2 节。 */
export interface StreamSubscription {
  run_id: string;
  /** 断线续传依据；服务端已无可续内容时返回 409 run_not_resumable。 */
  lastEventId?: number;
}
