/**
 * 模块: app/sessionCacheReset
 * 职责: 会话身份变化时清掉按会话归属的前端缓存
 * 数据来源:
 *   - docs/design/pages/设置页.md: MUST — 登出后不得残留上一个账号的界面数据
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 4.2 节（会话级状态归 store）
 * 边界:
 *   - 依赖: features/accounts 的会话 store、features/consult 的会话级 store
 *   - 被依赖: app/App 的启动装配
 * 禁止行为:
 *   - 禁止清凭据或授权结论（这里清的都是呈现态；凭据本就在 httpOnly cookie 里）
 *   - 禁止只在某一个登出入口清：401、主动登出、换成另一个账号必须走同一条路径
 */

import { useSessionStore, type SessionStoreState } from '../features/accounts/viewModel/sessionStore';
import { resetConsultRunStore } from '../features/consult/viewModel/runStore';

/**
 * 会话身份键：状态 + 展示名。
 *
 * 只看 `status` 会漏掉「已登录时在 /login 换成另一个账号」——那次切换仍是 authenticated，
 * 只有展示名变了；它是前端唯一可读的账号身份信号（凭据在 httpOnly cookie 里）。
 */
function identityOf(state: Pick<SessionStoreState, 'session' | 'account'>): string {
  return `${state.session.status}|${state.account?.accountName ?? ''}`;
}

/**
 * 订阅会话身份变化并在变化时清空咨询面的会话级缓存；返回退订函数。
 *
 * 用 store 订阅而不是 `useEffect`+选择器：后者让整个 App 随会话状态重渲染。
 * 键一变就清（登出 / 401 / 直接换账号 / 查证失败）；同一身份的重复确认不清——
 * 那不是身份变化，清了只会让使用者丢掉正在看的候选与草稿。
 */
export function installSessionCacheReset(): () => void {
  let previous = identityOf(useSessionStore.getState());
  return useSessionStore.subscribe((state) => {
    const next = identityOf(state);
    if (next === previous) return;
    previous = next;
    resetConsultRunStore();
  });
}
