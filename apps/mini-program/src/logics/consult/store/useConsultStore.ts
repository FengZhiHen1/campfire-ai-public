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
 *
 * 设计依据：CSLT-08 落地规范 §1.4 §1.5 §1.7 §1.8 §1.9
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import Taro from '@tarojs/taro';

import {
  type ConsultSessionState,
  type BehaviorTypeCategory,
  type CrisisLevel,
  type ValidationVerdict,
  type PlanSection,
  type TicketGuide,
  type MessageItem,
  type ReferencedCase,
  type DoneEventPayload,
  ConsultErrorCode,
} from '../types/index';
import {
  transitionTo,
  createMessageItem,
  getErrorMessage,
} from './stateMachine';
import { SseStreamParser } from '../services/sseParser';
import { consultApi } from '../services/consultApi';
import type { ConsultSubmitResponse } from '../services/consultApi';

// ============================================================================
// 常量定义
// ============================================================================

/**
 * 四段式方案标题常量列表。
 * 与后端 CSLT-03 解析的 JSON key 保持一致。
 */
const SECTION_KEYS: readonly string[] = [
  '即时安全干预动作',
  '情绪安抚话术',
  '后续观察指标',
  '就医判断标准',
] as const;

// ============================================================================
// Store 类型定义
// ============================================================================

/** Store 状态 + Actions 的合并类型 */
export interface ConsultStore extends ConsultSessionStoreState {
  // ---------- Actions ----------
  /** 开始新咨询：idle -> selecting_behavior */
  startConsult: () => void;
  /** 更新行为类型选择 */
  setBehaviorTypes: (types: BehaviorTypeCategory[]) => void;
  /** 更新行为描述文本 */
  setBehaviorDescription: (desc: string) => void;
  /** 设置情绪等级 */
  setEmotionLevel: (level: '轻' | '中' | '重') => void;
  /** 设置关联档案 */
  setSelectedProfile: (profileId: string | undefined) => void;
  /** 提交咨询：selecting_behavior -> submitting */
  submitConsult: () => Promise<void>;
  /** 取消行为选择：selecting_behavior -> idle */
  cancelSelection: () => void;
  /** 重试提交：submit_failed -> submitting */
  retrySubmit: () => Promise<void>;
  /** 返回修改：submit_failed | stream_failed -> selecting_behavior，保留表单数据 */
  goBackToSelecting: () => void;
  /** 重试流式接收：stream_failed -> submitting（重新生成） */
  retryStream: () => Promise<void>;
  /** 开始新一轮咨询：completed | ticket_guide -> selecting_behavior */
  startNewConsult: () => void;
  /** 跳转工单模块 */
  goToTicket: () => void;
  /** 添加消息（含裁剪逻辑） */
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
  /** 情绪等级选择 */
  emotionLevel?: '轻' | '中' | '重';
  /** 关联档案 ID */
  selectedProfileId?: string;
  /** 参考案例切片 ID 列表 */
  referencedSliceIds: string[];
  /** 参考案例简要信息 */
  referencedCases: ReferencedCase[];
  /** 幂等请求 ID（运行时，不持久化） */
  _requestId: string;
  /** SSE 重连计数器（运行时，不持久化） */
  _reconnectAttempt: number;
}

// ============================================================================
// 初始状态工厂
// ============================================================================

/**
 * 创建初始状态。
 * 用于 store 初始化和 startNewConsult 重置。
 */
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
    emotionLevel: undefined,
    selectedProfileId: undefined,
    referencedSliceIds: [],
    referencedCases: [],
    _requestId: '',
    _reconnectAttempt: 0,
  };
}

/**
 * 创建四个空的 PlanSection。
 */
function createEmptySections(): PlanSection[] {
  return SECTION_KEYS.map((title) => ({
    title,
    contents: [],
    isCompleted: false,
  }));
}

/**
 * 增量追加文本到 planSections 中对应段落的末尾。
 * 用于流式渲染中按 section 标记实时更新结构化卡片。
 *
 * @param sections - 当前的 PlanSection 数组
 * @param sectionTitle - chunk 所属的段落标题，null 表示 JSON 语法字符（仅计入 accumulatedText）
 * @param text - 要追加的文本
 */
