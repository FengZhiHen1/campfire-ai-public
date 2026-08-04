/**
 * 模块: react-web.infrastructure.http.tokenManager
 * 职责: JWT Token 对的持久化与读取（localStorage）。
 *       ADR-013：取代旧 deviceManager（X-Device-Id 匿名轨已废除）。
 * 边界:
 *   - 依赖: domain/auth（TokenPair 类型）
 *   - 被依赖: infrastructure/http/httpClient、viewModel/auth/userStore
 */

import type { TokenPair } from '@/domain/auth';

const ACCESS_TOKEN_KEY = 'campfire_access_token';
const REFRESH_TOKEN_KEY = 'campfire_refresh_token';

export const tokenStorage = {
  getAccessToken(): string | null {
    try {
      return localStorage.getItem(ACCESS_TOKEN_KEY);
    } catch {
      return null;
    }
  },

  getRefreshToken(): string | null {
    try {
      return localStorage.getItem(REFRESH_TOKEN_KEY);
    } catch {
      return null;
    }
  },

  getTokenPair(): TokenPair | null {
    const accessToken = this.getAccessToken();
    const refreshToken = this.getRefreshToken();
    if (!accessToken || !refreshToken) return null;
    return { accessToken, refreshToken };
  },

  setTokens(pair: TokenPair): void {
    try {
      localStorage.setItem(ACCESS_TOKEN_KEY, pair.accessToken);
      localStorage.setItem(REFRESH_TOKEN_KEY, pair.refreshToken);
    } catch {
      // 存储不可用（隐私模式等）——会话降级为内存态，由 store 持有
    }
  },

  clearTokens(): void {
    try {
      localStorage.removeItem(ACCESS_TOKEN_KEY);
      localStorage.removeItem(REFRESH_TOKEN_KEY);
    } catch {
      // ignore
    }
  },
};
