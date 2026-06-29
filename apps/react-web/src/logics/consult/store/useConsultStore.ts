/**
 * CSLT-08 咨询编排 Zustand Store。
 *
 * 职责：
 * - 管理 8 种会话状态、消息列表、SSE 流式数据、工单引导标记
 * - 通过 persist 中间件持久化消息列表到 Taro Storage
 * - 导出 useConsultStore hook
 *
 * 绝对约束：
 * - 所有 sessionState 变更必须通过 transitionTo()
 * - submitConsult() 入口有并发防护（submitting/streaming 阻止）
 * - addMessage() 有消息裁剪逻辑（>= 200 → slice(50)）
 * - 所有中文文案通过 getErrorMessage() 映射表管理
 * - SSE 事件处理委托给 services/sseCallbacks.ts
 *
 * 设计依据：CSLT-08 落地规范 §1.4 §1.5 §1.7 §1.8 §1.9
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
// React 移植版：Taro Storage → localStorage，导航 → window.location

import {
  type ConsultSessionState,
  type BehaviorTypeCategory,
  type CrisisLevel,
  type ValidationVerdict,
  type PlanSection,
  type TicketGuide,
  type MessageItem,
  type ReferencedCase,
  ConsultErrorCode,
} from '../types/index';
import {
  transitionTo,
  createMessageItem,
  getErrorMessage,
  createEmptySections,
} from './stateMachine';
import { SseStreamParser } from '../services/sseParser';
import { consultApi } from '../services/consultApi';
import { createSseCallbacks } from '../services/sseCallbacks';
import type { ConsultSubmitResponse } from '../services/consultApi';
import { isValidConsultSubmitRequest } from '../consult.contract';
import type { RequestId } from '../consult.contract';

// ============================================================================
// Store 类型定义
// ============================================================================

/** Store 状态 + Actions 的合并类型 */
export interface ConsultStore extends ConsultSessionStoreState {
  // ---------- Actions ----------
  startConsult: () => void;
  setBehaviorTypes: (types: BehaviorTypeCategory[]) => void;
  setBehaviorDescription: (desc: string) => void;
  setEmotionLevel: (level: '轻' | '中' | '重') => void;
  setSelectedProfile: (profileId: string | undefined) => void;
  submitConsult: () => Promise<void>;
  cancelSelection: () => void;
  retrySubmit: () => Promise<void>;
  goBackToSelecting: () => void;
  retryStream: () => Promise<void>;
  startNewConsult: () => void;
  goToTicket: () => void;
  addMessage: (msg: MessageItem) => void;
}

/** Store 状态部分（不含 Actions） */
interface ConsultSessionStoreState {
  sessionState: ConsultSessionState;
  behaviorTypeSelection: BehaviorTypeCategory[];
  behaviorDescription: string;
  accumulatedText: string;
  planSections: PlanSection[];
  lastSequence: number;
  crisisLevel?: CrisisLevel;
  confidenceScore?: number;
  validationVerdict?: ValidationVerdict;
  ticketGuide: TicketGuide;
  messages: MessageItem[];
  errorCode?: ConsultErrorCode;
  ticketGuideShown: boolean;
  emotionLevel?: '轻' | '中' | '重';
  selectedProfileId?: string;
  referencedSliceIds: string[];
  referencedCases: ReferencedCase[];
  _requestId: RequestId;
  _reconnectAttempt: number;
}

// ============================================================================
// 初始状态工厂
// ============================================================================

function createInitialState(): ConsultSessionStoreState {
  return {
    sessionState: 'idle',
    behaviorTypeSelection: [],
    behaviorDescription: '',
    accumulatedText: '',
    planSections: createEmptySections(),
    lastSequence: 0,
    crisisLevel: undefined,
    confidenceScore: undefined,
    validationVerdict: undefined,
    ticketGuide: { show: false, riskLevel: 'normal' },
    messages: [],
    errorCode: undefined,
    ticketGuideShown: false,
    emotionLevel: '中',
    selectedProfileId: undefined,
    referencedSliceIds: [],
    referencedCases: [],
    _requestId: '' as RequestId,
    _reconnectAttempt: 0,
  };
}

