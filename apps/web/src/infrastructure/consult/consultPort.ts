/**
 * 模块: infrastructure/consult/consultPort
 * 职责: 咨询面端口的 HTTP 实现——端点调用、传输异常到领域失败的翻译、SSE 订阅接线
 * 数据来源:
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 2 节通用约定与错误码、第 3～5 节端点形状
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 1 节（infrastructure 只做事件解码）
 * 边界:
 *   - 依赖: infrastructure/http/client（凭据与 401 语义）、infrastructure/sse、infrastructure/diagnostics、
 *     shared/types、features/consult 的 application/ports 与 domain
 *   - 被依赖: app 的装配（路由把端口注入页面）
 * 禁止行为:
 *   - 禁止在此渲染或写业务文案（领域失败的呈现归 domain/errors 与 view）
 *   - 禁止吞掉失败（每种传输异常都被翻译成显式的 ConsultError 种类）
 */

import type {
  CreateSessionResponse,
  EmergencyRequest,
  EmergencyResponse,
  ListMessagesResponse,
  ListSessionsResponse,
  PostMessageRequest,
  PostMessageResponse,
} from '../../shared/types/consult';
import type { RunEvent } from '../../shared/types/sse';
import type { ConsultPort, CreateSessionInput, ListSessionsInput, StreamRunInput } from '../../features/consult/application/ports';
import { ConsultError } from '../../features/consult/domain/errors';
import { SKILL_CATALOG } from '../../features/consult/domain/skills';
import type { SkillSummary } from '../../features/consult/domain/types';
import { logDiagnostic } from '../diagnostics';
import { HttpError, request } from '../http/client';
import {
  RunNotResumableError,
  RunStreamExhaustedError,
  SseTransportError,
  subscribeRunEvents,
  type SseDiagnosticSink,
} from '../sse';

/** 端口实现的装配选项。 */
export interface ConsultApiOptions {
  /** fetch 实现；测试注入 mock。 */
  fetchImpl?: typeof fetch;
  /** 401 处置（清本地状态 + 跳登录页）；由 app 层注入。 */
  onUnauthorized?: () => void;
  /** 诊断出口；默认写开发态 debug 日志。 */
  onDiagnostic?: SseDiagnosticSink;
}

/** HTTP 状态码 → 领域失败种类（契约第 2 节错误码表）。 */
function fromHttpStatus(error: HttpError): ConsultError {
  switch (error.status) {
    case 401:
      return new ConsultError('unauthorized', '会话已失效', { cause: error });
    case 404:
      return new ConsultError('not-found', '资源不存在或不属于当前账号', { cause: error });
    case 409:
      // 发消息路径上的 409 只有 session_busy；run_not_resumable 走 StreamRun 的专用异常。
      return new ConsultError('busy', '会话上已有正在进行的运行', { cause: error });
    case 422:
      return new ConsultError('invalid', '载荷不合法', { cause: error });
    case 503:
      return new ConsultError('unavailable', '依赖不可用', { cause: error });
    default:
      return new ConsultError('unexpected', `HTTP ${error.status}`, { cause: error });
  }
}

/** 任意传输异常 → 领域失败（唯一的翻译点）。 */
export function translateConsultError(error: unknown): ConsultError {
  if (error instanceof ConsultError) return error;
  if (error instanceof HttpError) return fromHttpStatus(error);
  if (error instanceof RunNotResumableError) {
    return new ConsultError('not-resumable', error.message, { cause: error });
  }
  if (error instanceof RunStreamExhaustedError) {
    return new ConsultError('stream-exhausted', error.message, { cause: error });
  }
  if (error instanceof SseTransportError) {
    return new ConsultError('network', error.message, { cause: error });
  }
  // fetch 在网络层失败时抛 TypeError（DNS/断网/CORS 预检失败），它不是程序缺陷，
  // 按可重试的网络失败呈现而不是「未预期错误」。
  if (error instanceof TypeError) {
    return new ConsultError('network', '网络请求失败', { cause: error });
  }
  return new ConsultError('unexpected', '未预期的错误', { cause: error });
}

/**
 * 创建咨询面端口。
 *
 * @param options 装配选项（fetch、401 处置与诊断出口）
 * @returns ConsultPort 实现
 * @throws ConsultError 端口方法失败时抛出（传输异常由 translateConsultError 翻译；调用方禁止忽略）
 */
