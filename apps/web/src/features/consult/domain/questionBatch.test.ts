/**
 * 模块: features/consult/domain/questionBatch.test
 * 职责: 提问卡状态机的回归守卫——三通道、逐题保留、整组一次提交与拒绝路径
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 6.1 节、第 8 节验证清单（未完成禁提交、整组一次、草稿保留）
 * 边界:
 *   - 依赖: domain/questionBatch、test/fixtures
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止只测顺利路径：拒绝路径（未完成提交、重复提交、不可跳过题跳过）必须有用例
 */

import { describe, expect, it } from 'vitest';

import {
  answerFor,
  answersDisplayText,
  createDraft,
  goTo,
  handledCount,
  isComplete,
  markSubmitted,
  QuestionBatchError,
  recordLines,
  selectOption,
  setFreeText,
  skipItem,
  toAnswers,
} from './questionBatch';
import { QUESTION_ITEMS } from '../test/fixtures';

describe('QuestionBatchDraft — 三通道与整组提交', () => {
  it('新建草稿全部未作答，停在第一题', () => {
    const draft = createDraft('b1', QUESTION_ITEMS);
    expect(draft.index).toBe(0);
    expect(isComplete(draft)).toBe(false);
    expect(handledCount(draft)).toBe(0);
    expect(answerFor(draft, 'q1')).toEqual({ kind: 'unanswered' });
  });

  it('选项通道暂存 label，切换题目后回来仍保留（逐题保留）', () => {
    let draft = createDraft('b1', QUESTION_ITEMS);
    draft = selectOption(draft, 'q1', '可以');
    draft = goTo(draft, 1);
    draft = selectOption(draft, 'q2', '是');
    draft = goTo(draft, 0);
    expect(answerFor(draft, 'q1')).toEqual({ kind: 'option', label: '可以' });
    expect(handledCount(draft)).toBe(2);
  });

  it('自由文本通道：空白文本回到未作答（不把空串当已回答）', () => {
    let draft = createDraft('b1', QUESTION_ITEMS);
    draft = setFreeText(draft, 'q1', '只能用点头表示');
    expect(answerFor(draft, 'q1')).toEqual({ kind: 'free', text: '只能用点头表示' });
    draft = setFreeText(draft, 'q1', '   ');
    expect(answerFor(draft, 'q1')).toEqual({ kind: 'unanswered' });
  });

  it('跳过通道：只影响当前题，且不可跳过的题保持原状', () => {
    let draft = createDraft('b1', QUESTION_ITEMS);
    draft = skipItem(draft, 'q1');
    expect(answerFor(draft, 'q1')).toEqual({ kind: 'skip' });
    // q2 的 allow_skip 为 false：调用跳过不改变草稿（不是静默当成跳过）。
    const before = draft;
    expect(skipItem(before, 'q2')).toEqual(before);
    expect(isComplete(before)).toBe(false);
  });

  it('整组提交的载荷：选项带 value、跳过带 skipped 且不带 value', () => {
    let draft = createDraft('b1', QUESTION_ITEMS);
    draft = selectOption(draft, 'q1', '不能');
    draft = skipItem(draft, 'q2');

    // q2 不可跳过，因此这里仍未完成——这正是拒绝路径的用例。
    expect(() => toAnswers(draft)).toThrow(QuestionBatchError);

    draft = selectOption(draft, 'q2', '不确定');
    expect(toAnswers(draft)).toEqual([
      { id: 'q1', value: '不能' },
      { id: 'q2', value: '不确定' },
    ]);
  });

  it('未处理完禁提交；提交后只读且不能重复提交', () => {
    let draft = createDraft('b1', QUESTION_ITEMS);
    expect(isComplete(draft)).toBe(false);
    expect(() => markSubmitted(draft)).toThrow(QuestionBatchError);

    draft = skipItem(draft, 'q1');
    draft = setFreeText(draft, 'q2', '可能吧');
    expect(isComplete(draft)).toBe(true);

    const submitted = markSubmitted(draft);
    expect(submitted.submitted).toBe(true);
    expect(() => toAnswers(submitted)).toThrow(QuestionBatchError);
    expect(() => selectOption(submitted, 'q1', '可以')).toThrow(QuestionBatchError);
  });

  it('记录行与回答文本：跳过写「（跳过）」而不是空值', () => {
    let draft = createDraft('b1', QUESTION_ITEMS);
    draft = skipItem(draft, 'q1');
    draft = selectOption(draft, 'q2', '不确定');

    expect(recordLines(draft)).toEqual([
      { prompt: QUESTION_ITEMS[0]?.prompt ?? '', answer: '（跳过）', skipped: true },
      { prompt: QUESTION_ITEMS[1]?.prompt ?? '', answer: '不确定', skipped: false },
    ]);
    expect(answersDisplayText(draft)).toContain('1. 现在还能用口语沟通吗？\n回答：（跳过）');
  });

  it('题号越界时取边界（UI 的上一题/下一题不会把题号打飞）', () => {
    const draft = createDraft('b1', QUESTION_ITEMS);
    expect(goTo(draft, -5).index).toBe(0);
    expect(goTo(draft, 99).index).toBe(QUESTION_ITEMS.length - 1);
  });

  it('未知题 id 抛出而不是静默当成未作答', () => {
    const draft = createDraft('b1', QUESTION_ITEMS);
    expect(() => answerFor(draft, '不存在')).toThrow(QuestionBatchError);
  });
});
