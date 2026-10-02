/**
 * 模块: features/consult/viewModel/runStore
 * 职责: 咨询面的会话级状态（Zustand）——当前会话、技能选择、候选、连接与进度、提问草稿
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 3 节（事件到状态的映射）、
 *     第 4.2 节（状态归属三分）、第 5 节（candidate 不进消息流）
 *   - docs/design/pages/对话页.md: MUST — 提交后恢复输入区、候选轻提示
 * 边界:
 *   - 依赖: features/consult/domain（类型与纯规则）、shared/types（线格式事件）
 *   - 被依赖: viewModel 的适配器与 hook、view 的页面与 part 渲染器
 * 禁止行为:
 *   - 禁止把消息正文放进本 store（消息与运行态归 assistant-ui runtime，技术设计第 2 节）
 *   - 禁止在此发请求（副作用归用例与适配器）
 *   - 禁止把 candidate 写进消息流（技术设计第 5 节）
 */

import { create } from 'zustand';

import type { QuestionAnswer } from '../../../shared/types/consult';
import type { QuestionItem, RunEvent } from '../../../shared/types/sse';
import type { ConsultFailureView } from '../domain/errors';
import { createDraft, type QuestionBatchDraft } from '../domain/questionBatch';
import {
  candidateView,
  runFailureView,
  type CandidateView,
  type ConnectionStatus,
  type SkillSummary,
} from '../domain/types';

/** 会话级状态与操作。 */
export interface ConsultRunState {
  // === 会话级数据 ===
  /** 当前对话 id（URL 是真源，这里镜像最近一次装配值）。 */
  sessionId: string | null;
  /** 技能目录（选择器 chip 来源）。 */
  skills: SkillSummary[];
  /** 待消费的技能选择；发送被受理后清空（发送即消费）。 */
  pendingSkill: string | null;
  /** 待发送的整组回答；发送被受理后清空。 */
  pendingAnswers: QuestionAnswer[] | null;
  /** 本次运行生效的技能集合（run_started.activated_skills：历史推导 ∪ 本轮新增）。 */
  activeSkills: string[];
  /** 待确认候选（不进消息流，只供轻提示与预览面板）。 */
  candidates: CandidateView[];
  /** 提问草稿：批次 id → 草稿（未提交的旧卡要保留自己的草稿）。 */
  questionDrafts: Readonly<Record<string, QuestionBatchDraft>>;
  /** 当前等待作答的批次；非 null 时对话页收起 Composer 与 SkillPicker。 */
  activeBatchId: string | null;

  // === 运行态 ===
  connection: ConnectionStatus;
  /** 状态条文案（progress 事件；首字到达即清空）。 */
  progressText: string | null;
  /** 运行失败呈现；null = 无。 */
  failure: ConsultFailureView | null;
  /** 运行开始时刻（毫秒）；用于应急首字超时的降级提示。 */
  runStartedAt: number | null;
  /** 应急首字超过预算（10 秒）时的降级提示开关。 */
  slowRun: boolean;
  /** 用户取消过当前运行：partial text 保留并标「本次回答中断」。 */
  interrupted: boolean;

  // === 操作 ===
  bindSession(sessionId: string): void;
  setSkills(skills: SkillSummary[]): void;
  /** 选择技能（只作用于下一条消息）。 */
  selectSkill(skillId: string | null): void;
  /** 读走待用技能选择（不改变状态；发送被受理后由 clearPendingSkill 清）。 */
  peekPendingSkill(): string | null;
  clearPendingSkill(): void;
  peekPendingAnswers(): QuestionAnswer[] | null;
  setPendingAnswers(answers: QuestionAnswer[]): void;
  clearPendingAnswers(): void;
  setConnection(connection: ConnectionStatus): void;
  /** 写入失败呈现（运行失败、发送失败或连接失败共用一处错误卡）。 */
  setFailure(failure: ConsultFailureView | null): void;
  setSlowRun(slow: boolean): void;
  /** 用户取消：保留 partial text 并标注中断（不变量 1：失败不得伪装成功）。 */
  markInterrupted(): void;
  /** 事件 → 状态（技术设计第 3 节映射表的 viewModel 侧）。 */
  applyRunEvent(event: RunEvent, now?: number): void;
  /** 写入/更新一组提问草稿。 */
  setQuestionDraft(draft: QuestionBatchDraft): void;
  /** 置当前等待作答的批次；提交或移除后传 null。 */
  setActiveBatch(batchId: string | null): void;
  /** 清空会话级状态（切换会话或重新装配）。 */
  reset(sessionId?: string | null): void;
}

