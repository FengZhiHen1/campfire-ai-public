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

import type { QuestionItem, RunEvent } from '../../../shared/types/sse';
import type { ConsultFailureView } from '../domain/errors';
import { createDraft, type AnswerSubmission, type QuestionBatchDraft } from '../domain/questionBatch';
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
  /** 待发送的整组回答（answers 与产出它那一组的 batchId 绑在同一个对象上）；发送被受理后清空。 */
  pendingSubmission: AnswerSubmission | null;
  /**
   * 待认领的「已在服务端启动、等待订阅」的运行（应急入口交接）。带会话 id 以免串到别的会话。
   *
   * 为什么与 pendingSkill 同一处存放：交接必须跨越 navigate。放在导航 state 里会被
   * 对话页的首次装配消费掉（`state: null` 的 replace），而 StrictMode 下 effect 会跑两遍、
   * 组件重挂载时 ref 也会重置——单例 store 是唯一不会被任一次装配吃掉的落点。
   */
  pendingAttachedRun: { sessionId: string; runId: string } | null;
  /**
   * 本次交接是否已经起过「认领运行」（防 StrictMode 下 effect 跑两遍重复 startRun）。
   * 放在 store 而不是组件 ref：单例跨两次 effect 存活，也正是因此不能用 ref 之外的猜测代替。
   */
  attachStarted: boolean;
  /** 待消费的认领意图：由 beginAttachRun 置位，由 adapter 取走即消费。 */
  attachIntent: boolean;
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
  peekPendingSubmission(): AnswerSubmission | null;
  setPendingSubmission(submission: AnswerSubmission): void;
  clearPendingSubmission(): void;
  /** 写入待认领运行（应急表单页在 navigate 前调用）。 */
  setPendingAttachedRun(sessionId: string, runId: string): void;
  /**
   * 只读探查待认领运行：**仅当会话匹配**时返回 run_id。
   *
   * 为什么不在这里消费：adapter 认领与「装配时决定要不要 startRun」是两件事，
   * 任一处提前清掉都会让另一处看不到交接（StrictMode 下 effect 跑两遍，第一次清掉就丢了）。
   * 清理点只有一个——运行到终态时由 adapter 调 clearPendingAttachedRun。
   */
  peekAttachedRun(sessionId: string): string | null;
  /**
   * 认领「要为自己起一轮运行」的资格：**首次调用返回 true 并置认领意图**，之后返回 false。
   *
   * 为什么把幂等收在 store：StrictMode 下 effect 会跑两遍（同一实例、无真实卸载），
   * 用组件 ref 当闸门会被 lint 判为「渲染期读 ref」，用猜测（有没有新输入）会误判
   * ——应急会话历史里的最后一条使用者消息就是那份八项采集。单例里的布尔量是唯一不猜的做法。
   */
  beginAttachRun(sessionId: string): boolean;
  /**
   * 归还起运行资格（装配卸载时调用）。
   *
   * 为什么必须归还：StrictMode 的「setup → cleanup → setup」会在 cleanup 时**取消**刚起的运行，
   * 若资格不归还，第二次装配就被自己的闸门挡住——现象是「订阅请求发过一次但立刻被取消，
   * 页面此后什么都不显示」。这一条是从浏览器控制台的诊断里读出来的，不是推断。
   */
  releaseAttachRun(): void;
  /** 取走认领意图（取走即消费）；没有交接或没置位时返回 false。 */
  consumeAttachIntent(): boolean;
  /** 认领的运行已到终态（或已被新的发送取代）：清掉交接。 */
  clearPendingAttachedRun(): void;
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
  pendingSubmission: null,
  pendingAttachedRun: null,
  attachStarted: false,
  attachIntent: false,
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
  | 'peekPendingSubmission'
  | 'setPendingSubmission'
  | 'clearPendingSubmission'
  | 'setPendingAttachedRun'
  | 'peekAttachedRun'
  | 'beginAttachRun'
  | 'releaseAttachRun'
  | 'consumeAttachIntent'
  | 'clearPendingAttachedRun'
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
    peekPendingSubmission: () => get().pendingSubmission,
    setPendingSubmission: (submission) => set({ pendingSubmission: submission }),
    clearPendingSubmission: () => set({ pendingSubmission: null }),
    setPendingAttachedRun: (sessionId, runId) =>
      set({ pendingAttachedRun: { sessionId, runId }, attachStarted: false, attachIntent: false }),
    peekAttachedRun: (sessionId) => {
      const pending = get().pendingAttachedRun;
      return pending !== null && pending.sessionId === sessionId ? pending.runId : null;
    },
    beginAttachRun: (sessionId) => {
      const pending = get().pendingAttachedRun;
      if (pending === null || pending.sessionId !== sessionId || get().attachStarted) return false;
      set({ attachStarted: true, attachIntent: true });
      return true;
    },
    consumeAttachIntent: () => {
      if (!get().attachIntent) return false;
      set({ attachIntent: false });
      return true;
    },
    releaseAttachRun: () => set({ attachStarted: false }),
    clearPendingAttachedRun: () => set({ pendingAttachedRun: null, attachStarted: false, attachIntent: false }),
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

    reset: (sessionId = null) =>
      set((state) => {
        // 交接属于**某个会话**：水合自己那次会话时不得清它——它就是为这次装配准备的，
        // 而对话页的水合（useConsultSession）会在挂载时先 reset 一次，清掉就等于把
        // 「拿 run_id 跳过来订阅」这件事本身抹了（EMG-01 修复的第一版正是这样失效的）。
        // 换会话则必须清：否则会把 A 会话的运行接到 B 会话页上。
        const pending = state.pendingAttachedRun;
        const keep = pending !== null && sessionId !== null && pending.sessionId === sessionId ? pending : null;
        return { ...INITIAL_DATA, sessionId, pendingAttachedRun: keep };
      }),
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
