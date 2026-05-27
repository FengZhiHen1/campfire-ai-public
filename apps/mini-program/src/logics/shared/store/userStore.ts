/**
 * Zustand SessionStore —— 前端认证会话状态管理
 *
 * 职责：
 * - 管理三态 sessionState（authenticated / refreshing / unauthenticated）
 * - 持有 tokenPair、refreshFailCount、user 等运行时状态
 * - 暴露 5 个核心 action + 辅助 setter
 * - 导出 initSession() 供 app.ts:onLaunch 调用，从 Taro Storage 恢复会话
 *
 * 技术栈：Zustand 5.x + TypeScript（严格模式，禁止 any）
 *
 * 设计依据：AUTH-06 落地规范 §1.2、§1.8
 * 契约对齐：docs/contracts/AUTH-06/SessionState.json, TokenPair.json, useAuthReturn.json
 */

import { create, type StoreApi } from 'zustand';
import {
  STORAGE_KEYS,
  safeGetStorage,
  safeRemoveStorage,
  validateTokenPair,
  parseJWTPayload,
} from '../utils/storage';

// ============================================================================
// 类型定义（与 docs/contracts/AUTH-06/ 契约一致）
// ============================================================================

/**
 * 前端认证会话状态枚举。
 * 契约文件：docs/contracts/AUTH-06/SessionState.json
 */
export type SessionState = 'authenticated' | 'refreshing' | 'unauthenticated';

/**
 * 认证令牌对。
 * 契约文件：docs/contracts/AUTH-06/TokenPair.json
 * 字段：accessToken (JWT, 15min), refreshToken (JWT, 7天)
 */
export interface TokenPair {
  readonly accessToken: string;
  readonly refreshToken: string;
}

/**
 * 当前登录用户简要信息。
 * 从 JWT accessToken payload 解析，与 useAuthReturn.json 中 user 字段一致。
 */
export interface SessionUser {
  readonly userId: string;
  readonly roles: string[];
}

// ============================================================================
// Zustand Store 接口定义
// ============================================================================

export interface SessionStoreState {
  /** 当前会话状态 */
  sessionState: SessionState;
  /** 令牌对，未登录时为 null */
  tokenPair: TokenPair | null;
  /** 跨请求续期失败累计计数（续期成功或重新登录时归零） */
  refreshFailCount: number;
  /** 当前登录用户信息，未登录时为 null */
  user: SessionUser | null;
}

export interface SessionStoreActions {
  /**
   * Action 1: 设置已登录状态。
   * 更新 tokenPair，重置 refreshFailCount 为 0，状态置 authenticated。
   */
  setAuthenticated: (tokenPair: TokenPair) => void;

  /**
   * Action 2: 设置续期中状态。
   * 仅从 authenticated 状态允许进入 refreshing；已在 refreshing 时幂等跳过。
   */
  setRefreshing: () => void;

  /**
   * Action 3: 设置未登录状态。
   * 清空 tokenPair、user，重置 refreshFailCount 为 0，状态置 unauthenticated。
   */
  setUnauthenticated: () => void;

  /**
   * Action 4: 续期失败计数 +1。
   */
  incrementFailCount: () => void;

  /**
   * Action 5: 重置续期失败计数为 0。
   */
  resetFailCount: () => void;

  /**
   * 辅助 setter：设置当前用户信息。
   */
  setUser: (user: SessionUser | null) => void;

  /**
   * 辅助 setter：恢复已登录状态但保留 refreshFailCount（续期软失败时使用）。
   * 续期失败次数 < 3 时，状态回 authenticated，Token 不清除，计数保留。
   */
  restoreAuthenticated: (tokenPair: TokenPair) => void;
}

export type SessionStore = SessionStoreState & SessionStoreActions;

// ============================================================================
// Store 创建
// ============================================================================

/**
 * 全局认证会话 Store。
 * 所有 feature 模块通过 useAuth() Hook 间接访问，禁止直接 import 本 Store 的 setState。
 */
