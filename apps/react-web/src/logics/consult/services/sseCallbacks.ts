/**
 * CSLT-08 SSE 事件回调工厂 —— 将 SSE 事件映射为 Zustand Store 状态变更。
 *
 * 职责：
 * - 接收 Store 的 get/set 引用，返回 SseStreamParserCallbacks
 * - 每个回调封装一个明确的业务含义（chunk → 段落追加，done → 状态转换等）
 * - 与 SseStreamParser 解耦——parser 不感知 Zustand
 *
 * 设计依据：CSLT-08 落地规范 §1.7
 */

import { ConsultErrorCode } from '../types/index';
import type {
  ConsultSessionState,
  CrisisLevel,
  PlanSection,
  DoneEventPayload,
} from '../types/index';
import type { RequestId } from '../consult.contract';
import {
  transitionTo,
  createMessageItem,
  sectionsToPlanSections,
} from '../store/stateMachine';
import type { SseStreamParserCallbacks } from './sseParser';

// ============================================================================
// 轻量状态视图 —— sseCallbacks 不依赖 Zustand 完整类型
// ============================================================================

/** SSE 回调所需的最小状态读接口。 */
interface ConsultStateView {
  sessionState: ConsultSessionState;
  planSections: PlanSection[];
  accumulatedText: string;
  lastSequence: number;
  messages: { messageType: string; metadata?: { isCompleted?: boolean } }[];
  ticketGuide: { show: boolean; riskLevel: 'normal' | 'high_risk' };
  behaviorDescription: string;
  _requestId: RequestId;
  _reconnectAttempt: number;
}

/** SSE 回调所需的最小状态写接口（兼容 Zustand set 重载签名）。 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type SetFn = (...args: any[]) => any;

// ============================================================================
// 回调工厂
// ============================================================================

/**
 * 为 SseStreamParser 创建事件回调。
 *
 * @param get - Zustand Store.getState()（返回 ConsultStateView 的超集）
 * @param set - Zustand Store.setState()（接受 SetFn 的超集）
 * @param requestId - 当前咨询的幂等请求 ID
 */
