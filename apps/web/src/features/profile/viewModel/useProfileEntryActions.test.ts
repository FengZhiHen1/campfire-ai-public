/**
 * 模块: features/profile/viewModel/useProfileEntryActions.test
 * 职责: 条目写操作的并发闸门回归守卫——在途时重复触发不发起第二次请求（FE-12）
 * 数据来源:
 *   - docs/design/pages/档案页.md: MUST — 状态覆盖表（提交中与提交失败的呈现）
 *   - features/profile/viewModel/useProfileEntryActions: MUST — 被测动作函数
 * 边界:
 *   - 依赖: features/profile/test/fixtures、src/test/deferred
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言守卫等于授权
 *   - 禁止用页面层点击代替动作函数调用（见下）
 *
 * 为什么在 hook 层而不是页面层：条目表单的提交按钮带 `disabled={submitting}`，jsdom 下
 * 第二次 fireEvent.click 落在已禁用按钮上不会触发 handler——页面层用例在修复前后同样通过，
 * 它会掩盖「闸门不在函数体内」这件事。这里直接调用动作函数，模拟绕过 UI 的触发路径
 * （程序化调用、将来的键盘入口、以及同一个动作函数的其它入口），这才是 FE-12 判据所在。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import { deferred } from '../../../test/deferred';
import { profileItem, profilePort } from '../test/fixtures';
import type { ProfilePort } from '../application/ports';
import { useProfileEntryActions } from './useProfileEntryActions';

/** 挂起不决的确认端点：用来把「请求在途」这个状态固定住。 */
function pendingConfirm(): ProfilePort['confirmItem'] {
  const gate = deferred<Awaited<ReturnType<ProfilePort['confirmItem']>>>();
  return vi.fn(() => gate.promise);
}

/** 挂起不决的纠正端点。 */
function pendingCorrect(): ProfilePort['correctItem'] {
  const gate = deferred<Awaited<ReturnType<ProfilePort['correctItem']>>>();
  return vi.fn(() => gate.promise);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useProfileEntryActions · 并发闸门（FE-12）', () => {
  it('P1 确认候选在途时再次触发 → 端口只被调用一次', async () => {
    const p = profilePort({ confirmItem: pendingConfirm() });
    const { result } = renderHook(() => useProfileEntryActions(p, 'o1', async () => undefined));

    await act(async () => {
      void result.current.confirmCandidate('c1');
    });
    // 第二次触发：闸门必须在函数体内拒绝它，而不是靠按钮 disabled。
    await act(async () => {
      void result.current.confirmCandidate('c1');
    });

    expect(p.confirmItem).toHaveBeenCalledTimes(1);
    expect(result.current.busyItemId).toBe('c1');
  });

  it('P1 纠正提交在途时再次触发 → 端口只被调用一次', async () => {
    const p = profilePort({ correctItem: pendingCorrect() });
    const { result } = renderHook(() => useProfileEntryActions(p, 'o1', async () => undefined));

    act(() => {
      result.current.openCorrect(profileItem());
      // 与原描述相同会被用例拦在提交前（不发请求），这里改成真的不同。
      result.current.updateCorrectDraft({ description: '改用图片卡 + 手势' });
    });
    await act(async () => {
      void result.current.submitCorrect();
    });
    await act(async () => {
      void result.current.submitCorrect();
    });

    expect(p.correctItem).toHaveBeenCalledTimes(1);
  });

  it('P1 纠正在途时补充提交被拒；纠正结束后补充照常发起', async () => {
    // 两条写操作并发会各自触发一次内容区重载，后到的重载会盖掉先到的结果。
    const gate = deferred<Awaited<ReturnType<ProfilePort['correctItem']>>>();
    const p = profilePort({ correctItem: vi.fn(() => gate.promise) });
    const { result } = renderHook(() => useProfileEntryActions(p, 'o1', async () => undefined));

    act(() => {
      result.current.openCorrect(profileItem());
      result.current.updateCorrectDraft({ description: '改用图片卡 + 手势' });
      result.current.openAdd();
      result.current.updateAddDraft({ topic: '入睡', description: '入睡前要开小灯' });
    });
    await act(async () => {
      void result.current.submitCorrect();
    });
    await act(async () => {
      void result.current.submitAdd();
    });
    expect(p.correctItem).toHaveBeenCalledTimes(1);
    expect(p.addItem).not.toHaveBeenCalled();

    // 闸门随纠正结束释放：这一次补充必须真的发出去——否则上面那条「未调用」可能只是空转发
    // （空草稿同样会被用例拦在提交前）。
    await act(async () => {
      gate.resolve({ item_id: 'new1', supersedes: 'i1' });
    });
    await act(async () => {
      void result.current.submitAdd();
    });
    expect(p.addItem).toHaveBeenCalledTimes(1);
  });

  it('P1 失败后闸门释放：再次提交会发起第二次请求（不是永久锁死）', async () => {
    let attempt = 0;
    const confirmItem = vi.fn(async (itemId: string) => {
      attempt += 1;
      if (attempt === 1) throw { status: 500 };
      return { item_id: itemId, confirmation: 'confirmed' as const };
    });
    const p = profilePort({ confirmItem });
    const { result } = renderHook(() => useProfileEntryActions(p, 'o1', async () => undefined));

    await act(async () => {
      await result.current.confirmCandidate('c1');
    });
    expect(result.current.rowFailure).not.toBeNull();

    await act(async () => {
      await result.current.confirmCandidate('c1');
    });

    expect(confirmItem).toHaveBeenCalledTimes(2);
    expect(result.current.rowFailure).toBeNull();
  });
});