function appendToPlanSections(
  sections: PlanSection[],
  sectionTitle: string | null,
  text: string,
): PlanSection[] {
  if (!sectionTitle || !text) return sections;
  return sections.map((sec) => {
    if (sec.title !== sectionTitle) return sec;
    const lastIdx = sec.contents.length - 1;
    if (lastIdx >= 0 && !sec.isCompleted) {
      // 追加到最后一个条目（流式渲染中同一条建议可能跨多个 chunk）
      const updated = [...sec.contents];
      updated[lastIdx] = updated[lastIdx] + text;
      return { ...sec, contents: updated };
    }
    // 新条目或已完成段落
    return { ...sec, contents: [...sec.contents, text] };
  });
}

/**
 * 将后端下发的 sections dict 转换为前端 PlanSection 数组。
 * sections 由后端从 LLM JSON 输出解析，无需前端正则处理。
 */
function sectionsToPlanSections(sections: Record<string, string[]>): PlanSection[] {
  return SECTION_KEYS.map((title) => {
    const contents = sections[title] ?? [];
    return {
      title,
      contents: Array.isArray(contents) ? contents : [],
      isCompleted: contents.length > 0,
    };
  });
}

// ============================================================================
// Taro Storage 适配器（用于 Zustand persist 中间件）
// ============================================================================

/**
 * Zustand persist 中间件的 Taro Storage 适配器。
 * 使用 Taro 同步 Storage API（getStorageSync/setStorageSync/removeStorageSync）。
 */
const taroStorageAdapter = {
  getItem: (name: string): string | null => {
    try {
      const value = Taro.getStorageSync(name);
      return value ?? null;
    } catch {
      return null;
    }
  },
  setItem: (name: string, value: string): void => {
    try {
      Taro.setStorageSync(name, value);
    } catch {
      // 写入失败仅记录日志，不抛异常
      console.debug('persist_write_failed', { key: name });
    }
  },
  removeItem: (name: string): void => {
    try {
      Taro.removeStorageSync(name);
    } catch {
      // 删除失败忽略
    }
  },
};

// ============================================================================
// Store 创建
// ============================================================================

/**
 * 全局咨询编排 Store。
 * 所有组件通过 useConsult() Hook 间接访问，禁止直接 import 本 Store。
 *
 * 持久化策略：
 *   - 仅持久化 messages 和输入状态（跨会话恢复）
 *   - sessionState 不持久化（会话状态时效性强）
 */