export function createConsultApi(options: ConsultApiOptions = {}): ConsultPort {
  const fetchImpl = options.fetchImpl ?? fetch;
  const onDiagnosticSink: SseDiagnosticSink =
    options.onDiagnostic ?? ((diagnostic) => logDiagnostic('sse', diagnostic));

  /**
   * 调用一个 202 受理型端点。
   *
   * 契约只规定 202 表示已受理，没有规定响应体；空体是合法响应，而共享的 request()
   * 用 response.json() 收尾，空体会抛 SyntaxError。这里把「2xx 但没有 JSON 正文」当作
   * 成功（状态码已由 request 判定），其余异常照常抛出——不静默吞真正的失败。
   */
  async function requestAccepted(path: string): Promise<void> {
    try {
      await request<unknown>(path, { method: 'POST' });
    } catch (error) {
      if (error instanceof SyntaxError) return;
      throw error;
    }
  }

  return {
    async createSession(input: CreateSessionInput = {}): Promise<CreateSessionResponse> {
      try {
        return await request<CreateSessionResponse>('/consult/sessions', {
          method: 'POST',
          body: JSON.stringify(input),
        });
      } catch (error) {
        throw translateConsultError(error);
      }
    },

    async listSessions(input: ListSessionsInput): Promise<ListSessionsResponse> {
      try {
        const params = new URLSearchParams();
        if (input.cursor !== undefined && input.cursor !== null) params.set('cursor', input.cursor);
        if (input.limit !== undefined) params.set('limit', String(input.limit));
        const query = params.toString();
        return await request<ListSessionsResponse>(`/consult/sessions${query === '' ? '' : `?${query}`}`);
      } catch (error) {
        throw translateConsultError(error);
      }
    },

    async loadHistory(sessionId: string): Promise<ListMessagesResponse> {
      try {
        return await request<ListMessagesResponse>(`/consult/sessions/${encodeURIComponent(sessionId)}/messages`);
      } catch (error) {
        throw translateConsultError(error);
      }
    },

    async listSkills(): Promise<SkillSummary[]> {
      // 目录替身点：HTTP/SSE 契约第 3～6 节没有技能目录端点，此处按已确认的三个技能标识
      // 返回（domain/skills 的文件头写明出处与替身理由，并登记在交付报告未决问题节）。
      return Promise.resolve([...SKILL_CATALOG]);
    },

    async sendMessage(sessionId: string, payload: PostMessageRequest): Promise<PostMessageResponse> {
      try {
        return await request<PostMessageResponse>(`/consult/sessions/${encodeURIComponent(sessionId)}/messages`, {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      } catch (error) {
        throw translateConsultError(error);
      }
    },

    async cancelRun(runId: string): Promise<void> {
      try {
        await requestAccepted(`/consult/runs/${encodeURIComponent(runId)}/cancel`);
      } catch (error) {
        throw translateConsultError(error);
      }
    },

    async skipOnboarding(sessionId: string): Promise<void> {
      try {
        await requestAccepted(`/consult/sessions/${encodeURIComponent(sessionId)}/onboarding/skip`);
      } catch (error) {
        throw translateConsultError(error);
      }
    },

    async emergencyStart(payload: EmergencyRequest): Promise<EmergencyResponse> {
      try {
        return await request<EmergencyResponse>('/consult/emergency', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      } catch (error) {
        throw translateConsultError(error);
      }
    },

    async *streamRun(input: StreamRunInput): AsyncGenerator<RunEvent, void> {
      // 重连通告的中转：SSE 层的诊断是传输细节，上层只关心「正在重连 / 已恢复」。
      let reconnecting = false;
      let resumed = false;
      const onDiagnostic: SseDiagnosticSink = (diagnostic) => {
        if (diagnostic.reason === 'reconnect') {
          reconnecting = true;
          input.onNotice?.({ kind: 'reconnecting', attempt: diagnostic.attempt ?? 1 });
        }
        onDiagnosticSink(diagnostic);
      };

      try {
        for await (const event of subscribeRunEvents({
          runId: input.runId,
          signal: input.signal,
          ...(input.lastEventId === undefined ? {} : { lastEventId: input.lastEventId }),
          fetchImpl,
          onDiagnostic,
        })) {
          if (reconnecting && !resumed) {
            resumed = true;
            input.onNotice?.({ kind: 'resumed' });
          }
          yield event;
        }
      } catch (error) {
        // SSE 的 401 不经过 http/client 的 401 处置（那条路只覆盖 JSON 请求），
        // 因此这里显式通知 app 层清状态跳登录，再翻译成领域失败。
        if (error instanceof HttpError && error.status === 401) options.onUnauthorized?.();
        throw translateConsultError(error);
      }
    },
  };
}
