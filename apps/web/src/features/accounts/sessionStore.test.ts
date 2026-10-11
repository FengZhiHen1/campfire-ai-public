/**
 * 模块: src/features/accounts/sessionStore.test
 * 职责: 会话用例与 store 的三态迁移（含端口异常不得降级为匿名）
 * 数据来源:
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 6 节（登录与会话）
 * 边界:
 *   - 依赖: features/accounts 的 application 与 viewModel
 *   - 被依赖: 无
 * 禁止行为:
 *   - 禁止让端口异常静默变成「未登录」（本用例守住这条边界）
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ResolveSessionUseCase } from './application/usecases';
import type { SessionPort } from './application/ports';
import { useSessionStore } from './viewModel/sessionStore';

/** 构造一个可控的会话端口替身。 */
function port(overrides: Partial<SessionPort> = {}): SessionPort {
  return {
    doesSessionExist: vi.fn(async () => true),
    signOut: vi.fn(async () => undefined),
    ...overrides,
  };
}

beforeEach(() => {
  localStorage.clear();
  useSessionStore.setState({ session: { status: 'unknown' }, account: null });
});

describe('ResolveSessionUseCase', () => {
  it('P1 会话存在 → authenticated', async () => {
    await expect(new ResolveSessionUseCase(port()).execute()).resolves.toEqual({ status: 'authenticated' });
  });

  it('P1 会话不存在 → anonymous', async () => {
    const session = port({ doesSessionExist: vi.fn(async () => false) });
    await expect(new ResolveSessionUseCase(session).execute()).resolves.toEqual({ status: 'anonymous' });
  });

  it('P1 端口抛异常 → unknown，不得降级为 anonymous', async () => {
    const session = port({
      doesSessionExist: vi.fn(async () => {
        throw new Error('network down');
      }),
    });

    await expect(new ResolveSessionUseCase(session).execute()).resolves.toEqual({ status: 'unknown' });
  });
});

describe('sessionStore', () => {
  it('刷新保留展示名，缓存不让会话绕过真实查证；登出清掉展示名', async () => {
    useSessionStore.getState().markAuthenticated({ accountName: '普通账号' });
    expect(localStorage.getItem('campfire.account-name')).toBe('普通账号');
    vi.resetModules();
    const { useSessionStore: reloaded } = await import('./viewModel/sessionStore');
    expect(reloaded.getState().account?.accountName).toBe('普通账号');
    expect(reloaded.getState().session.status).toBe('unknown');
    const session = port();
    await reloaded.getState().refresh(session);
    expect(session.doesSessionExist).toHaveBeenCalledTimes(1);
    reloaded.getState().markAnonymous();
    expect(localStorage.getItem('campfire.account-name')).toBeNull();
    expect(reloaded.getState().account).toBeNull();
  });
  it('refresh 用端口结果更新状态', async () => {
    await useSessionStore.getState().refresh(port({ doesSessionExist: vi.fn(async () => false) }));

    expect(useSessionStore.getState().session.status).toBe('anonymous');
  });

  it('markAnonymous 把状态置为已确认未登录', () => {
    useSessionStore.getState().markAnonymous();

    expect(useSessionStore.getState().session.status).toBe('anonymous');
  });
});
