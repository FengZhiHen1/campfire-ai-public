/**
 * Zustand Store —— MVP 匿名版用户状态管理
 *
 * 职责：
 * - 管理 deviceId（从 deviceManager 同步）
 * - 保留用户基本信息状态（供 UI 展示用）
 * - sessionState 默认 'authenticated'（MVP 无登录流程，匿名即认证）
 *
 * MVP 阶段：JWT / Token / 续期相关状态为 stub，供 useAuth Hook 编译通过。
 */

import { create } from 'zustand';
import { deviceManager } from '../services/tokenManager';

// ============================================================================
// 类型
// ============================================================================

export type SessionState = 'loading' | 'authenticated' | 'unauthenticated';

export interface SessionUser {
  readonly userId: string;
  readonly roles: string[];
}

export interface TokenPair {
  accessToken: string;
  refreshToken: string;
}

export interface UserStoreState {
  deviceId: string;
  user: SessionUser | null;
  sessionState: SessionState;
  tokenPair: TokenPair | null;
}

export interface UserStoreActions {
  setUser: (user: SessionUser | null) => void;
  setDeviceId: (deviceId: string) => void;
  setAuthenticated: (tokenPair: TokenPair) => void;
  setUnauthenticated: () => void;
}

export type UserStore = UserStoreState & UserStoreActions;

// ============================================================================
// Store
// ============================================================================

export const useSessionStore = create<UserStore>()((set) => ({
  deviceId: deviceManager.getDeviceId(),
  user: null,
  // MVP 阶段：匿名设备即视为已认证，无需登录流程
  sessionState: 'authenticated',
  tokenPair: null,

  setUser: (user: SessionUser | null): void => {
    set({ user });
  },

  setDeviceId: (deviceId: string): void => {
    set({ deviceId });
  },

  setAuthenticated: (tokenPair: TokenPair): void => {
    set({ sessionState: 'authenticated', tokenPair });
  },

  setUnauthenticated: () => {
    set({ sessionState: 'unauthenticated', tokenPair: null, user: null });
  },
}));

/**
 * 应用启动时初始化状态。
 * 确保 deviceId 已存在。
 */
export function initSession(): void {
  const store = useSessionStore.getState();
  if (!store.deviceId) {
    store.setDeviceId(deviceManager.getDeviceId());
  }
}
