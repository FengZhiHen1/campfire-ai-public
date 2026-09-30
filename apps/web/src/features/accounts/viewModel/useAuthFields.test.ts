/**
 * 模块: features/accounts/viewModel/useAuthFields.test
 * 职责: 字段状态机的回归守卫——同一任务内连续写入多个字段时不互相覆盖
 * 数据来源:
 *   - docs/design/pages/登录与注册.md: MUST — 状态覆盖表（server-error 行「保留已输入内容不清空」）
 *   - docs/design/pages/登录与注册.md: MUST — 响应式与平台节（原生 autocomplete：浏览器会一次性填多个字段）
 * 边界:
 *   - 依赖: features/accounts/viewModel/useAuthFields（被测对象）
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言守卫等于授权
 *
 * 为什么这组用例在 hook 层而不是页面层：本包实测 jsdom 下每次派发原生 input 事件都会在派发内
 * 提交一次渲染（同一 act 内两次派发共触发两次渲染），页面层两次写入之间必然换到新闭包，
 * 复现不出「两次更新落在同一批次」；而该缺陷只在同一批次下显形。因此这里用一次 act 把两次
 * setField 压进同一批次，直接钉住不变量：字段更新不得依赖渲染闭包里的旧值。
 */

import { describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import { useAuthFields } from './useAuthFields';

describe('useAuthFields · 同一任务内连续写入多个字段', () => {
  it('P0 连续两次 setField 写不同字段 → 第二次不覆盖第一次', () => {
    const { result } = renderHook(() => useAuthFields('login'));

    act(() => {
      result.current.setField('account', '阿澈的妈妈');
      result.current.setField('password', 'campfire2026');
    });

    expect(result.current.values).toEqual({
      account: '阿澈的妈妈',
      password: 'campfire2026',
      inviteCode: '',
    });
  });

  it('P0 连续两次 setField 后的即时重校验读含本次写入的最新值', () => {
    const { result } = renderHook(() => useAuthFields('login'));

    // 两个字段都触碰过：两次写入各自触发即时重校验（未触碰的字段按设计不重校验，
    // 是否呈现由 View 按 touched 决定）。
    act(() => {
      result.current.blurField('account');
      result.current.blurField('password');
    });
    expect(result.current.errors).toEqual({ account: '请填写账号名', password: '请填写密码' });

    act(() => {
      result.current.setField('account', '阿澈的妈妈');
      result.current.setField('password', 'campfire2026');
    });

    // 两次写入合起来把表单填成合法：错误集合必须清空。
    // 若即时重校验读的是闭包旧值，账号名会被算成空，错误留在原地。
    expect(result.current.errors).toEqual({});
  });

  it('P0 同一任务内先写值再失焦 → 不把刚填好的字段误报成空', () => {
    const { result } = renderHook(() => useAuthFields('login'));

    act(() => {
      result.current.setField('account', '阿澈的妈妈');
      result.current.blurField('account');
    });

    // blurField 的校验读同样必须是含本次写入的最新值，否则刚填好的账号名
    // 会被判成空并显示「请填写账号名」（与 setField 同一类陈旧读）。
    expect(result.current.errors.account).toBeUndefined();
  });
});
