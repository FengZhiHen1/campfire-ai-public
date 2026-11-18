/**
 * 模块: features/consult/viewModel/useEmergencyForm.test
 * 职责: 应急表单控制器的流程控制用例——跳过推进、步骤状态、退出判定、提交中锁题
 * 数据来源:
 *   - docs/design/pages/应急表单页.md: MUST — 状态覆盖表、「功能语义审查修订」
 *     （跳过后推进下一题、已填写内容退出时确认丢弃、提交中停止改题与改答案）
 *   - docs/需求/功能需求与验收.md: MUST — RQ-EMG-01（跳过 = 未排除，不得默认为正常）
 * 边界:
 *   - 依赖: viewModel/useEmergencyForm、test/consultPortStub、react 的 act/renderHook
 *   - 被依赖: 无（回归守卫：这些流程此前散在视图里，拼法一改就会静默漂移）
 * 禁止行为:
 *   - 禁止只测「填满八题」；全跳过与部分作答是本页的主用法（RQ-EMG-01）
 */

import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { useEmergencyForm } from './useEmergencyForm';
import { createConsultPortStub } from '../test/consultPortStub';
import { resetConsultRunStore } from './runStore';

afterEach(() => {
  resetConsultRunStore();
});

/** 渲染控制器；onStarted 记录跳转。 */
function renderForm() {
  const port = createConsultPortStub();
  const started: { sessionId: string; runId: string }[] = [];
  const view = renderHook(() =>
    useEmergencyForm(port, (sessionId, runId) => {
      started.push({ sessionId, runId });
    }),
  );
  return { port, started, view };
}

describe('useEmergencyForm — 流程控制', () => {
  it('跳过当前题会同时推进到下一题（页面设计：跳过后推进下一题）', () => {
    const { view } = renderForm();
    expect(view.result.current.index).toBe(0);

    act(() => view.result.current.skip());

    expect(view.result.current.index).toBe(1);
    // 上一题已是显式跳过态，不是「未作答」。
    expect(view.result.current.steps[0]).toEqual({ key: view.result.current.steps[0]?.key, status: 'skipped' });
    expect(view.result.current.skipped).toBe(1);
  });

  it('末题跳过后停在原地（没有下一题可推进）', () => {
    const { view } = renderForm();
    for (let step = 1; step < view.result.current.total; step += 1) {
      act(() => view.result.current.next());
    }
    expect(view.result.current.isLast).toBe(true);

    act(() => view.result.current.skip());

    expect(view.result.current.index).toBe(view.result.current.total - 1);
    expect(view.result.current.currentStatus).toBe('skipped');
  });

  it('作答会从跳过态回到已作答；已作答 / 已跳过 / 未作答三态可辨', () => {
    const { view } = renderForm();
    act(() => view.result.current.skip());
    act(() => view.result.current.previous());
    expect(view.result.current.currentStatus).toBe('skipped');

    act(() => view.result.current.toggle('altered_consciousness'));
    expect(view.result.current.currentStatus).toBe('answered');
    expect(view.result.current.answered).toBe(1);
    expect(view.result.current.skipped).toBe(0);
    expect(view.result.current.handled).toBe(1);
  });

  it('未作答是 answered/skipped 的补集（默认全部未作答）', () => {
    const { view } = renderForm();
    expect(view.result.current.steps.every((step) => step.status === 'unanswered')).toBe(true);
    expect(view.result.current.handled).toBe(0);
  });

  it('没有任何输入时退出直接放行，不弹确认', () => {
    const { view } = renderForm();
    let decision: string | undefined;
    act(() => {
      decision = view.result.current.requestExit();
    });
    expect(decision).toBe('leave');
    expect(view.result.current.exitConfirmOpen).toBe(false);
  });

  it('有已填写内容时退出要求确认；取消后留在原处', () => {
    const { view } = renderForm();
    act(() => view.result.current.toggle('altered_consciousness'));

    let decision: string | undefined;
    act(() => {
      decision = view.result.current.requestExit();
    });
    expect(decision).toBe('confirm');
    expect(view.result.current.exitConfirmOpen).toBe(true);

    act(() => view.result.current.cancelExit());
    expect(view.result.current.exitConfirmOpen).toBe(false);
    // 取消不清空答案。
    expect(view.result.current.answer.selected).toContain('altered_consciousness');
  });

  it('仅跳过（未作答）也算「已填写」，退出同样要确认', () => {
    const { view } = renderForm();
    act(() => view.result.current.skip());
    let decision: string | undefined;
    act(() => {
      decision = view.result.current.requestExit();
    });
    expect(decision).toBe('confirm');
  });

  it('提交中锁定改题与改答案（载荷按下按钮时已确定）', async () => {
    const { view, port } = renderForm();
    // 让提交挂起：用一个永不 resolve 的端口替身。
    (port.emergencyStart as unknown as { mockImplementation: (fn: () => Promise<never>) => void }).mockImplementation(
      () => new Promise<never>(() => {}),
    );

    act(() => {
      void view.result.current.submit();
    });
    expect(view.result.current.submitting).toBe(true);

    const before = view.result.current.answer.selected.length;
    act(() => view.result.current.toggle('altered_consciousness'));
    act(() => view.result.current.next());
    act(() => view.result.current.skip());
    // 提交中：作答、翻题、跳过都不改变状态。
    expect(view.result.current.answer.selected.length).toBe(before);
    expect(view.result.current.index).toBe(0);
    expect(view.result.current.skipped).toBe(0);
  });
});
