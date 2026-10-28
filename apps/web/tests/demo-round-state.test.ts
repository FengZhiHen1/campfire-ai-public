/**
 * 模块: tests/demo-round-state
 * 职责: 给「这一轮跑完没有」的判据配能失败的用例——演示装置靠它决定什么时候截图
 * 数据来源:
 *   - apps/web/demo/support/roundState.ts: 被测实现
 *   - apps/web/src/features/consult/view/ChatWorkspace.tsx: 停止键与发送键的真实语义（注释里逐条对应）
 * 边界:
 *   - 依赖: vitest、demo/support/roundState（纯函数，不需要浏览器）
 *   - 被依赖: 无（`pnpm test` 收集）
 * 禁止行为:
 *   - 禁止只测「happy path」：这份判据的价值全在分支顺序上（错误态优先、待作答是终态）
 *   - 禁止用真实 DOM 替身凑测试：判据是纯函数，DOM 采样留在 stack.ts
 */

import { describe, expect, it } from 'vitest';

import { classifyRound, SettleTracker, type RoundSignals } from '../demo/support/roundState';

/** 一次「看起来像刚跑完一轮」的采样；各用例只覆盖它的一两个字段。 */
function signals(overrides: Partial<RoundSignals> = {}): RoundSignals {
  return {
    errorText: null,
    docCount: 1,
    baselineDocs: 0,
    runningTools: 0,
    pendingQuestion: false,
    stopVisible: false,
    sendDisabled: false,
    lastDocLength: 120,
    ...overrides,
  };
}

describe('classifyRound — 单次采样的判定', () => {
  it('错误卡片最先：有它就报错，不会被「正文还没出现」掩盖', () => {
    // 这条是「不白等 240 秒」的唯一保证：没有新增正文时若先判 waiting，错误卡片就永远看不到。
    expect(classifyRound(signals({ errorText: '模型暂时不可用', docCount: 0 }))).toBe('error');
  });

  it('本轮还没有新正文 ⇒ waiting（「长度不变」此时毫无意义）', () => {
    expect(classifyRound(signals({ docCount: 0, baselineDocs: 0 }))).toBe('waiting');
    expect(classifyRound(signals({ docCount: 1, baselineDocs: 1 }))).toBe('waiting');
  });

  it('还有工具行在跑 ⇒ waiting', () => {
    expect(classifyRound(signals({ runningTools: 1 }))).toBe('waiting');
  });

  it('待作答的提问卡是终态，不是「还在跑」', () => {
    // 待作答时输入区整体收起（发送键必然禁用）；若先判 sendDisabled 就会一路等到超时。
    expect(classifyRound(signals({ pendingQuestion: true, sendDisabled: true }))).toBe('question');
  });

  it('停止键可见 ⇒ waiting（它只在 thread.isRunning 时渲染）', () => {
    expect(classifyRound(signals({ stopVisible: true }))).toBe('waiting');
  });

  it('发送键禁用 ⇒ waiting（草稿为空也会禁用，所以它只是必要条件）', () => {
    expect(classifyRound(signals({ sendDisabled: true }))).toBe('waiting');
  });

  it('四条清道夫都干净 ⇒ stable（待稳定闸门确认）', () => {
    expect(classifyRound(signals())).toBe('stable');
  });
});

describe('SettleTracker — 稳定闸门', () => {
  it('长度连续 requiredSamples 次不变才算 done，中间只算 waiting', () => {
    const tracker = new SettleTracker(3);
    expect(tracker.next(signals())).toEqual({ kind: 'waiting' });
    expect(tracker.next(signals())).toEqual({ kind: 'waiting' });
    expect(tracker.next(signals())).toEqual({ kind: 'done' });
  });

  it('正文还在增长就把计数打回原点（模型两次工具调用之间的静默不能算结束）', () => {
    const tracker = new SettleTracker(2);
    expect(tracker.next(signals({ lastDocLength: 100 }))).toEqual({ kind: 'waiting' });
    expect(tracker.next(signals({ lastDocLength: 100 }))).toEqual({ kind: 'done' });

    const growing = new SettleTracker(2);
    expect(growing.next(signals({ lastDocLength: 100 }))).toEqual({ kind: 'waiting' });
    expect(growing.next(signals({ lastDocLength: 400 }))).toEqual({ kind: 'waiting' });
    expect(growing.next(signals({ lastDocLength: 400 }))).toEqual({ kind: 'done' });
  });

  it('中途出现「仍在跑」的证据后，稳定计数必须重新开始', () => {
    const tracker = new SettleTracker(2);
    expect(tracker.next(signals({ lastDocLength: 100 }))).toEqual({ kind: 'waiting' });
    // 第二轮工具调用开始了：即使正文长度没变，也不能把之前那次采样算进稳定计数。
    expect(tracker.next(signals({ lastDocLength: 100, runningTools: 1 }))).toEqual({ kind: 'waiting' });
    expect(tracker.next(signals({ lastDocLength: 100 }))).toEqual({ kind: 'waiting' });
    expect(tracker.next(signals({ lastDocLength: 100 }))).toEqual({ kind: 'done' });
  });

  it('待作答直接判终态，不消耗稳定计数', () => {
    const tracker = new SettleTracker(4);
    expect(tracker.next(signals({ pendingQuestion: true }))).toEqual({ kind: 'question' });
  });

  it('错误态立即带出文案（调用方据此抛错，文案要能看懂）', () => {
    const tracker = new SettleTracker(4);
    expect(tracker.next(signals({ errorText: '模型暂时不可用' }))).toEqual({
      kind: 'error',
      message: '模型暂时不可用',
    });
  });

  it('错误文案读不到时给显式占位，而不是空字符串', () => {
    const tracker = new SettleTracker(1);
    expect(tracker.next(signals({ errorText: '（读不到错误卡片文案）' }))).toEqual({
      kind: 'error',
      message: '（读不到错误卡片文案）',
    });
  });
});
