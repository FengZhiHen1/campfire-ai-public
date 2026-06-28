/**
 * useAuth Hook —— L1a（表现层）与 L1b（逻辑层）之间的唯一认证桥接。
 *
 * 职责：
 * - 返回 useAuthReturn 接口（sessionState、isAuthenticated、user、login、logout）
 * - login() → mock AUTH-02 登录 API → 更新 Store + Storage
 * - logout() → 清除 Storage + Store + reLaunch 登录页
 * - 订阅 Zustand Store，自动响应状态变更
 *
 * 所有 feature 模块通过此 Hook 获取认证状态和操作方法。
 *
 * 技术栈：React Hooks + Zustand 5.x + Taro 4.x
 *
 * 设计依据：AUTH-06 落地规范 §1.2、§1.5 步骤 1 和 6、§1.6.1
 * 契约对齐：docs/contracts/AUTH-06/useAuthReturn.json
 */

import { useCallback, useMemo } from 'react';
// React 移植版：移除 Taro 依赖，使用 window.location + localStorage
import { useSessionStore, type SessionState, type SessionUser } from '../store/userStore';
import {
  tokenManager,
  buildMockLoginResponse,
  LoginError,
  SessionExpiredError,
} from '../services/tokenManager';
import type { TokenPair } from '../store/userStore';
import { parseJWTPayload } from '../utils/storage';

// ============================================================================
// useAuthReturn 接口 —— 与契约 docs/contracts/AUTH-06/useAuthReturn.json 一致
// ============================================================================

/**
 * useAuth() Hook 的返回接口。
 * 契约文件：docs/contracts/AUTH-06/useAuthReturn.json
 */
export interface UseAuthReturn {
  /** 当前会话状态枚举值 */
  sessionState: SessionState;
  /** sessionState === 'authenticated' 的便捷布尔值 */
  isAuthenticated: boolean;
  /** 当前用户信息，未登录时为 null */
  user: SessionUser | null;
  /**
   * 登录方法。
   * 调用 AUTH-02 POST /api/v1/auth/login（当前 mock），
   * 成功后自动更新 TokenPair 和 sessionState。
   *
   * @param username - 用户名
   * @param password - 密码
   * @throws {LoginError} 登录请求失败或凭证无效
   */
  login: (username: string, password: string) => Promise<void>;
  /**
   * 登出方法。
   * 清除 Taro Storage 中的 TokenPair，
   * 重置 SessionState 为 unauthenticated，
   * reLaunch 到登录页。
   * 不抛出异常。
   */
  logout: () => void;
}

// ============================================================================
// 内部工具函数
// ============================================================================

/**
 * 从 JWT accessToken 中解析用户信息。
 *
 * @param accessToken - JWT 访问令牌
 * @returns SessionUser 或 null
 */
function parseUserFromAccessToken(accessToken: string): SessionUser | null {
  const payload = parseJWTPayload(accessToken);
  if (!payload || typeof payload.sub !== 'string') {
    return null;
  }
  return {
    userId: payload.sub,
    roles: Array.isArray(payload.roles)
      ? payload.roles.filter((r: unknown): r is string => typeof r === 'string')
      : [],
  };
}

/**
 * 检查当前页面是否为首页，避免重复跳转。
 * MVP 阶段无独立登录页，登出后回到首页。
 *
 * @returns 是否已在首页
 */
function isOnHomePage(): boolean {
  try {
    return window.location.pathname === '/' || window.location.pathname.startsWith('/home');
  } catch {
    return false;
  }
}

// ============================================================================
// useAuth Hook
// ============================================================================

/**
 * 认证状态桥接 Hook。
 *
 * 所有 React 组件通过此 Hook 获取认证状态和操作方法。
 * 必须在组件顶层调用（遵守 React Hooks 规则）。
 *
 * @returns UseAuthReturn — 包含会话状态、用户信息和 login/logout 方法
 */
export function useAuth(): UseAuthReturn {
  // 订阅 Zustand Store（选择器优化：仅订阅需要的字段）
  const sessionState: SessionState = useSessionStore((state) => state.sessionState);
  const user: SessionUser | null = useSessionStore((state) => state.user);
  const tokenPair: TokenPair | null = useSessionStore((state) => state.tokenPair);

  // 便捷布尔值
  const isAuthenticated: boolean = sessionState === 'authenticated';

  // ==========================================================================
  // login —— 登录
  // ==========================================================================

  const login = useCallback(
    async (username: string, password: string): Promise<void> => {
      try {
        // ================================================================
        // Mock: AUTH-02 登录 API 调用
        // 真实实现参考（AUTH-02 后端就绪后取消注释，删除下方 mock）：
        // const response = await Taro.request({
        //   url: '/api/v1/auth/login',
        //   method: 'POST',
        //   data: { username, password },
        //   header: { 'Content-Type': 'application/json' },
        // });
        // const mockResponse = response.data as {
        //   access_token: string;
        //   refresh_token: string;
        //   token_type: string;
        // };
        // ================================================================
        const mockResponse = await new Promise<{
          access_token: string;
          refresh_token: string;
          token_type: 'Bearer';
        }>((resolve) => {
          // 模拟网络延迟
          setTimeout(() => {
            resolve(buildMockLoginResponse(username, password));
          }, 100);
        });

        // 校验 mock 响应
        if (
          !mockResponse.access_token ||
          !mockResponse.refresh_token ||
          mockResponse.token_type !== 'Bearer'
        ) {
          throw new LoginError('Invalid login response format');
        }

        // snake_case → camelCase
        const newTokenPair: TokenPair = {
          accessToken: mockResponse.access_token,
          refreshToken: mockResponse.refresh_token,
        };

        // 更新 Zustand Store
        const store = useSessionStore.getState();
        store.setAuthenticated(newTokenPair);

        // 解析并设置 user 信息
        const parsedUser: SessionUser | null = parseUserFromAccessToken(newTokenPair.accessToken);
        if (parsedUser) {
          store.setUser(parsedUser);
        }

        // 持久化到 Taro Storage
        tokenManager.setTokens(newTokenPair);
      } catch (error: unknown) {
        if (error instanceof LoginError) {
          throw error;
        }
        if (error instanceof Error) {
          throw new LoginError(`Login failed: ${error.message}`);
        }
        throw new LoginError('Login failed with unknown error');
      }
    },
    [], // 无外部依赖；使用 useSessionStore.getState() 而非订阅
  );

  // ==========================================================================
  // logout —— 登出
  // ==========================================================================

  const logout = useCallback((): void => {
    try {
      // 步骤 1：清除 Storage
      tokenManager.clearTokens();

      // 步骤 2：重置 Zustand Store
      useSessionStore.getState().setUnauthenticated();

      // 步骤 3：跳转首页（MVP 阶段无独立登录页，避免重复跳转）
      if (!isOnHomePage()) {
        window.location.href = '/';
      }
    } catch {
      // logout 不抛异常——Storage 清除失败仍执行跳转
      try {
        if (!isOnHomePage()) {
          window.location.href = '/';
        }
      } catch {
        // 最终降级：静默失败
      }
    }
  }, []);

  // ==========================================================================
  // 返回值
  // ==========================================================================

  // useMemo 防止每次渲染都创建新对象引用（优化下游 React.memo 组件）
  return useMemo<UseAuthReturn>(
    () => ({
      sessionState,
      isAuthenticated,
      user,
      login,
      logout,
    }),
    [sessionState, isAuthenticated, user, login, logout],
  );
}
