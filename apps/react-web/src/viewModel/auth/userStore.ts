/**
 * 模块: react-web.viewModel.auth.userStore
 * 职责: 认证会话全局状态（Zustand）——用户实体、会话状态、Token 对。
 *       ADR-013：取代旧 logics/shared/store/userStore.ts（匿名 stub 版，S6 移除）。
 * 边界:
 *   - 依赖: domain/auth、infrastructure/http/tokenManager
 *   - 被依赖: viewModel/auth/useAuth、view 层（经 useAuth Hook）
 */

import { create } from 'zustand';
import type { AuthUser, TokenPair } from '@/domain/auth';
import { tokenStorage } from '@/infrastructure/http/tokenManager';

export type SessionState = 'loading' | 'authenticated' | 'unauthenticated';

export interface UserStoreState {
  user: AuthUser | null;
  sessionState: SessionState;
  tokenPair: TokenPair | null;
}

export interface UserStoreActions {
  /** 登录/刷新成功：写入 Token 对（持久化 + 内存） */
  setSession: (user: AuthUser, tokens: TokenPair) => void;
  /** 仅更新用户实体（/me 刷新） */
  setUser: (user: AuthUser | null) => void;
  /** 会话失效/登出：清空全部会话状态 */
  clearSession: () => void;
  /** 应用启动时从本地存储恢复 Token（sessionState: loading → unauthenticated） */
  restoreFromStorage: () => TokenPair | null;
}

export type UserStore = UserStoreState & UserStoreActions;

export const useUserStore = create<UserStore>()((set) => ({
  user: null,
  sessionState: 'loading',
  tokenPair: null,

  setSession: (user, tokens) => {
    tokenStorage.setTokens(tokens);
    set({ user, tokenPair: tokens, sessionState: 'authenticated' });
  },

  setUser: (user) => {
    set({ user });
  },

  clearSession: () => {
    tokenStorage.clearTokens();
    set({ user: null, tokenPair: null, sessionState: 'unauthenticated' });
  },

  restoreFromStorage: () => {
    const pair = tokenStorage.getTokenPair();
    if (pair) {
      set({ tokenPair: pair });
      return pair;
    }
    set({ sessionState: 'unauthenticated' });
    return null;
  },
}));