export const useSessionStore = create<SessionStore>()((set, get) => ({
  // --- 初始状态 ---
  sessionState: 'unauthenticated',
  tokenPair: null,
  refreshFailCount: 0,
  user: null,

  // --- Action 1: setAuthenticated ---
  setAuthenticated: (tokenPair: TokenPair): void => {
    set({
      sessionState: 'authenticated',
      tokenPair,
      refreshFailCount: 0,
    });
  },

  // --- Action 2: setRefreshing (幂等) ---
  setRefreshing: (): void => {
    const { sessionState } = get();
    if (sessionState !== 'authenticated') {
      return; // 仅在 authenticated 状态允许进入 refreshing
    }
    set({ sessionState: 'refreshing' });
  },

  // --- Action 3: setUnauthenticated ---
  setUnauthenticated: (): void => {
    set({
      sessionState: 'unauthenticated',
      tokenPair: null,
      refreshFailCount: 0,
      user: null,
    });
  },

  // --- Action 4: incrementFailCount ---
  incrementFailCount: (): void => {
    set((state) => ({
      refreshFailCount: state.refreshFailCount + 1,
    }));
  },

  // --- Action 5: resetFailCount ---
  resetFailCount: (): void => {
    set({ refreshFailCount: 0 });
  },

  // --- 辅助 setter: setUser ---
  setUser: (user: SessionUser | null): void => {
    set({ user });
  },

  // --- 辅助 setter: restoreAuthenticated (保留 failCount) ---
  restoreAuthenticated: (tokenPair: TokenPair): void => {
    set({
      sessionState: 'authenticated',
      tokenPair,
    });
    // refreshFailCount 保持不变
  },
}));

// ============================================================================
// 冷启动会话恢复
// ============================================================================

/**
 * 从 Taro Storage 同步恢复会话状态。
 * 调用时机：app.ts:onLaunch 中调用，必须在任何 UI 渲染之前完成。
 *
 * 恢复流程：
 * 1. 读取 Storage 中的 TokenPair
 * 2. 结构 + JWT 格式 + refreshToken 过期校验
 * 3. 校验通过 → setAuthenticated + 解析 user
 * 4. 校验失败 → 清空损坏数据 + setUnauthenticated
 */
export function initSession(): void {
  const store = useSessionStore as unknown as StoreApi<SessionStore>;

  // 步骤 1：读取持久化数据
  const stored = safeGetStorage<string>(STORAGE_KEYS.TOKEN_PAIR);

  if (stored === null || stored === undefined) {
    store.getState().setUnauthenticated();
    return;
  }

  let tokenPair: unknown;
  try {
    tokenPair = JSON.parse(stored);
  } catch {
    // JSON 解析失败 → 数据损坏，清空
    safeRemoveStorage(STORAGE_KEYS.TOKEN_PAIR);
    safeRemoveStorage(STORAGE_KEYS.TOKEN_TIMESTAMP);
    store.getState().setUnauthenticated();
    return;
  }

  // 步骤 2-3：结构 + JWT + 过期校验
  if (!validateTokenPair(tokenPair)) {
    // 校验失败 → 清空不完整数据
    safeRemoveStorage(STORAGE_KEYS.TOKEN_PAIR);
    safeRemoveStorage(STORAGE_KEYS.TOKEN_TIMESTAMP);
    store.getState().setUnauthenticated();
    return;
  }

  // 步骤 4：校验通过 → 恢复会话
  store.getState().setAuthenticated(tokenPair as { accessToken: string; refreshToken: string });

  // 解析 user 信息（从 accessToken 的 JWT payload）
  const payload = parseJWTPayload(tokenPair.accessToken);
  if (payload && typeof payload.sub === 'string') {
    const user: SessionUser = {
      userId: payload.sub,
      roles: Array.isArray(payload.roles) ? payload.roles.filter((r: unknown): r is string => typeof r === 'string') : [],
    };
    store.getState().setUser(user);
  }
  // 注意：accessToken 可能已过期，但 refreshToken 仍有效。
  // 根据设计文档 §1.7 易错点 #3：此时仍置 Authenticated，
  // 由第一次 API 调用的 401 自然触发续期。
}
