/**
 * 模块: features/consult/domain/questionBatch
 * 职责: 提问卡的纯状态机——逐题草稿、切换保留、显式跳过、整组一次提交的载荷
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 6.1 节（三通道、逐题保留、整组统一提交、跳过显式标记）
 *   - docs/技术设计/technical-details/通用基座.md: MUST — 第 7.2 节（batch_id/items/id/prompt/options/allow_skip）
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 4.1 节（answers 载荷形状）
 * 边界:
 *   - 依赖: shared/types/sse（QuestionItem）、shared/types/consult（QuestionAnswer）
 *   - 被依赖: viewModel 的 runStore 与 view 的 QuestionCard
 * 禁止行为:
 *   - 禁止在未处理完题目时产出提交载荷（拒绝路径必须显式抛出，CORE-02）
 *   - 禁止把「跳过」写成空值或默认值（跳过必须是服务端可判定的事实，契约第 4.1 节）
 *   - 禁止预选答案（事实类问题不预选、不推荐，对话页设计契约修订 3）
 */

import type { QuestionAnswer } from '../../../shared/types/consult';
import type { QuestionItem } from '../../../shared/types/sse';

/** 一题的作答草稿。三通道显式建模（选项 / 自由文本 / 跳过），unanswered 是第四态而非默认值。 */
export type AnswerDraft =
  | { kind: 'unanswered' }
  | { kind: 'option'; label: string }
  | { kind: 'free'; text: string }
  | { kind: 'skip' };

/** 一组题的草稿。 */
export interface QuestionBatchDraft {
  batchId: string;
  items: readonly QuestionItem[];
  /** 题 id → 草稿（题 id 批次内唯一，作为键稳定）。 */
  answers: Readonly<Record<string, AnswerDraft>>;
  /** 当前题号（0 起）。 */
  index: number;
  /** 是否已整组提交；提交后只读（静态已提交记录）。 */
  submitted: boolean;
}

/** 草稿机的显式拒绝：未处理完就提交、或题目不存在。 */
export class QuestionBatchError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'QuestionBatchError';
  }
}

/** 一组题的静态已提交记录里的一行。 */
export interface QuestionRecordLine {
  prompt: string;
  answer: string;
  skipped: boolean;
}

/** 建一组新草稿：全部未作答、停在第一题。 */
export function createDraft(batchId: string, items: readonly QuestionItem[]): QuestionBatchDraft {
  const answers: Record<string, AnswerDraft> = {};
  for (const item of items) answers[item.id] = { kind: 'unanswered' };
  return { batchId, items, answers, index: 0, submitted: false };
}

/** 取某题草稿；题不存在时抛出（调用方不得静默当成未作答）。 @throws QuestionBatchError 题 id 不在本批次内 */
export function answerFor(draft: QuestionBatchDraft, itemId: string): AnswerDraft {
  const answer = draft.answers[itemId];
  if (answer === undefined) throw new QuestionBatchError(`题目 ${itemId} 不在本批次内`);
  return answer;
}

/** 已处理的题数（作答或显式跳过）。用于题号与处理进度显示。 */
export function handledCount(draft: QuestionBatchDraft): number {
  return draft.items.filter((item) => answerFor(draft, item.id).kind !== 'unanswered').length;
}

/** 整组是否已处理完（每题都有答案或显式跳过）。 */
export function isComplete(draft: QuestionBatchDraft): boolean {
  return draft.items.every((item) => answerFor(draft, item.id).kind !== 'unanswered');
}

/** 是否处于只读态：已提交的草稿不得再改（对话页设计契约修订 3）。 */
function ensureEditable(draft: QuestionBatchDraft): void {
  if (draft.submitted) throw new QuestionBatchError('本组已提交，不能再修改');
}

/** 写入某题草稿（不可变更新）。 */
function withAnswer(
  draft: QuestionBatchDraft,
  itemId: string,
  answer: AnswerDraft,
): QuestionBatchDraft {
  ensureEditable(draft);
  answerFor(draft, itemId);
  return { ...draft, answers: { ...draft.answers, [itemId]: answer } };
}

/** 点选某一项（选项通道）。 */
export function selectOption(draft: QuestionBatchDraft, itemId: string, label: string): QuestionBatchDraft {
  return withAnswer(draft, itemId, { kind: 'option', label });
}

/**
 * 写入自由回答（自由文本通道）。
 *
 * 空文本回到未作答：把空串当成「已回答」会让「未完成禁提交」形同虚设，
 * 也会向服务端送出空答案。
 */