// ============================================================================
// Taro Storage 适配器
// ============================================================================

const taroStorageAdapter = {
  getItem: (name: string): string | null => {
    try {
      return localStorage.getItem(name) ?? null;
    } catch {
      return null;
    }
  },
  setItem: (name: string, value: string): void => {
    try {
      localStorage.setItem(name, value);
    } catch {
      console.debug('persist_write_failed', { key: name });
    }
  },
  removeItem: (name: string): void => {
    try {
      localStorage.removeItem(name);
    } catch { /* 删除失败忽略 */ }
  },
};

// ============================================================================
// 请求 ID 生成
// ============================================================================

function generateRequestId(): RequestId {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID() as RequestId;
  }
  // 微信小程序等环境无 crypto.randomUUID，手动生成 UUID v4
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  }) as RequestId;
}

// ============================================================================
// Store 创建
// ============================================================================

export const useConsultStore = create<ConsultStore>()(
  persist(
    (set, get) => ({
      ...createInitialState(),

      // ===== startConsult =====
      startConsult: (): void => {
        const { sessionState } = get();
        if (sessionState !== 'idle') return;
        const next = transitionTo(sessionState, 'selecting_behavior');
        set({
          sessionState: next,
          messages: [],
          accumulatedText: '',
          planSections: createEmptySections(),
          lastSequence: 0,
          errorCode: undefined,
          ticketGuide: { show: false, riskLevel: 'normal' },
          ticketGuideShown: false,
          emotionLevel: '中',
          crisisLevel: undefined,
          confidenceScore: undefined,
          validationVerdict: undefined,
          _requestId: '' as RequestId,
          _reconnectAttempt: 0,
        });
      },

      // ===== 输入 setter =====
      setBehaviorTypes: (types) => set({ behaviorTypeSelection: types }),
      setBehaviorDescription: (desc) => set({ behaviorDescription: desc }),
      setEmotionLevel: (level) => set({ emotionLevel: level }),
      setSelectedProfile: (profileId) => set({ selectedProfileId: profileId }),

      // ===== submitConsult =====
      submitConsult: async (): Promise<void> => {
        const state = get();

        // 并发防护
        if (state.sessionState === 'submitting' || state.sessionState === 'streaming') {
          set({ errorCode: ConsultErrorCode.CONCURRENT_SUBMIT_BLOCKED });
          return;
        }

        // 输入校验（契约守卫）
        if (!isValidConsultSubmitRequest({
          behavior_description: state.behaviorDescription,
          behavior_type_selection: state.behaviorTypeSelection,
        })) {
          set({ errorCode: ConsultErrorCode.INPUT_VALIDATION_FAILED });
          return;
        }

        // 状态转换：selecting_behavior → submitting
        set({
          sessionState: transitionTo(state.sessionState, 'submitting'),
          errorCode: undefined,
          _requestId: '' as RequestId,
          _reconnectAttempt: 0,
        });

        const requestId = generateRequestId();
        set({ _requestId: requestId });

        const { behaviorTypeSelection, behaviorDescription, emotionLevel, selectedProfileId } = get();

        try {
          const response: ConsultSubmitResponse = await consultApi.submitConsult(
            behaviorDescription,
            behaviorTypeSelection,
            selectedProfileId,
            emotionLevel,
            requestId,
          );

          const { stream_url, session_id } = response;

          // 保持在 submitting，等待第一个真实 SSE chunk 到达后再切 streaming
          // （心跳不算，只有内容 chunk 才触发状态跳转）

          const sseCallbacks = createSseCallbacks(get, set, requestId);

          if (import.meta.env.VITE_USE_MOCK === 'true') {
            // eslint-disable-next-line @typescript-eslint/no-var-requires
            const { MockSseSimulator: SimCls } = require('../../shared/services/mock/mockSseSimulator');
            const simulator = new SimCls(sseCallbacks, behaviorDescription);
            await simulator.connect(stream_url);
          } else {
            const parser = new SseStreamParser(
              {
                reconnectMaxRetries: 3,
                reconnectDelays: [1000, 2000, 5000],
                heartbeatTimeout: 15000,
                connectTimeout: 10000,
                streamNoDataTimeout: 20000,
              },
              sseCallbacks,
            );

            const extraHeaders: Record<string, string> = {
              'ngrok-skip-browser-warning': '1',
            };
            if (session_id) {
              extraHeaders['X-Session-Id'] = session_id;
            }

            await parser.connect(stream_url, extraHeaders);
          }
        } catch (error: unknown) {
          const currentState = get();
          if (currentState.sessionState !== 'submitting') return;

          const isNetworkError =
            error instanceof TypeError ||
            (error instanceof Error &&
              (error.message.includes('network') ||
                error.message.includes('Network') ||
                error.message.includes('timeout') ||
                error.message.includes('abort')));

          const errorCode = isNetworkError
            ? ConsultErrorCode.SUBMIT_NETWORK_ERROR
            : ConsultErrorCode.SUBMIT_SERVER_ERROR;

          try {
            set({
              sessionState: transitionTo(currentState.sessionState, 'submit_failed'),
              errorCode,
            });
          } catch { /* 状态已变更 */ }

          console.debug('submit_failed', {
            errorCode,
            timestamp: Date.now(),
            errorMessage: error instanceof Error ? error.message : String(error),
          });
        }
      },

      // ===== cancelSelection =====
      cancelSelection: (): void => {
        const { sessionState } = get();
        if (sessionState !== 'selecting_behavior') return;
        set({ sessionState: transitionTo(sessionState, 'idle') });
      },

      // ===== retrySubmit =====
      retrySubmit: async (): Promise<void> => {
        const { sessionState } = get();
        if (sessionState !== 'submit_failed') return;
        set({ sessionState: transitionTo(sessionState, 'submitting'), errorCode: undefined });
        await get().submitConsult();
      },

      // ===== goBackToSelecting =====
      goBackToSelecting: (): void => {
        const { sessionState } = get();
        if (sessionState !== 'submit_failed' && sessionState !== 'stream_failed') return;
        set({
          sessionState: transitionTo(sessionState, 'selecting_behavior'),
          errorCode: undefined,
          accumulatedText: '',
          planSections: createEmptySections(),
          lastSequence: 0,
        });
      },

      // ===== retryStream =====
      retryStream: async (): Promise<void> => {
        const { sessionState } = get();
        if (sessionState !== 'stream_failed') return;
        set({
          sessionState: transitionTo(sessionState, 'submitting'),
          errorCode: undefined,
          accumulatedText: '',
          planSections: createEmptySections(),
          lastSequence: 0,
        });
        await get().submitConsult();
      },

      // ===== startNewConsult =====
      startNewConsult: (): void => {
        const { sessionState } = get();
        if (sessionState !== 'completed' && sessionState !== 'ticket_guide') return;
        set({
          ...createInitialState(),
          sessionState: transitionTo(sessionState, 'selecting_behavior'),
        });
      },

      // ===== goToTicket =====
      goToTicket: (): void => {
        window.location.href = '/tickets/detail';
      },

      // ===== addMessage =====
      addMessage: (msg: MessageItem): void => {
        set((state) => {
          const newMessages = [...state.messages, msg];
          if (newMessages.length >= 200) {
            return { messages: newMessages.slice(50) };
          }
          return { messages: newMessages };
        });
      },
    }),
    {
      name: 'consult-session',
      storage: createJSONStorage(() => taroStorageAdapter),
      merge: (persisted, current) => ({
        ...current,
        ...(persisted as object),
        sessionState: 'idle' as const,
      }),
      partialize: (state) => ({
        messages: state.messages,
        behaviorTypeSelection: state.behaviorTypeSelection,
        behaviorDescription: state.behaviorDescription,
      }),
    },
  ),
);

// ============================================================================
// 工具函数导出（供 useConsult Hook 使用）
// ============================================================================

export { getErrorMessage, createEmptySections, createMessageItem };
export { sectionsToPlanSections } from './stateMachine';
