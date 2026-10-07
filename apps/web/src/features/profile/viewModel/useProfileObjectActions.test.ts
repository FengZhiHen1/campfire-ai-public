/**
 * 模块: features/profile/viewModel/useProfileObjectActions.test
 * 职责: 对象写操作的并发闸门回归守卫——在途时重复提交只发一次请求，提前返回不占住闸门（FE-12）
 * 数据来源:
 *   - docs/design/pages/档案页.md: MUST — 「新建对象」「对象操作」两节与状态覆盖表的归档行
 *   - features/profile/viewModel/useProfileObjectActions: MUST — 被测动作函数
 * 边界:
 *   - 依赖: features/profile/test/fixtures、src/test/deferred
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言守卫等于授权
 *   - 禁止用页面层点击代替动作函数调用（单内提交按钮带 disabled，页面层用例看不出闸门缺失）
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import { deferred } from '../../../test/deferred';
import { profilePort, supportObject } from '../test/fixtures';
import type { ProfilePort } from '../application/ports';
import { useProfileObjectActions } from './useProfileObjectActions';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useProfileObjectActions · 并发闸门（FE-12）', () => {
  it('P1 新建在途时再次提交 → 端口只被调用一次', async () => {
    const gate = deferred<Awaited<ReturnType<ProfilePort['createObject']>>>();
    const p = profilePort({ createObject: vi.fn(() => gate.promise) });
    const { result } = renderHook(() => useProfileObjectActions(p, supportObject('o1', '小宝'), async () => undefined));

    act(() => {
      result.current.openCreate();
      result.current.updateName('小宝');
    });
    await act(async () => {
      void result.current.submit();
    });
    await act(async () => {
      void result.current.submit();
    });

    expect(p.createObject).toHaveBeenCalledTimes(1);
  });

  it('P1 提前返回的路径（没有当前对象的恢复）不占住闸门 → 之后的提交照常发起', async () => {
    // selected 为 null 时 rename/archive/restore 在 try 里提前返回；闸门若只清在成功分支上，
    // 这一次空提交会把后续所有对象操作永久锁死。
    const p = profilePort();
    const { result } = renderHook(() => useProfileObjectActions(p, null, async () => undefined));

    act(() => {
      result.current.openRestore();
    });
    await act(async () => {
      await result.current.submit();
    });
    expect(p.patchObject).not.toHaveBeenCalled();

    act(() => {
      result.current.openCreate();
      result.current.updateName('小宝');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(p.createObject).toHaveBeenCalledTimes(1);
  });
});
