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
 * 为什么这组用例在 hook 层而不是页面层：页面层的 fireEvent 每次都会自己 act 一次，
 * 两次字段写入之间必然插入一次渲染，闭包旧值问题被抹平；而真实浏览器的自动填充
 * 在同一个任务里写账号名与密码，React 的事件 flush 落在微任务，两次 onChange 共用
 * 同一份渲染闭包。这里用一次 act 把两次调用压进同一批次，复现浏览器的事件时序。
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