export function createSseCallbacks(
  get: () => ConsultStateView,
  set: SetFn,
  requestId: RequestId,
): SseStreamParserCallbacks {
  return {
    // ---- onChunk：增量追加文本到对应段落 ----
    onChunk: (chunkData) => {
      const state = get();

      // 首个真实内容 chunk 到达 → 从 submitting/submit_failed 切到 streaming
      if (state.sessionState === 'submitting') {
        set({ sessionState: transitionTo(state.sessionState, 'streaming') });
      }

      const chunkSection = chunkData.section ?? null;
      const updatedSections = appendToPlanSections(
        state.planSections,
        chunkSection,
        chunkData.text,
      );
      set({
        accumulatedText: state.accumulatedText + chunkData.text,
        lastSequence: chunkData.sequence,
        planSections: updatedSections,
      });
    },

    // ---- onDone：流正常结束——转换到终态 + 归档 ----
    onDone: (doneData: DoneEventPayload) => {
      const state = get();

      if (state.sessionState === 'submitting') {
        try {
          set({
            sessionState: transitionTo(state.sessionState, 'submit_failed'),
            errorCode: ConsultErrorCode.SUBMIT_SERVER_ERROR,
          });
        } catch { /* 状态已变更 */ }
        return;
      }

      if (state.sessionState !== 'streaming') return;

      const crisisLevel = doneData?.crisis_level || 'mild';
      const referencedSliceIds: string[] = doneData?.referenced_slice_ids ?? [];
      const referencedCases = doneData?.referenced_cases ?? [];
      const verdict = doneData?.verdict || 'PASS';

      const doneSections = doneData?.sections ?? {};
      const planSections = sectionsToPlanSections(doneSections);

      const shouldShowTicket = verdict === 'FORCE_BLOCK' || verdict === 'APPEND_WARNING';
      const nextState = shouldShowTicket ? 'ticket_guide' : 'completed';
      const next = transitionTo(state.sessionState, nextState);

      const updatedMessages = state.messages.map((msg) => {
        if (msg.messageType === 'system_plan' && !msg.metadata?.isCompleted) {
          return { ...msg, metadata: { ...msg.metadata, isCompleted: true } };
        }
        return msg;
      });

      set({
        sessionState: next,
        messages: updatedMessages,
        crisisLevel: crisisLevel as CrisisLevel,
        referencedSliceIds,
        referencedCases,
        planSections,
        ticketGuide: shouldShowTicket
          ? { show: true, riskLevel: verdict === 'FORCE_BLOCK' ? 'high_risk' : 'normal' }
          : state.ticketGuide,
      });
    },

    // ---- onError：致命/非致命分类处理 ----
    onError: (errorData) => {
      const state = get();
      const isFatal =
        errorData.error_code === 'GENERATION_FAILED' ||
        errorData.error_code === 'SESSION_NOT_FOUND';

      if (!isFatal) {
        console.debug('sse_non_fatal_error', { errorCode: errorData.error_code, timestamp: Date.now() });
        return;
      }

      if (state.lastSequence === 0) {
        try {
          set({
            sessionState: transitionTo(state.sessionState, 'submit_failed'),
            errorCode: ConsultErrorCode.SUBMIT_SERVER_ERROR,
          });
        } catch { /* 静默 */ }
      } else {
        handleStreamFailure(get, set, ConsultErrorCode.SSE_CONNECTION_BROKEN);
      }
    },

    onHeartbeat: () => { /* parser 内部管理计时器 */ },

    onReconnect: (attempt: number) => {
      set({ _reconnectAttempt: attempt });
    },

    onReconnectFailed: () => {
      const state = get();
      if (state.lastSequence === 0) {
        try {
          set({
            sessionState: transitionTo(state.sessionState, 'submit_failed'),
            errorCode: ConsultErrorCode.SUBMIT_NETWORK_ERROR,
          });
        } catch { /* 静默 */ }
      } else {
        handleStreamFailure(get, set, ConsultErrorCode.SSE_CONNECTION_BROKEN);
      }
    },

    onNoDataTimeout: () => {
      set({ errorCode: ConsultErrorCode.SSE_NO_DATA_TIMEOUT });
    },
  };
}

// ============================================================================
// 内部工具函数
// ============================================================================

function appendToPlanSections(
  sections: PlanSection[],
  sectionTitle: string | null,
  text: string,
): PlanSection[] {
  if (!sectionTitle || !text) return sections;

  const existingIdx = sections.findIndex((sec) => sec.title === sectionTitle);

  if (existingIdx === -1) {
    return [...sections, { title: sectionTitle, contents: [text], isCompleted: false }];
  }

  return sections.map((sec, idx) => {
    if (idx !== existingIdx) return sec;
    const lastIdx = sec.contents.length - 1;
    if (lastIdx >= 0 && !sec.isCompleted) {
      const updated = [...sec.contents];
      updated[lastIdx] = updated[lastIdx] + text;
      return { ...sec, contents: updated };
    }
    return { ...sec, contents: [...sec.contents, text] };
  });
}

function handleStreamFailure(
  get: () => ConsultStateView,
  set: SetFn,
  errorCode: ConsultErrorCode,
): void {
  const state = get();
  try {
    set({ sessionState: transitionTo(state.sessionState, 'stream_failed'), errorCode });

    const partialSections = state.planSections.map((sec) => {
      if (!sec.isCompleted) return { ...sec, isPartial: true };
      return sec;
    });

    const promptMsg = createMessageItem(
      'system',
      '生成中断，以下为不完整建议，可能缺失部分段落',
      'system_prompt',
    );

    set({
      planSections: partialSections,
      messages: [...get().messages, promptMsg],
    });
  } catch { /* 静默 */ }
}