export const useConsultStore = create<ConsultStore>()(
  persist(
    (set, get) => ({
      // ===== 初始状态 =====
      ...createInitialState(),

      // ===== startConsult =====
      startConsult: (): void => {
        const { sessionState } = get();
        if (sessionState !== 'idle') {
          // 非 idle 状态静默忽略
          return;
        }
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
          crisisLevel: undefined,
          confidenceScore: undefined,
          validationVerdict: undefined,
          _requestId: '',
          _reconnectAttempt: 0,
        });
      },

      // ===== setBehaviorTypes =====
      setBehaviorTypes: (types: BehaviorTypeCategory[]): void => {
        set({ behaviorTypeSelection: types });
      },

      // ===== setBehaviorDescription =====
      setBehaviorDescription: (desc: string): void => {
        set({ behaviorDescription: desc });
      },
      setEmotionLevel: (level: '轻' | '中' | '重'): void => {
        set({ emotionLevel: level });
      },
      setSelectedProfile: (profileId: string | undefined): void => {
        set({ selectedProfileId: profileId });
      },

      // ===== submitConsult =====
      submitConsult: async (): Promise<void> => {
        const currentState = get();

        // ----- 并发防护 -----
        if (currentState.sessionState === 'submitting' || currentState.sessionState === 'streaming') {
          set({ errorCode: ConsultErrorCode.CONCURRENT_SUBMIT_BLOCKED });
          return;
        }

        // ----- 输入校验（防御性，Hook 层 isInputValid 已拦截按钮）-----
        if (
          currentState.behaviorTypeSelection.length === 0 ||
          currentState.behaviorDescription.trim() === ''
        ) {
          set({ errorCode: ConsultErrorCode.INPUT_VALIDATION_FAILED });
          return;
        }

        // ----- 状态转换：selecting_behavior -> submitting -----
        const next = transitionTo(currentState.sessionState, 'submitting');
        set({
          sessionState: next,
          errorCode: undefined,
          _requestId: '',
          _reconnectAttempt: 0,
        });

        // ----- 生成幂等请求 ID -----
        const requestId: string =
          typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
            ? crypto.randomUUID()
            : `req-${Math.random().toString(36).substring(2)}-${Date.now().toString(36)}`;
        set({ _requestId: requestId });

        // ----- 组装请求体 -----
        const { behaviorTypeSelection, behaviorDescription, emotionLevel, selectedProfileId } = get();

        try {
          // ----- 发起 HTTP POST 请求 -----
          const response: ConsultSubmitResponse = await consultApi.submitConsult(
            behaviorDescription,
            behaviorTypeSelection,
            selectedProfileId,
            emotionLevel,
            requestId,
          );

          const { stream_url, confidence_output, session_id, referenced_slice_ids, disclaimer, generation_time_ms, is_partial, finish_reason, ttft_ms, token_input, token_output } = response;

          // ----- 存储置信度数据（供 done 事件后使用）-----
          const updates: Partial<ConsultSessionStoreState> = {};
          if (confidence_output) {
            updates.confidenceScore = confidence_output.confidence_score;
            updates.validationVerdict = confidence_output.verdict;
          }

          // ----- 创建 SSE 解析器并连接 -----
          const parser = new SseStreamParser(
            {
              reconnectMaxRetries: 3,
              reconnectDelays: [1000, 2000, 5000],
              heartbeatTimeout: 15000,
              connectTimeout: 10000,
              streamNoDataTimeout: 20000,
            },
            {
              // ---- onChunk ----
              onChunk: (chunkData: { text: string; sequence: number; section?: string | null }): void => {
                const state = get();
                const newSeq = chunkData.sequence;
                const chunkSection = chunkData.section ?? null;

                // 仅在 submitting 或 streaming 状态下处理 chunk
                if (state.sessionState !== 'submitting' && state.sessionState !== 'streaming') {
                  return;
                }

                // 首个内容 chunk → 触发 streaming 状态转换
                const isFirstChunk = state.lastSequence === 0;

                if (isFirstChunk) {
                  try {
                    const sNext = transitionTo(state.sessionState, 'streaming');
                    const initMsg = createMessageItem('system', '', 'system_plan', {
                      isOriginal: true,
                    });
                    const updatedSections = appendToPlanSections(
                      state.planSections,
                      chunkSection,
                      chunkData.text,
                    );
                    set({
                      sessionState: sNext,
                      accumulatedText: state.accumulatedText + chunkData.text,
                      lastSequence: newSeq,
                      planSections: updatedSections,
                      messages: [...state.messages, initMsg],
                    });
                  } catch {
                    // 状态已被其他事件改变（如 done 先到达），静默忽略
                  }
                } else {
                  const updatedSections = appendToPlanSections(
                    state.planSections,
                    chunkSection,
                    chunkData.text,
                  );
                  set({
                    accumulatedText: state.accumulatedText + chunkData.text,
                    lastSequence: newSeq,
                    planSections: updatedSections,
                  });
                }
              },

              // ---- onDone ----
              onDone: (doneData: DoneEventPayload): void => {
                const state = get();

                // 仍在 submitting：上游生成器未产出任何 chunk 即结束（超时/LLM 不可用）
                // 转为 submit_failed 让用户看到错误提示并可以重试
                if (state.sessionState === 'submitting') {
                  try {
                    const next = transitionTo(state.sessionState, 'submit_failed');
                    set({
                      sessionState: next,
                      errorCode: ConsultErrorCode.SUBMIT_SERVER_ERROR,
                    });
                  } catch {
                    // 状态已变更，不覆盖
                  }
                  return;
                }

                // 不在 streaming 状态（已完成转换或已进入其他终态）→ 忽略
                if (state.sessionState !== 'streaming') {
                  return;
                }

                // 提取 SSE done 事件元数据
                const crisisLevel = doneData?.crisis_level || 'mild';
                const referencedSliceIds: string[] = doneData?.referenced_slice_ids ?? [];
                const referencedCases: ReferencedCase[] = doneData?.referenced_cases ?? [];
                const verdict = doneData?.verdict || 'PASS';

                // 从后端 sections 数据构建结构化段落（替代前端正则解析）
                const doneSections = doneData?.sections ?? {};
                const planSections = sectionsToPlanSections(doneSections);

                // 判决是否触发工单引导
                const shouldShowTicket = verdict === 'FORCE_BLOCK' || verdict === 'APPEND_WARNING';
                const nextState = shouldShowTicket ? 'ticket_guide' : 'completed';
                const next = transitionTo(state.sessionState, nextState);

                // 更新 system_plan 消息：标记为已完成
                const updatedMessages = state.messages.map((msg) => {
                  if (msg.messageType === 'system_plan' && !msg.metadata?.isCompleted) {
                    return {
                      ...msg,
                      metadata: { ...msg.metadata, isCompleted: true },
                    };
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

                // ----- 步骤 6：归档（非阻塞）-----
                // user_id 由后端从 X-Device-Id 提取，前端传占位值即可
                const archiveData: Record<string, unknown> = {
                  request_id: state._requestId || requestId,
                  user_id: '00000000-0000-0000-0000-000000000000',
                  crisis_level: state.crisisLevel ?? 'mild',
                  behavior_description: state.behaviorDescription,
                  consultation_time: new Date().toISOString(),
                  generated_plan: state.accumulatedText,
                  source_list: referenced_slice_ids ?? [],
                  disclaimer:
                    '以上建议由 AI 生成，仅供参考，不构成医疗诊断或治疗建议。如情况紧急，请立即联系专业医疗机构。',
                  generation_time_ms: generation_time_ms ?? 0,
                  is_partial: is_partial ?? false,
                  referenced_slice_ids: referenced_slice_ids ?? [],
                  finish_reason: finish_reason ?? 'COMPLETE',
                  ttft_ms: ttft_ms ?? 0,
                  has_feedback: false,
                  token_input: token_input ?? null,
                  token_output: token_output ?? null,
                };

                consultApi.archiveConsultation(archiveData).catch(() => {
                  // 归档失败为降级场景，不阻塞用户
                });
              },

              // ---- onError ----
              onError: (errorData: { error_code: string }): void => {
                const state = get();
                const isFatal =
                  errorData.error_code === 'GENERATION_FAILED' ||
                  errorData.error_code === 'SESSION_NOT_FOUND';

                if (isFatal) {
                  if (state.lastSequence === 0) {
                    // 尚未收到任何 chunk → 视为提交失败
                    try {
                      const next = transitionTo(state.sessionState, 'submit_failed');
                      set({
                        sessionState: next,
                        errorCode: ConsultErrorCode.SUBMIT_SERVER_ERROR,
                      });
                    } catch {
                      // 静默
                    }
                  } else {
                    // 已收到 chunk → 流传输失败
                    try {
                      const next = transitionTo(state.sessionState, 'stream_failed');
                      set({
                        sessionState: next,
                        errorCode: ConsultErrorCode.SSE_CONNECTION_BROKEN,
                      });

                      // 标记未完成段落为 isPartial
                      const partialSections = get().planSections.map((sec) => {
                        if (!sec.isCompleted) {
                          return { ...sec, isPartial: true };
                        }
                        return sec;
                      });

                      // 追加不完整提示消息
                      const promptMsg = createMessageItem(
                        'system',
                        '生成中断，以下为不完整建议，可能缺失部分段落',
                        'system_prompt',
                      );

                      set({
                        planSections: partialSections,
                        messages: [...get().messages, promptMsg],
                      });
                    } catch {
                      // 静默
                    }
                  }
                } else {
                  // 非致命错误仅记录日志
                  console.debug('sse_non_fatal_error', {
                    errorCode: errorData.error_code,
                    timestamp: Date.now(),
                  });
                }
              },

              // ---- onHeartbeat ----
              onHeartbeat: (): void => {
                // 心跳事件重置无数据计时器（由 parser 内部处理）
                // 可通过设置 lastEventTime 刷新监控
              },

              // ---- onReconnect ----
              onReconnect: (attempt: number): void => {
                set({ _reconnectAttempt: attempt });
              },

              // ---- onReconnectFailed ----
              onReconnectFailed: (): void => {
                const state = get();
                try {
                  if (state.lastSequence === 0) {
                    // 尚未收到任何 chunk → 视为提交失败
                    const next = transitionTo(state.sessionState, 'submit_failed');
                    set({
                      sessionState: next,
                      errorCode: ConsultErrorCode.SUBMIT_NETWORK_ERROR,
                    });
                  } else {
                    // 已收到 chunk → 流传输失败
                    const next = transitionTo(state.sessionState, 'stream_failed');
                    set({
                      sessionState: next,
                      errorCode: ConsultErrorCode.SSE_CONNECTION_BROKEN,
                    });

                    // 标记未完成段落
                    const partialSections = get().planSections.map((sec) => {
                      if (!sec.isCompleted) {
                        return { ...sec, isPartial: true };
                      }
                      return sec;
                    });

                    // 追加不完整提示消息
                    const promptMsg = createMessageItem(
                      'system',
                      '生成中断，以下为不完整建议，可能缺失部分段落',
                      'system_prompt',
                    );

                    set({
                      planSections: partialSections,
                      messages: [...get().messages, promptMsg],
                    });
                  }
                } catch {
                  // 静默
                }
              },

              // ---- onNoDataTimeout ----
              onNoDataTimeout: (): void => {
                // 软超时：仅设置 errorCode，不改变状态，不终止连接
                set({ errorCode: ConsultErrorCode.SSE_NO_DATA_TIMEOUT });
              },
            },
          );

          // 发起 SSE 连接
          const extraHeaders: Record<string, string> = {
            'ngrok-skip-browser-warning': '1',
          };
          if (session_id) {
            extraHeaders['X-Session-Id'] = session_id;
          }

          await parser.connect(stream_url, extraHeaders);
        } catch (error: unknown) {
          // ----- 请求失败处理 -----
          const state = get();

          // 若状态已不是 submitting（可能已被其他逻辑修改），不覆盖
          if (state.sessionState !== 'submitting') {
            return;
          }

          // 分类错误类型
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
            const next = transitionTo(state.sessionState, 'submit_failed');
            set({
              sessionState: next,
              errorCode,
            });
          } catch {
            // 状态已变更，不覆盖
          }

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
        // 仅在 selecting_behavior 状态下执行
        if (sessionState !== 'selecting_behavior') {
          return;
        }
        const next = transitionTo(sessionState, 'idle');
        set({ sessionState: next });
        // 保留 behaviorTypeSelection 和 behaviorDescription（不丢失）
      },

      // ===== retrySubmit =====
      retrySubmit: async (): Promise<void> => {
        const { sessionState } = get();
        if (sessionState !== 'submit_failed') {
          return;
        }
        const next = transitionTo(sessionState, 'submitting');
        set({ sessionState: next, errorCode: undefined });
        // 重用 submitConsult 逻辑
        await get().submitConsult();
      },

      // ===== goBackToSelecting =====
      goBackToSelecting: (): void => {
        const { sessionState } = get();
        if (sessionState !== 'submit_failed' && sessionState !== 'stream_failed') {
          return;
        }
        const next = transitionTo(sessionState, 'selecting_behavior');
        set({
          sessionState: next,
          errorCode: undefined,
          // 仅清空流式相关状态，保留 behaviorTypeSelection 和 behaviorDescription
          accumulatedText: '',
          planSections: createEmptySections(),
          lastSequence: 0,
        });
      },

      // ===== retryStream =====
      retryStream: async (): Promise<void> => {
        const { sessionState } = get();
        if (sessionState !== 'stream_failed') {
          return;
        }
        const next = transitionTo(sessionState, 'submitting');
        set({
          sessionState: next,
          errorCode: undefined,
          accumulatedText: '',
          planSections: createEmptySections(),
          lastSequence: 0,
        });
        // 注意：保留现有 messages（不覆盖历史）
        await get().submitConsult();
      },

      // ===== startNewConsult =====
      startNewConsult: (): void => {
        const { sessionState } = get();
        if (sessionState !== 'completed' && sessionState !== 'ticket_guide') {
          return;
        }
        const next = transitionTo(sessionState, 'selecting_behavior');
        // 清空所有会话数据
        set({
          sessionState: next,
          behaviorTypeSelection: [],
          behaviorDescription: '',
          messages: [],
          accumulatedText: '',
          planSections: createEmptySections(),
          lastSequence: 0,
          errorCode: undefined,
          ticketGuide: { show: false, riskLevel: 'normal' },
          ticketGuideShown: false,
          crisisLevel: undefined,
          confidenceScore: undefined,
          validationVerdict: undefined,
          _requestId: '',
          _reconnectAttempt: 0,
        });
      },

      // ===== goToTicket =====
      goToTicket: (): void => {
        Taro.navigateTo({ url: '/views/tickets/pages/detail' });
      },

      // ===== addMessage =====
      addMessage: (msg: MessageItem): void => {
        set((state) => {
          const newMessages = [...state.messages, msg];
          // 消息裁剪：>= 200 条时截断前 50 条
          if (newMessages.length >= 200) {
            return { messages: newMessages.slice(50) };
          }
          return { messages: newMessages };
        });
      },
    }),
    {
      // persist 中间件配置
      name: 'consult-session',
      storage: createJSONStorage(() => taroStorageAdapter),
      // 防御：storage 中可能残留旧版完整 state（含非 idle 的 sessionState），
      // 合并时强制覆盖为 idle，确保每次重开页面都从入口开始。
      merge: (persisted, current) => ({
        ...current,
        ...(persisted as object),
        sessionState: 'idle' as const,
      }),
      // 仅持久化 messages 和输入状态
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

/**
 * 获取错误提示文案（导出到 stateMachine 的 getErrorMessage）。
 */
export { getErrorMessage, sectionsToPlanSections, createEmptySections, createMessageItem, SECTION_KEYS };
