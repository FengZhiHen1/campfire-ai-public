/**
 * 模块: features/consult/viewModel/useConsultRuntime.test
 * 职责: 发送闸门与「append 同步抛错」的回归守卫（连接态不被乐观写入卡住）
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 3 节（run_started 前后的输入区状态）
 *   - apps/web/src/features/consult/viewModel/useConsultRuntime.ts: MUST — 被测的闸门与回滚
 * 边界:
 *   - 依赖: viewModel/useConsultRuntime、test/consultPortStub、runStore
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止只断言返回值：判据是连接态真的回到 idle、请求真的一条都没发
 */

import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useConsultRuntime } from './useConsultRuntime';
import { resetConsultRunStore, useRunStore } from './runStore';
import { createConsultPortStub } from '../test/consultPortStub';

beforeEach(() => {
  resetConsultRunStore();
});

/** 装配工作面，并把 append 换成一个同步抛错的实现。 */
function renderWithThrowingAppend(method: 'send' | 'sendAnswers') {
  const port = createConsultPortStub();
  const { result } = renderHook(() =>
    useConsultRuntime({ sessionId: 's1', initialMessages: [], consult: port }),
  );
  const thread = result.current.runtime.thread;
  const append = vi.spyOn(thread as never, 'append' as never).mockImplementation((() => {
    throw new Error('This is the empty thread');
  }) as never);

  let accepted = true;
  act(() => {
    accepted = method === 'send' ? result.current.send('他很紧张') : result.current.sendAnswers('1. 可以');
  });
  return { accepted, append, port };
}

describe('useConsultRuntime — 发送没起成时连接态归位', () => {
  /**
   * 2026-10-29 审查：`send` 先乐观写 'subscribing' 再 append；append 同步抛错时旧实现只放开
   * 闸门，连接态永远停在 'subscribing'（思考行按「还在流式」渲染、状态条停在等待态）。
   */
  it('send：append 同步抛错 ⇒ 返回 false、连接态回 idle、不发请求', () => {
    const { accepted, append, port } = renderWithThrowingAppend('send');

    expect(accepted).toBe(false);
    expect(append).toHaveBeenCalledTimes(1);
    expect(useRunStore.getState().connection).toBe('idle');
    expect(port.sendCalls).toHaveLength(0);
    expect(port.streamCalls).toHaveLength(0);
  });

  it('sendAnswers：同样回 idle、不发请求（提交件由提问卡的调用方撤回）', () => {
    const { accepted, port } = renderWithThrowingAppend('sendAnswers');

    expect(accepted).toBe(false);
    expect(useRunStore.getState().connection).toBe('idle');
    expect(port.sendCalls).toHaveLength(0);
  });

  it('对照（防恒真）：append 成功时确实是 subscribing，且真的进入了发送', () => {
    const port = createConsultPortStub();
    const { result } = renderHook(() =>
      useConsultRuntime({ sessionId: 's1', initialMessages: [], consult: port }),
    );
    const append = vi
      .spyOn(result.current.runtime.thread as never, 'append' as never)
      .mockImplementation((() => undefined) as never);

    let accepted = false;
    act(() => {
      accepted = result.current.send('他很紧张');
    });

    expect(accepted).toBe(true);
    expect(append).toHaveBeenCalledTimes(1);
    expect(useRunStore.getState().connection).toBe('subscribing');
  });
});
