/**
 * 模块: features/consult/viewModel/useQuestionBatch
 * 职责: 提问卡的控制器——逐题草稿读写、切换、跳过与整组一次提交的闸门
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 6.1 节（三通道、逐题保留、整组提交、已提交只读）
 *   - docs/design/pages/对话页.md: MUST — 契约修订 3（未完成禁提交、草稿保留、提交后静态记录）
 * 边界:
 *   - 依赖: domain/questionBatch（纯状态机）、viewModel/runStore（草稿与整组回答）
 *   - 被依赖: view 的 QuestionCard
 * 禁止行为:
 *   - 禁止逐题发送消息（整组一次提交，对话页设计契约修订 3）
 *   - 禁止未处理完就提交（闸门在动作函数体内，不依赖按钮 disabled，FE-12）
 *   - 禁止提交后允许再改（已提交态只读）
 */

import { useRef } from 'react';

import type { QuestionItem } from '../../../shared/types/sse';
import {
  answersDisplayText,
  createDraft,
  isComplete,
  markSubmitted,
  nextItem,
  previousItem,
  recordLines,
  selectOption,
  setFreeText,
  skipItem,
  toSubmission,
  handledCount,
  type AnswerDraft,
  type QuestionBatchDraft,
} from '../domain/questionBatch';
import { useRunStore } from './runStore';

/** 已提交/历史记录的展示行：answer 为 null 表示「答案不在这张卡里」（历史水合）。 */
export interface QuestionRecordRow {
  prompt: string;
  answer: string | null;
  skipped: boolean;
}

/** 提问卡的视图契约（View 只依赖这些字段与操作）。 */
export interface QuestionBatchController {
  /**
   * 有效呈现模式（已把服务端的 `answered` 判定折算进去）：
   * - `live` = 可作答（运行中刚发出的提问，或历史里未被作答的提问）；
   * - `record` = 只读记录（已作答，或无法判定 ⇒ fail-closed）。
   */
  mode: 'live' | 'record';
  items: readonly QuestionItem[];
  /** 当前题号（0 起）。 */
  index: number;
  /** 已处理题数（作答或显式跳过）。 */
  handled: number;
  total: number;
  /** 整组是否已处理完（决定提交按钮可用）。 */
  complete: boolean;
  /** 是否已提交（只读态）。 */
  submitted: boolean;
  isFirst: boolean;
  isLast: boolean;
  /** 当前题的草稿。 */
  answered: AnswerDraft;
  /** 静态记录行（已提交态或历史记录）。 */
  records: readonly QuestionRecordRow[];
  select(label: string): void;
  setFreeText(text: string): void;
  skip(): void;
  previous(): void;
  next(): void;
  /** 整组提交；未处理完或已提交时是空操作（闸门在函数体内）。 */
  submit(): void;
}

/** 未作答时的稳定占位（避免每次渲染新建对象导致引用变化）。 */
const UNANSWERED: AnswerDraft = { kind: 'unanswered' };

/**
 * 提问卡控制器。
 *
 * @param options.batchId 批次 id（草稿键）
 * @param options.items 题面（来自 question 事件或历史 part）
 * @param options.mode 呈现来源：`live` = 运行中刚发出；`record` = 历史水合
 * @param options.answered 服务端对历史提问的三态判定（仅 `mode === 'record'` 时有意义）：
 *   `true` = 已作答 ⇒ 只读；`false` = 未作答 ⇒ 可作答（刷新后仍能补答）；`null` = 无法判定
 *   ⇒ 只读（fail-closed）。缺省 `undefined` 与 `null` 同处置——「没拿到判定」不是
 *   「未作答」，猜错方向的代价是使用者对同一组题作答两次。
 * @param options.onSubmit 整组提交后追加使用者消息（由工作面注入）
 */
