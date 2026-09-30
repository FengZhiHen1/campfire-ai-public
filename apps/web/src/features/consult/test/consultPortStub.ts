/**
 * 模块: features/consult/test/consultPortStub
 * 职责: ConsultPort 的测试替身——脚本化事件流与调用记录
 * 数据来源:
 *   - features/consult/application/ports: MUST — 端口契约（替身必须实现同一接口）
 * 边界:
 *   - 依赖: application/ports、test/fixtures
 *   - 被依赖: features/consult 的适配器与组件测试
 * 禁止行为:
 *   - 禁止把替身用于生产路径（生产用 infrastructure/consult/consultPort）
 *   - 禁止用替身伪造「真实后端已联调」的结论（本包不接真实后端）
 */

import { vi } from 'vitest';

import type {
  CreateSessionInput,
  ConsultPort,
  ListSessionsInput,
  StreamRunInput,
} from '../application/ports';
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
import { SKILL_CATALOG } from '../domain/skills';
import { historyResponse } from './fixtures';

/** 一次订阅请求的记录。 */
export interface StreamCall {
  runId: string;
  lastEventId: number | undefined;
  signal: AbortSignal;
}

/** 端口替身（额外暴露记录与脚本注入）。 */
export interface ConsultPortStub extends ConsultPort {
  /** 每次 sendMessage 的入参。 */
  sendCalls: { sessionId: string; payload: PostMessageRequest }[];
  /** 每次 streamRun 的入参。 */
  streamCalls: StreamCall[];
  /** 每次 cancelRun 的 runId。 */
  cancelCalls: string[];
  /** 追加一段脚本事件（每次 streamRun 消费一段；用尽后返回空流）。 */
  script(events: readonly RunEvent[]): void;
  /** 让下一次 streamRun 抛错（模拟传输/契约失败）。 */
  failNextStream(error: unknown): void;
}

/** 替身装配选项。 */
export interface ConsultPortStubOptions {
  history?: ListMessagesResponse;
  sessions?: ListSessionsResponse;
  /** 首页列表请求抛错（错误态用）。 */
  sessionsError?: unknown;
  createSession?: CreateSessionResponse | Error;
  emergency?: EmergencyResponse | Error;
  cancelError?: unknown;
}

/** 一段脚本：一批事件，或一次失败。 */
type ScriptEntry = { kind: 'events'; events: readonly RunEvent[] } | { kind: 'error'; error: unknown };

/**
 * 建一个端口替身。
 *
 * 事件流按「每次 streamRun 消费一段脚本」的方式工作，这样一条测试里的多次发送
 * （例如提问卡提交后的第二次运行）可以各自有独立的事件序列。
 */
export function createConsultPortStub(options: ConsultPortStubOptions = {}): ConsultPortStub {
  const scripts: ScriptEntry[] = [];
  const sendCalls: { sessionId: string; payload: PostMessageRequest }[] = [];
  const streamCalls: StreamCall[] = [];
  const cancelCalls: string[] = [];

  const stub: ConsultPortStub = {
    sendCalls,
    streamCalls,
    cancelCalls,

    script: (events) => {
      scripts.push({ kind: 'events', events });
    },

    failNextStream: (error) => {
      scripts.push({ kind: 'error', error });
    },

    createSession: vi.fn(async (input?: CreateSessionInput): Promise<CreateSessionResponse> => {
      void input;
      const configured = options.createSession;
      if (configured instanceof Error) throw configured;
      return configured ?? { session_id: 's-new', support_object_id: 'o1', onboarding_pending: false };
    }),

    listSessions: vi.fn(async (input: ListSessionsInput): Promise<ListSessionsResponse> => {
      void input;
      if (options.sessionsError !== undefined) throw options.sessionsError;
      return options.sessions ?? { items: [], next_cursor: null };
    }),

    loadHistory: vi.fn(async (): Promise<ListMessagesResponse> => options.history ?? historyResponse([])),

    listSkills: vi.fn(async () => [...SKILL_CATALOG]),

    sendMessage: vi.fn(async (sessionId: string, payload: PostMessageRequest): Promise<PostMessageResponse> => {
      sendCalls.push({ sessionId, payload });
      return { run_id: `run-${String(sendCalls.length)}`, session_id: sessionId };
    }),

    // eslint 之外的理由：async generator 才是端口的真实形状（技术设计第 1 节），
    // 用数组模拟会丢掉「事件是逐条到达」这一性质。
    streamRun: (input: StreamRunInput): AsyncIterable<RunEvent> => {
      streamCalls.push({ runId: input.runId, lastEventId: input.lastEventId, signal: input.signal });
      const next: ScriptEntry = scripts.shift() ?? { kind: 'events', events: [] };
      return (async function* stream(): AsyncGenerator<RunEvent, void> {
        if (next.kind === 'error') throw next.error;
        for (const event of next.events) {
          if (input.signal.aborted) return;
          yield event;
        }
      })();
    },

    cancelRun: vi.fn(async (runId: string): Promise<void> => {
      cancelCalls.push(runId);
      if (options.cancelError !== undefined) throw options.cancelError;
    }),

    emergencyStart: vi.fn(async (payload: EmergencyRequest): Promise<EmergencyResponse> => {
      void payload;
      const configured = options.emergency;
      if (configured instanceof Error) throw configured;
      return configured ?? { session_id: 's-emg', run_id: 'run-emg' };
    }),
  };

  return stub;
}
