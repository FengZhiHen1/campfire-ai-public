/**
 * 模块: app/sessionCacheReset.test
 * 职责: 会话身份变化清缓存的回归守卫（登出 / 401 / 直接换账号）与「不该清」的负例
 * 数据来源:
 *   - docs/design/pages/设置页.md: MUST — 登出后不得残留上一个账号的界面数据
 * 边界:
 *   - 依赖: app/sessionCacheReset、accounts 的会话 store、consult 的会话级 store
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止只断言「没有抛错」：判据是 store 里那几个字段真的被清空（或真的被保留）
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { installSessionCacheReset } from './sessionCacheReset';
import { useSessionStore } from '../features/accounts/viewModel/sessionStore';
import { resetConsultRunStore, useRunStore } from '../features/consult/viewModel/runStore';
import { createDraft } from '../features/consult/domain/questionBatch';
import { QUESTION_ITEMS } from '../features/consult/test/fixtures';

/** 上一个账号留在内存里的东西：当前会话、待用技能、提问草稿、候选。 */
function seedConsultCache(): void {
  useRunStore.getState().reset('s-old');
  useRunStore.getState().selectSkill('daily-consulting');
  useRunStore.getState().setQuestionDraft(createDraft('batch-old', QUESTION_ITEMS));
  useRunStore.getState().applyRunEvent({
    type: 'candidate',
    candidate: { reference: '上一次对话', summary: '上一个账号的候选' },
  });
}

function expectCacheCleared(): void {
  const state = useRunStore.getState();
  expect(state.sessionId).toBeNull();
  expect(state.pendingSkill).toBeNull();
  expect(state.questionDrafts).toEqual({});
  expect(state.candidates).toEqual([]);
}

let uninstall: (() => void) | null = null;

beforeEach(() => {
  localStorage.clear();
  resetConsultRunStore();
  useSessionStore.setState({ session: { status: 'unknown' }, account: null });
});

afterEach(() => {
  uninstall?.();
  uninstall = null;
});

describe('installSessionCacheReset', () => {
  it('登出 / 401（→ anonymous）清空咨询面的会话级缓存', () => {
    useSessionStore.getState().markAuthenticated({ accountName: '账号 A' });
    seedConsultCache();
    uninstall = installSessionCacheReset();

    useSessionStore.getState().markAnonymous();

    expectCacheCleared();
  });

  it('不经 anonymous 直接换成另一个账号也要清（/login 在已登录时仍可直达）', () => {
    useSessionStore.getState().markAuthenticated({ accountName: '账号 A' });
    uninstall = installSessionCacheReset();
    seedConsultCache();

    useSessionStore.getState().markAuthenticated({ accountName: '账号 B' });

    expectCacheCleared();
  });

  it('负例：同一身份的重复确认不清（不是身份变化，清了会丢掉正在看的候选与草稿）', () => {
    useSessionStore.getState().markAuthenticated({ accountName: '账号 A' });
    uninstall = installSessionCacheReset();
    seedConsultCache();

    // 重登同一账号 / refresh 再次返回同一结果：状态与展示名都没变。
    useSessionStore.getState().markAuthenticated({ accountName: '账号 A' });
    useSessionStore.setState((state) => ({ session: { ...state.session } }));

    expect(useRunStore.getState().sessionId).toBe('s-old');
    expect(useRunStore.getState().pendingSkill).toBe('daily-consulting');
  });

  it('负例：安装本身不清已有缓存（首帧身份快照只作比较基准）', () => {
    useSessionStore.getState().markAuthenticated({ accountName: '账号 A' });
    seedConsultCache();

    uninstall = installSessionCacheReset();

    expect(useRunStore.getState().sessionId).toBe('s-old');
  });

  it('退订后不再清（App 卸载 / StrictMode 的 setup→cleanup 之后不残留订阅）', () => {
    useSessionStore.getState().markAuthenticated({ accountName: '账号 A' });
    seedConsultCache();
    installSessionCacheReset()();

    useSessionStore.getState().markAnonymous();

    expect(useRunStore.getState().sessionId).toBe('s-old');
  });
});
