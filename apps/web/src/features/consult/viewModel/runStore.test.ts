/**
 * 模块: features/consult/viewModel/runStore.test
 * 职责: 会话级状态的回归守卫——事件映射全表、技能消费、候选不进消息流、提问草稿
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 3 节映射表（12 事件）、第 5 节（candidate 不进消息流）
 * 边界:
 *   - 依赖: viewModel/runStore、test/fixtures
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止跳过「事件不改状态」的行（12 事件必须逐行有断言）
 */

import { beforeEach, describe, expect, it } from 'vitest';

import { createConsultRunStore, type ConsultRunState } from './runStore';
import {
  actionCardEvent,
  citation,
  questionEvent,
  QUESTION_ITEMS,
  runFailed,
  runFinished,
  runStarted,
  textDelta,
} from '../test/fixtures';

/** 每个用例一个干净 store（工厂形式，避免单例跨用例污染）。 */
function newStore() {
  return createConsultRunStore();
}

describe('runStore — 事件映射（技术设计第 3 节全表）', () => {
  let store: ReturnType<typeof createConsultRunStore>;

  beforeEach(() => {
    store = newStore();
  });

  it('run_started：置运行中、记录生效技能集合与开始时刻', () => {
    store.getState().applyRunEvent(runStarted(['emergency-consulting']), 1000);
    expect(store.getState().connection).toBe('streaming');
    expect(store.getState().activeSkills).toEqual(['emergency-consulting']);
    expect(store.getState().runStartedAt).toBe(1000);
    expect(store.getState().failure).toBeNull();
  });

  it('run_started：生效集合可以是多个技能（历史推导 ∪ 本轮新增）', () => {
    store.getState().applyRunEvent(runStarted(['daily-consulting', 'profile-curation']), 1000);
    expect(store.getState().activeSkills).toEqual(['daily-consulting', 'profile-curation']);
  });

  it('progress：写状态条文案；text_delta 到达即清空文案', () => {
    store.getState().applyRunEvent({ type: 'progress', message: '正在检索资料…' });
    expect(store.getState().progressText).toBe('正在检索资料…');
    store.getState().applyRunEvent(textDelta('第一句'));
    expect(store.getState().progressText).toBeNull();
  });

  it('reasoning_delta / tool_call_* / citation / action_card 只进消息内容，不改会话级状态', () => {
    const before = store.getState();
    store.getState().applyRunEvent({ type: 'reasoning_delta', delta: '思考' });
    store.getState().applyRunEvent({ type: 'tool_call_started', tool_name: 'search_knowledge', call_id: 'c1' });
    store
      .getState()
      .applyRunEvent({ type: 'tool_call_finished', tool_name: 'search_knowledge', call_id: 'c1', ok: true, error_code: null, summary: '1 条' });
    store.getState().applyRunEvent({ type: 'citation', citation: citation() });
    store.getState().applyRunEvent(actionCardEvent());

    expect(store.getState().progressText).toBe(before.progressText);
    expect(store.getState().connection).toBe(before.connection);
    expect(store.getState().candidates).toEqual(before.candidates);
  });

  it('candidate：只累加候选列表（不进消息流）', () => {
    store.getState().applyRunEvent({ type: 'candidate', candidate: { reference: '本次对话', summary: '可能更安心' } });
    expect(store.getState().candidates).toEqual([{ source: '本次对话', summary: '可能更安心' }]);
  });

  it('question：建草稿并置为当前待作答组；重复到达不覆盖已作答内容', () => {
    store.getState().applyRunEvent(questionEvent(QUESTION_ITEMS));
    expect(store.getState().activeBatchId).toBe('b1');
    const draft = store.getState().questionDrafts.b1;
    if (draft === undefined) throw new Error('question 事件应建出草稿');
    expect(draft.items).toHaveLength(2);

    store
      .getState()
      .setQuestionDraft({ ...draft, answers: { ...draft.answers, q1: { kind: 'option', label: '可以' } } });
    store.getState().applyRunEvent(questionEvent(QUESTION_ITEMS));
    expect(store.getState().questionDrafts.b1?.answers.q1).toEqual({ kind: 'option', label: '可以' });
  });

  it('run_finished：回空闲并清进度', () => {
    store.getState().applyRunEvent(runStarted());
    store.getState().applyRunEvent(runFinished());
    expect(store.getState().connection).toBe('idle');
    expect(store.getState().runStartedAt).toBeNull();
    expect(store.getState().failure).toBeNull();
  });

  it('run_failed：置失败态与错误呈现（检索类失败文案不得读成「没有资料」）', () => {
    store.getState().applyRunEvent(runFailed('injection_failed'));
    const failure = store.getState().failure as ConsultRunState['failure'];
    expect(store.getState().connection).toBe('failed');
    expect(failure?.title).toBe('检索暂时不可用');
    expect(failure?.message).not.toContain('未找到');
    expect(failure?.message).not.toContain('没有资料');
  });
});

describe('runStore — 技能消费、取消与重置', () => {
  it('技能选择：peek 不改状态，clear 才消费（发送即消费的受理点）', () => {
    const store = newStore();
    store.getState().selectSkill('emergency-consulting');
    expect(store.getState().peekPendingSkill()).toBe('emergency-consulting');
    store.getState().clearPendingSkill();
    expect(store.getState().peekPendingSkill()).toBeNull();
  });

  it('整组回答：peek / set / clear', () => {
    const store = newStore();
    expect(store.getState().peekPendingAnswers()).toBeNull();
    store.getState().setPendingAnswers([{ id: 'q1', value: '可以' }]);
    expect(store.getState().peekPendingAnswers()).toEqual([{ id: 'q1', value: '可以' }]);
    store.getState().clearPendingAnswers();
    expect(store.getState().peekPendingAnswers()).toBeNull();
  });

  it('取消：标中断并回到空闲（不显示成完整回答）', () => {
    const store = newStore();
    store.getState().applyRunEvent(runStarted());
    store.getState().markInterrupted();
    expect(store.getState().interrupted).toBe(true);
    expect(store.getState().connection).toBe('idle');
  });

  it('reset：清空会话级状态并绑定新会话', () => {
    const store = newStore();
    store.getState().applyRunEvent(runStarted());
    store.getState().applyRunEvent({ type: 'candidate', candidate: { reference: 'r', summary: 's' } });
    store.getState().reset('s2');
    expect(store.getState().sessionId).toBe('s2');
    expect(store.getState().candidates).toEqual([]);
    expect(store.getState().connection).toBe('idle');
    expect(store.getState().questionDrafts).toEqual({});
  });
});
