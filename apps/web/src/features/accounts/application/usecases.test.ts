/**
 * 模块: src/features/accounts/usecases.test
 * 职责: 登录/注册/登出用例的前置校验与拒绝路径——不经框架、直接 new 实例测
 * 数据来源:
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 4、6 节（注册与登录、登出）
 *   - docs/code-craft react.md FE-04: MUST — 用例无状态、校验不可绕过
 * 边界:
 *   - 依赖: features/accounts/application、domain
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止把用例测试写成对端口的转调断言（要断言的是拒绝路径与校验不可绕过）
 */

import { describe, expect, it, vi } from 'vitest';

import { LogoutUseCase, SubmitLoginUseCase, SubmitRegisterUseCase } from './usecases';
import type { AuthPort } from './ports';
import { AuthError } from '../domain/authFailure';
import { ValidationError } from '../domain/formValidation';

/** 构造一个可控的认证端口替身。 */
function port(overrides: Partial<AuthPort> = {}): AuthPort {
  return {
    doesSessionExist: vi.fn(async () => false),
    signOut: vi.fn(async () => undefined),
    submitLogin: vi.fn(async () => ({ accountName: 'acct' })),
    submitRegister: vi.fn(async () => ({ accountName: 'acct' })),
    ...overrides,
  };
}

/** 取回被拒的字段错误；抛出的不是 ValidationError 时让用例失败。 */
async function fieldErrorsFrom(action: () => Promise<unknown>) {
  try {
    await action();
  } catch (error) {
    if (error instanceof ValidationError) return error.fieldErrors;
    throw error;
  }
  throw new Error('预期校验失败，但调用成功了');
}

describe('SubmitLoginUseCase', () => {
  it('P0 合法输入 → 透传端口并回传账号名', async () => {
    const auth = port({ submitLogin: vi.fn(async () => ({ accountName: '阿澈的妈妈' })) });

    await expect(new SubmitLoginUseCase(auth).execute({ account: 'a', password: 'campfire2026' })).resolves.toEqual({
      accountName: '阿澈的妈妈',
    });
  });

  it('P0 空字段 → ValidationError，且不触碰端口（校验不可绕过）', async () => {
    const auth = port();
    const errors = await fieldErrorsFrom(() => new SubmitLoginUseCase(auth).execute({ account: '', password: '' }));

    expect(errors.account).toBe('请填写账号名');
    expect(errors.password).toBe('请填写密码');
    expect(auth.submitLogin).not.toHaveBeenCalled();
  });

  it('P0 端口拒绝原样上抛（不吞掉原因）', async () => {
    const auth = port({ submitLogin: vi.fn(async () => Promise.reject(new AuthError('invalid-credentials'))) });

    await expect(new SubmitLoginUseCase(auth).execute({ account: 'a', password: 'campfire2026' })).rejects.toThrow(
      '账号名或密码不正确',
    );
  });
});

describe('SubmitRegisterUseCase', () => {
  it('P0 合法输入 → 透传端口并回传账号名', async () => {
    const auth = port({ submitRegister: vi.fn(async () => ({ accountName: '新账号' })) });

    await expect(
      new SubmitRegisterUseCase(auth).execute({ account: 'a', password: 'campfire2026', inviteCode: 'A1B2C3D4' }),
    ).resolves.toEqual({ accountName: '新账号' });
  });

  it('P0 空邀请码 → ValidationError，且不触碰端口', async () => {
    const auth = port();
    const errors = await fieldErrorsFrom(() =>
      new SubmitRegisterUseCase(auth).execute({ account: 'a', password: 'campfire2026', inviteCode: '' }),
    );

    expect(errors.inviteCode).toBe('请填写邀请码');
    expect(auth.submitRegister).not.toHaveBeenCalled();
  });

  it('P0 邀请码被拒 → AuthError 原样上抛', async () => {
    const auth = port({ submitRegister: vi.fn(async () => Promise.reject(new AuthError('invite-rejected'))) });

    await expect(
      new SubmitRegisterUseCase(auth).execute({ account: 'a', password: 'campfire2026', inviteCode: 'BAD' }),
    ).rejects.toThrow('邀请码无效或已被使用');
  });
});

describe('LogoutUseCase', () => {
  it('P0 成功时不抛异常', async () => {
    const auth = port();

    await expect(new LogoutUseCase(auth).execute()).resolves.toBeUndefined();
    expect(auth.signOut).toHaveBeenCalledTimes(1);
  });

  it('P0 端口抛 AuthError → 原样上抛（保留分类）', async () => {
    const auth = port({ signOut: vi.fn(async () => Promise.reject(new AuthError('rate-limited'))) });

    await expect(new LogoutUseCase(auth).execute()).rejects.toThrow('尝试次数过多，请稍后再试');
  });

  it('P0 端口抛非 AuthError → 收敛为 service-unavailable，不得静默成功', async () => {
    // 登出失败被记成成功会让使用者以为已登出、而服务端会话可能仍有效。
    const auth = port({ signOut: vi.fn(async () => Promise.reject(new Error('boom'))) });

    await expect(new LogoutUseCase(auth).execute()).rejects.toThrow('服务暂时不可用，请稍后再试');
  });
});
