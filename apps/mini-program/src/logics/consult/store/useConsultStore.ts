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
 * 与 CSLT-03 Prompt 模板标题一致，若 CSLT-03 修改标题文案必须同步更新。
 */
const SECTION_TITLES: readonly string[] = [
  '即时安全干预动作',
  '情绪安抚话术',
  '后续观察指标',
  '就医判断标准',
] as const;

/**
 * 段落边界检测正则。
 * 匹配 Markdown 标题（#/##/###）后跟四段标题之一。
 * 依赖 CSLT-03 Prompt 模板的固定标题格式，同步标注。
 */
const SECTION_TITLE_REGEX: RegExp =
  /#{1,3}\s*(即时安全干预动作|情绪安抚话术|后续观察指标|就医判断标准)/g;

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
  /** 返回空闲：submit_failed | stream_failed -> idle */
  goBackToIdle: () => void;
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
  return SECTION_TITLES.map((title) => ({
    title,
    contents: [],
    isCompleted: false,
  }));
}

// ============================================================================
// parseSections —— 段落解析
// ============================================================================

/**
 * 从 accumulatedText 中解析四段式方案段落。
 * 使用正则检测标题行，将累积文本按标题切分为四段。
 *
 * @param text - 已累积的原始文本
 * @returns 更新后的 PlanSection 数组（始终返回 4 个段落）
 */
function parseSections(text: string): PlanSection[] {
  if (!text || text.trim().length === 0) {
    return createEmptySections();
  }

  // 查找所有标题匹配项
  const matches: Array<{ title: string; index: number }> = [];
  let match: RegExpExecArray | null;
  // 重置正则 lastIndex（全局匹配需手动重置）
  SECTION_TITLE_REGEX.lastIndex = 0;

  while ((match = SECTION_TITLE_REGEX.exec(text)) !== null) {
    matches.push({
      title: match[1]!,
      index: match.index,
    });
  }

  // 无任何标题匹配 → 返回空段落
  if (matches.length === 0) {
    return createEmptySections();
  }

  // 为每个已知标题构建 PlanSection
  const result: PlanSection[] = [];

  for (let i = 0; i < SECTION_TITLES.length; i++) {
    const title = SECTION_TITLES[i];
    const currentMatch = matches.find((m) => m.title === title);

    if (currentMatch) {
      // 找到此段落在文本中的结束位置（下一个标题的位置，或文本末尾）
      const currentMatchIndex = matches.indexOf(currentMatch);
      const nextMatch = currentMatchIndex + 1 < matches.length
        ? matches[currentMatchIndex + 1]
        : null;
      const endIndex = nextMatch ? nextMatch.index : text.length;

      // 提取段落文本（标题之后的内容）
      const sectionText = text.substring(currentMatch.index, endIndex);
      const lines = sectionText.split('\n');

      // 跳过标题行，提取内容行
      const contentLines: string[] = [];
      for (let j = 1; j < lines.length; j++) {
        const trimmed = lines[j].trim();
        if (trimmed.length > 0 && !SECTION_TITLE_REGEX.test(lines[j])) {
          // 移除列表标记（-、*、数字.）
          contentLines.push(trimmed.replace(/^[-*\d.]+\s*/, '').trim());
        }
      }

      // 判断段落是否已完成：有内容且（下一标题也已出现，或是最后一段，或非最后一段但有内容）
      const isCompleted = contentLines.length > 0 && (
        nextMatch !== null || i === SECTION_TITLES.length - 1
      );

      result.push({
        title,
        contents: contentLines,
        isCompleted,
      });
    } else {
      // 此标题未在文本中出现 → 空段落
      result.push({
        title,
        contents: [],
        isCompleted: false,
      });
    }
  }

  return result;
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
              onChunk: (chunkData: { text: string; sequence: number }): void => {
                const state = get();
                const newText = state.accumulatedText + chunkData.text;
                const newSeq = chunkData.sequence;

                // 首个 chunk → 触发 streaming 状态转换 + 初始化 system_plan 消息
                const isFirstChunk = state.lastSequence === 0;

                const newSections = parseSections(newText);

                if (isFirstChunk) {
                  // 状态转换：submitting -> streaming
                  const sNext = transitionTo(state.sessionState, 'streaming');
                  const initMsg = createMessageItem('system', '', 'system_plan', {
                    isOriginal: true,
                  });
                  set({
                    sessionState: sNext,
                    accumulatedText: newText,
                    lastSequence: newSeq,
                    planSections: newSections,
                    messages: [...state.messages, initMsg],
                  });
                } else {
                  // 更新累积文本和段落
                  set({
                    accumulatedText: newText,
                    lastSequence: newSeq,
                    planSections: newSections,
                  });
                }
              },

              // ---- onDone ----
              onDone: (doneData: DoneEventPayload): void => {
                const state = get();

                // 只在 streaming 状态下处理 done 事件（error 已转换的忽略）
                if (state.sessionState !== 'streaming') {
                  return;
                }

                // 提取 SSE done 事件元数据
                const crisisLevel = doneData?.crisis_level || 'mild';
                const referencedSliceIds: string[] = doneData?.referenced_slice_ids ?? [];
                const referencedCases: ReferencedCase[] = doneData?.referenced_cases ?? [];
                const verdict = doneData?.verdict || 'PASS';

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
          const extraHeaders: Record<string, string> = {};
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

      // ===== goBackToIdle =====
      goBackToIdle: (): void => {
        const { sessionState } = get();
        if (sessionState !== 'submit_failed' && sessionState !== 'stream_failed') {
          return;
        }
        const next = transitionTo(sessionState, 'idle');
        set({ sessionState: next, errorCode: undefined });
        // 从 submit_failed 回来：保留 behaviorTypeSelection 和 behaviorDescription
        // 从 stream_failed 回来：保留消息列表
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
export { getErrorMessage, parseSections, createEmptySections, createMessageItem, SECTION_TITLES };
