/**
 * 模块: features/consult/application/ports
 * 职责: 咨询面用例依赖的端口声明（HTTP/SSE 实现归 infrastructure）
 * 数据来源:
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 3～5 节端点形状、第 4.2 节事件流
 *   - docs/项目结构设计.md: MUST — 第 9 节（infrastructure 只暴露 RunEvent 异步流）
 * 边界:
 *   - 依赖: shared/types/{consult,sse}、features/consult/domain
 *   - 被依赖: features/consult 的用例与 viewModel
 * 禁止行为:
 *   - 禁止在此 import fetch、supertokens 或任何框架模块（FE-03）
 *   - 禁止让端口暴露 HTTP 细节（路径、状态码语义归实现；调用方按异常类型分支）
 */

import type {
  CreateSessionResponse,
  EmergencyRequest,
  EmergencyResponse,
  ListMessagesResponse,
  ListSessionsResponse,
  PostMessageRequest,
  PostMessageResponse,
} from '../../../shared/types/consult';
import type { RunEvent } from '../../../shared/types/sse';
import type { SkillSummary } from '../domain/types';

/** 建会话入参（契约第 3.1 节；省略对象时由服务端推导默认对象）。 */
export interface CreateSessionInput {
  support_object_id?: string;
}

/** 会话列表入参（契约第 3.2 节；limit 默认 20、上限 50）。 */
export interface ListSessionsInput {
  cursor?: string | null;
  limit?: number;
}

/** 订阅期间给上层的连接通告（只含「连接怎么样」，不含事件内容）。 */
export type StreamNotice =
  | { kind: 'reconnecting'; attempt: number }
  | { kind: 'resumed' };

/** 订阅入参。 */
export interface StreamRunInput {
  runId: string;
  /** 断线续传依据（上一次已收到的事件序号）。 */
  lastEventId?: number;
  signal: AbortSignal;
  /** 连接通告（重连开始/恢复）；用于状态条文案与输入区置灰。 */
  onNotice?: (notice: StreamNotice) => void;
}

/**
 * 咨询面端口。
 *
 * 为什么 streamRun 返回 AsyncIterable 而不是回调：技术设计第 1 节把 infrastructure 的职责
 * 限定为「事件解码」，适配器用 for await 逐事件映射成 assistant-ui 的 chunk 流；回调形态会
 * 让取消与背压两件事都要另立机制。
 */
export interface ConsultPort {
  /** 创建会话（日常入口）；返回 session_id 与是否待注入引导。 */
  createSession(input?: CreateSessionInput): Promise<CreateSessionResponse>;
  /** 会话列表（分页）。 */
  listSessions(input: ListSessionsInput): Promise<ListSessionsResponse>;
  /** 历史水合：按真源顺序返回消息与 part。 */
  loadHistory(sessionId: string): Promise<ListMessagesResponse>;
  /** 技能目录（选择器可选项）。 */
  listSkills(): Promise<SkillSummary[]>;
  /** 发消息（普通消息或一组回答，二选一），返回受理后的 run_id。 */
  sendMessage(sessionId: string, payload: PostMessageRequest): Promise<PostMessageResponse>;
  /** 订阅一条运行的事件流（含续传与重连）。 */
  streamRun(input: StreamRunInput): AsyncIterable<RunEvent>;
  /** 取消一条运行（对应停止按钮与 abortSignal）。 */
  cancelRun(runId: string): Promise<void>;
  /** 应急入口：建会话 → 落第一条消息 → 启动运行，一次调用完成。 */
  emergencyStart(payload: EmergencyRequest): Promise<EmergencyResponse>;
}