/** 初始数据（不含操作）。 */
const INITIAL_DATA = {
  sessionId: null,
  skills: [],
  pendingSkill: null,
  pendingAnswers: null,
  activeSkills: [],
  candidates: [],
  questionDrafts: {},
  activeBatchId: null,
  connection: 'idle',
  progressText: null,
  failure: null,
  runStartedAt: null,
  slowRun: false,
  interrupted: false,
} satisfies Omit<
  ConsultRunState,
  | 'bindSession'
  | 'setSkills'
  | 'selectSkill'
  | 'peekPendingSkill'
  | 'clearPendingSkill'
  | 'peekPendingAnswers'
  | 'setPendingAnswers'
  | 'clearPendingAnswers'
  | 'setConnection'
  | 'setFailure'
  | 'setSlowRun'
  | 'markInterrupted'
  | 'applyRunEvent'
  | 'setQuestionDraft'
  | 'setActiveBatch'
  | 'reset'
>;

/** 初始数据快照（测试与 reset 共用；读取方不得就地修改）。 */
export const CONSULT_RUN_INITIAL_STATE: Readonly<typeof INITIAL_DATA> = INITIAL_DATA;

/**
 * 创建 store（工厂形式便于测试拿到干净的实例）。
 *
 * 并发纪律：本 store 的写操作都是同步赋值，没有在途异步结果回写的路径
 * （网络调用在用例与适配器里，结果经 applyRunEvent 同步落状态），因此不需要序号守卫；
 * 唯一的并发面是提问草稿的提交闸门，它收在 useQuestionBatch 的动作函数体内。
 */
export function createConsultRunStore() {
  return create<ConsultRunState>((set, get) => ({
    ...INITIAL_DATA,

    bindSession: (sessionId) => set({ sessionId }),
    setSkills: (skills) => set({ skills }),
    selectSkill: (skillId) => set({ pendingSkill: skillId }),
    peekPendingSkill: () => get().pendingSkill,
    clearPendingSkill: () => set({ pendingSkill: null }),
    peekPendingAnswers: () => get().pendingAnswers,
    setPendingAnswers: (answers) => set({ pendingAnswers: answers }),
    clearPendingAnswers: () => set({ pendingAnswers: null }),
    setConnection: (connection) => set({ connection }),
    setFailure: (failure) => set({ failure }),
    setSlowRun: (slow) => set({ slowRun: slow }),
    markInterrupted: () => set({ interrupted: true, connection: 'idle', progressText: null, runStartedAt: null }),

    applyRunEvent: (event, now = Date.now()) => {
      switch (event.type) {
        case 'run_started':
          set({
            connection: 'streaming',
            activeSkills: [...event.activated_skills],
            progressText: null,
            failure: null,
            interrupted: false,
            slowRun: false,
            runStartedAt: now,
          });
          break;
        case 'progress':
          set({ progressText: event.message });
          break;
        case 'candidate':
          set((state) => ({ candidates: [...state.candidates, candidateView(event.candidate)] }));
          break;
        case 'text_delta':
          // 首字到达：状态条文案让位给正文（技术设计第 3 节 progress 行）。
          if (get().progressText !== null) set({ progressText: null });
          break;
        case 'question': {
          const state = get();
          if (state.questionDrafts[event.batch_id] === undefined) {
            set({
              questionDrafts: {
                ...state.questionDrafts,
                [event.batch_id]: createDraft(event.batch_id, event.items),
              },
              activeBatchId: event.batch_id,
            });
          } else {
            // 同一批次重复到达（重连重放）：保留已有草稿，不覆盖使用者已作答的内容。
            set({ activeBatchId: event.batch_id });
          }
          break;
        }
        case 'run_finished':
          set({ connection: 'idle', progressText: null, runStartedAt: null, slowRun: false });
          break;
        case 'run_failed':
          set({
            connection: 'failed',
            progressText: null,
            failure: runFailureView(event),
            runStartedAt: null,
            slowRun: false,
          });
          break;
        default:
          // reasoning_delta / tool_call_* / citation / action_card 只进消息 content（part），
          // 会话级状态无需变化；这里显式列出不改状态而不是给个兜底分支。
          break;
      }
    },

    setQuestionDraft: (draft) =>
      set((state) => ({ questionDrafts: { ...state.questionDrafts, [draft.batchId]: draft } })),
    setActiveBatch: (batchId) => set({ activeBatchId: batchId }),

    reset: (sessionId = null) => set({ ...INITIAL_DATA, sessionId }),
  }));
}

/** 界面消费的 store 单例。 */
export const useRunStore = createConsultRunStore();

/** 测试与退场清理用：把单例恢复到初始数据。 */
export function resetConsultRunStore(): void {
  useRunStore.setState({ ...INITIAL_DATA });
}

/** 读一组提问草稿；不存在返回 null（调用方按「不是本批次的卡」处理）。 */
export function questionDraftOf(
  drafts: Readonly<Record<string, QuestionBatchDraft>>,
  batchId: string,
): QuestionBatchDraft | null {
  return drafts[batchId] ?? null;
}

/** 供 part 渲染器使用：按批次取题面（草稿缺失时用事件里的 items 建只读记录）。 */
export function questionItemsOf(
  drafts: Readonly<Record<string, QuestionBatchDraft>>,
  batchId: string,
  fallback: readonly QuestionItem[],
): readonly QuestionItem[] {
  return drafts[batchId]?.items ?? fallback;
}
