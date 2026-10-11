/**
 * 模块: features/accounts/viewModel/sessionStore
 * 职责: 会话存在性与账号名展示值的跨页面状态（Zustand），供路由守卫与设置页消费
 * 数据来源:
 *   - docs/项目结构设计.md: MUST — 第 9 节（状态归属三分：跨介质 UI 状态归 viewModel）
 *   - docs/design/pages/设置页.md: MUST — 账号名来自会话（登录态唯一账号数据）
 * 边界:
 *   - 依赖: features/accounts/domain、application
 *   - 被依赖: app 的路由守卫与装配、features/accounts 的页面
 * 禁止行为:
 *   - 禁止在 store 里存凭据（凭据在 httpOnly cookie，前端不可读）
 *   - 禁止把 store 当成权限判定（守卫只负责体验）
 */

import { create } from 'zustand';

import type { AuthenticatedAccount, SessionSnapshot } from '../domain/session';
import { unknownSession } from '../domain/session';
import { ResolveSessionUseCase } from '../application/usecases';
import type { SessionPort } from '../application/ports';

/** 会话 store 的状态与方法。 */
export interface SessionStoreState {
  session: SessionSnapshot;
  /**
   * 已登录账号的展示身份。
   *
   * 登录/注册响应提供展示名，允许仅将此非凭据字段缓存在本地以供刷新恢复。
   * null 表示本地尚无展示名，不影响会话查证；该字段不参与授权。
   */
  account: AuthenticatedAccount | null;
  /** 用给定端口重新查证会话；查证失败保持 unknown（不得降级为匿名）。 */
  refresh(session: SessionPort): Promise<void>;
  /** 登录或注册成功后写入已确认的会话与账号名。 */
  markAuthenticated(account: AuthenticatedAccount): void;
  /** 标记为已确认未登录（401 处置与登出路径使用，不经过 SDK 查证）。 */
  markAnonymous(): void;
}

// 只保存展示名；会话存在性仍由 SessionPort 查证，不缓存 token 或授权结果。
const ACCOUNT_NAME_KEY = 'campfire.account-name';
function cachedAccount(): AuthenticatedAccount | null {
  try {
    const name = globalThis.localStorage?.getItem(ACCOUNT_NAME_KEY);
    return typeof name === 'string' && name.trim() !== '' ? { accountName: name } : null;
  } catch { return null; }
}
function cacheName(name: string | null): void {
  try {
    if (name === null) globalThis.localStorage?.removeItem(ACCOUNT_NAME_KEY);
    else globalThis.localStorage?.setItem(ACCOUNT_NAME_KEY, name);
  } catch { /* 浏览器禁用存储时，展示名仍保留在内存。 */ }
}

/**
 * 为什么状态初始为 unknown 而不是 anonymous：应用冷启动时尚未查证，直接判匿名会把
 * 已登录用户在刷新页面时弹到登录页（一次误判换取一次闪烁），而判已登录会让守卫失效。
 * unknown 是一个必须被下游显式处理的第三态。
 */
export const useSessionStore = create<SessionStoreState>((set) => ({
  session: unknownSession(),
  account: cachedAccount(),
  async refresh(session: SessionPort) {
    const snapshot = await new ResolveSessionUseCase(session).execute();
    if (snapshot.status === 'anonymous') cacheName(null);
    // 查证为匿名时同时清掉账号名：留着它会让设置页在登出后仍显示上一个账号的名字。
    set(snapshot.status === 'anonymous' ? { session: snapshot, account: null } : { session: snapshot });
  },
  markAuthenticated(account: AuthenticatedAccount) {
    cacheName(account.accountName);
    set({ session: { status: 'authenticated' }, account });
  },
  markAnonymous() {
    cacheName(null);
    set({ session: { status: 'anonymous' }, account: null });
  },
}));