export function useQuestionBatch(options: {
  batchId: string;
  items: readonly QuestionItem[];
  mode: 'live' | 'record';
  answered?: boolean | null;
  /**
   * 整组提交后追加使用者消息（由工作面注入）。
   * @returns false = 没有被受理（如另一轮运行还在跑）；卡片须保持可作答并撤回提交件
   */
  onSubmit?: (displayText: string) => boolean | void;
}): QuestionBatchController {
  // 选项名与「当前题的草稿」都叫 answered，这里把服务端判定改名为 serverVerdict，
  // 免去两处同名（同名会让下面的 `const answered = draft.answers[...]` 直接编译失败，
  // 但即使编译器不报，读代码的人也无法分辨哪一个是「服务端说的」）。
  const { batchId, items, mode, answered: serverVerdict, onSubmit } = options;
  const stored = useRunStore((state) => state.questionDrafts[batchId]);
  const setQuestionDraft = useRunStore((state) => state.setQuestionDraft);
  const setActiveBatch = useRunStore((state) => state.setActiveBatch);
  const setPendingSubmission = useRunStore((state) => state.setPendingSubmission);
  const clearPendingSubmission = useRunStore((state) => state.clearPendingSubmission);
  const submitting = useRef(false);

  /**
   * ★ 可作答的唯一判据。两个来源合取：
   * - 运行中刚发出的提问（`live`）按定义是可作答的（它刚被发出，不可能已有作答）；
   * - 历史水合的提问（`record`）只有服务端明确判为未作答（`answered === false`）才可作答。
   *
   * `true` 与 `null`（以及缺省）一律只读：前者是「已经答过」，后者是「判不出来」。
   * 两者都归只读的依据是失败方向——猜成可作答会让使用者重复作答，猜成只读最多少修一点。
   */
  const answerable = mode === 'live' || serverVerdict === false;
  /** 折算后的有效模式：View 与下面各处只看它，判定只有上面一处。 */
  const effectiveMode: 'live' | 'record' = answerable ? 'live' : 'record';

  // 草稿缺失时按未作答渲染（此时不写 store；首次操作才把它写进 store）。
  const draft: QuestionBatchDraft = stored ?? createDraft(batchId, items);
  // 这些操作每次渲染重建即可：控制器对象本身就是每帧新建的，包一层 useCallback
  // 只是多一份要维护的依赖数组，不减少任何真实渲染。
  const write = (next: QuestionBatchDraft): void => {
    setQuestionDraft(next);
  };

  const select = (label: string): void => {
    write(selectOption(draft, draft.items[draft.index]?.id ?? '', label));
  };

  const setFree = (text: string): void => {
    write(setFreeText(draft, draft.items[draft.index]?.id ?? '', text));
  };

  const skip = (): void => {
    write(skipItem(draft, draft.items[draft.index]?.id ?? ''));
  };

  const previous = (): void => write(previousItem(draft));
  const next = (): void => write(nextItem(draft));

  const submit = (): void => {
    if (!answerable) return;
    if (submitting.current) return;
    if (draft.submitted) return;
    // 未完成禁提交：闸门在这里，按钮 disabled 只是展示提示。
    if (!isComplete(draft)) return;
    submitting.current = true;
    try {
      // ★ `batchId` 与 `answers` 一起从本帧的 draft 对象折出（`toSubmission`），
      // 而不是从闭包捕获的某个 `batchId` 变量或另一处 state 各取一半。
      // 理由（本包关键决策）：多组题场景下传错组的 `batch_id` 比不传更坏——它会触发服务端
      // 的排他层，把本该判 `True` 的组挡掉；而 `draft` 是「本组」的唯一事实源，绑在同一对象上
      // 让它不可能与 answers 来自不同的组。
      const submission = toSubmission(draft);
      setPendingSubmission(submission);
      // 先发后记：没被受理就回滚。先标已提交会把答案留成「已提交 + 从未发出」。
      const accepted = onSubmit?.(answersDisplayText(draft));
      if (accepted === false) {
        clearPendingSubmission();
        return;
      }
      write(markSubmitted(draft));
      setActiveBatch(null);
    } finally {
      submitting.current = false;
    }
  };

  const currentId = draft.items[draft.index]?.id ?? '';
  const answered = draft.answers[currentId] ?? UNANSWERED;
  const records: QuestionRecordRow[] =
    effectiveMode === 'record'
      ? // 历史水合：问题事件载荷里没有答案（答案由服务端渲染成下一条使用者消息）。
        draft.items.map((item) => ({ prompt: item.prompt, answer: null, skipped: false }))
      : recordLines(draft);

  return {
    mode: effectiveMode,
    items: draft.items,
    index: draft.index,
    handled: handledCount(draft),
    total: draft.items.length,
    complete: isComplete(draft),
    submitted: effectiveMode === 'record' || draft.submitted,
    isFirst: draft.index === 0,
    isLast: draft.index >= draft.items.length - 1,
    answered,
    records,
    select,
    setFreeText: setFree,
    skip,
    previous,
    next,
    submit,
  };
}