export function setFreeText(draft: QuestionBatchDraft, itemId: string, text: string): QuestionBatchDraft {
  const trimmed = text.trim();
  return withAnswer(draft, itemId, trimmed === '' ? { kind: 'unanswered' } : { kind: 'free', text: trimmed });
}

/** 显式跳过当前题；题面不允许跳过时保持原状（不静默当成跳过）。 @throws QuestionBatchError 题 id 不在本批次内 */
export function skipItem(draft: QuestionBatchDraft, itemId: string): QuestionBatchDraft {
  const item = draft.items.find((candidate) => candidate.id === itemId);
  if (item === undefined) throw new QuestionBatchError(`题目 ${itemId} 不在本批次内`);
  if (!item.allow_skip) return draft;
  return withAnswer(draft, itemId, { kind: 'skip' });
}

/** 切到指定题；越界取边界（不抛错——题号来自 UI 的上一题/下一题）。 */
export function goTo(draft: QuestionBatchDraft, index: number): QuestionBatchDraft {
  const last = Math.max(0, draft.items.length - 1);
  const clamped = Math.min(Math.max(0, Math.trunc(index)), last);
  return { ...draft, index: clamped };
}

/** 下一题（已是最后一题则不动）。 */
export function nextItem(draft: QuestionBatchDraft): QuestionBatchDraft {
  return goTo(draft, draft.index + 1);
}

/** 上一题（已是第一题则不动）。 */
export function previousItem(draft: QuestionBatchDraft): QuestionBatchDraft {
  return goTo(draft, draft.index - 1);
}

/**
 * 产出 answers 载荷。
 *
 * 前置: isComplete(draft) 为真
 * 后置: 逐题一条：选项/自由文本带 value，跳过带 skipped=true（不带 value）
 * 异常: QuestionBatchError（未处理完）——提交闸门在函数体内，不依赖按钮是否 disabled
 *
 * @throws QuestionBatchError 未处理完，或本组已提交
 */
export function toAnswers(draft: QuestionBatchDraft): QuestionAnswer[] {
  if (draft.submitted) throw new QuestionBatchError('本组已提交，不能重复提交');
  if (!isComplete(draft)) throw new QuestionBatchError('还有题目没有作答或跳过');
  return draft.items.map((item) => {
    const answer = answerFor(draft, item.id);
    switch (answer.kind) {
      case 'option':
        return { id: item.id, value: answer.label };
      case 'free':
        return { id: item.id, value: answer.text };
      case 'skip':
        return { id: item.id, skipped: true };
      case 'unanswered':
        // isComplete 已排除；留着分支是为了让新增状态必须被显式处理。
        throw new QuestionBatchError(`题目 ${item.id} 尚未作答`);
    }
  });
}

/** 标记整组已提交（只读）。前置: isComplete。 @throws QuestionBatchError 还有题目没有作答或跳过 */
export function markSubmitted(draft: QuestionBatchDraft): QuestionBatchDraft {
  if (!isComplete(draft)) throw new QuestionBatchError('还有题目没有作答或跳过');
  return { ...draft, submitted: true };
}

/** 静态记录行（已提交态与历史水合的呈现形态）。 */
export function recordLines(draft: QuestionBatchDraft): QuestionRecordLine[] {
  return draft.items.map((item) => {
    const answer = answerFor(draft, item.id);
    switch (answer.kind) {
      case 'option':
        return { prompt: item.prompt, answer: answer.label, skipped: false };
      case 'free':
        return { prompt: item.prompt, answer: answer.text, skipped: false };
      case 'skip':
        return { prompt: item.prompt, answer: '（跳过）', skipped: true };
      case 'unanswered':
        return { prompt: item.prompt, answer: '（未作答）', skipped: false };
    }
  });
}

/**
 * 整组回答的呈现文本（作为一条使用者消息追加进消息流）。
 *
 * 为什么不把 answers 载荷直接当消息内容：消息 content 由 assistant-ui 渲染，
 * 结构化载荷无法呈现；契约第 4.1 节也写明服务端会把 answers 渲染成一条使用者消息，
 * 前端本地呈现与它保持同形（逐题对应 + 跳过标记）。
 */
export function answersDisplayText(draft: QuestionBatchDraft): string {
  return recordLines(draft)
    .map((line, index) => `${index + 1}. ${line.prompt}\n回答：${line.answer}`)
    .join('\n\n');
}
