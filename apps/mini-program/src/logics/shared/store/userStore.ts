/**
 * Zustand Store —— MVP 匿名版用户状态管理
 *
 * 职责：
 * - 管理 deviceId（从 deviceManager 同步）
 * - 保留用户基本信息状态（供 UI 展示用）
 *
 * MVP 阶段：完全移除 JWT / Token / 续期相关状态。
 */

import { create } from 'zustand';
import { deviceManager } from '../services/tokenManager';

export interface SessionUser {
  readonly userId: string;
  readonly roles: string[];
}

export interface UserStoreState {
  deviceId: string;
  user: SessionUser | null;
}

export interface UserStoreActions {
  setUser: (user: SessionUser | null) => void;
  setDeviceId: (deviceId: string) => void;
}

export type UserStore = UserStoreState & UserStoreActions;

export const useSessionStore = create<UserStore>()((set) => ({
  deviceId: deviceManager.getDeviceId(),
  user: null,

  setUser: (user: SessionUser | null): void => {
    set({ user });
  },

  setDeviceId: (deviceId: string): void => {
    set({ deviceId });
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
