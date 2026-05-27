/**
 * Token 持久化与续期管理器
 *
 * 职责：
 * - TokenPair 的 Storage CRUD（读/写/清除）
 * - Token 续期：调用 AUTH-03 refresh 接口（当前使用 mock）
 * - 续期失败计数与降级策略
 *
 * AUTH-02 / AUTH-03 后端未落地时使用 mock 数据。
 * mock 替换为真实 API 时仅需修改本文件中的 URL 和请求体字段映射。
 *
 * 技术栈：Taro 4.x 同步 Storage API + Zustand 5.x Store
 *
 * 设计依据：AUTH-06 落地规范 §1.2、§1.4、§1.5 步骤 4、§1.9
 * 契约对齐：docs/contracts/AUTH-06/TokenPair.json
 */

import Taro from '@tarojs/taro';
import type { TokenPair, SessionUser } from '../store/userStore';
import { useSessionStore } from '../store/userStore';
import {
  STORAGE_KEYS,
  safeSetStorage,
  safeRemoveStorage,
  validateTokenPairFormat,
  validateJWTFormat,
  parseJWTPayload,
  base64UrlEncode,
} from '../utils/storage';

// ============================================================================
// 续期 API 常量
// ============================================================================

/** AUTH-03 Token 续期接口路径 */
const REFRESH_API_URL: string = '/api/v1/auth/refresh';

/** 续期请求超时时间（毫秒） */
const REFRESH_TIMEOUT_MS: number = 10000;

// ============================================================================
// Mock 数据工具（AUTH-02/AUTH-03 后端未落地时使用）
// ============================================================================

/**
 * 生成符合 JWT 三段式格式的 mock token。
 * 用于 AUTH-02 登录和 AUTH-03 续期 mock 响应。
 *
 * @param payload - JWT payload 对象
 * @returns base64url 编码的三段式 JWT 字符串
 */
function createMockToken(payload: Record<string, unknown>): string {
  const header: Record<string, unknown> = { alg: 'HS256', typ: 'JWT', kid: 'mock' };
  const headerB64: string = base64UrlEncode(JSON.stringify(header));
  const payloadB64: string = base64UrlEncode(JSON.stringify(payload));
  const signatureB64: string = base64UrlEncode('mock-signature-for-dev');
  return `${headerB64}.${payloadB64}.${signatureB64}`;
}

/**
 * 构建 mock 续期 API 响应。
 * 模拟 AUTH-03 POST /api/v1/auth/refresh 的成功响应。
 *
 * @param _refreshToken - 当前使用的刷新令牌（mock 中忽略）
 * @returns snake_case 的 mock 响应（对齐 AUTH-03 意图文档）
 */
function buildMockRefreshResponse(_refreshToken: string): {
  access_token: string;
  refresh_token: string;
} {
  const nowSec: number = Math.floor(Date.now() / 1000);
  const userId: string = '550e8400-e29b-41d4-a716-446655440000';
  const roles: string[] = ['family'];

  return {
    access_token: createMockToken({
      sub: userId,
      roles,
      exp: nowSec + 900, // 15 分钟
      iat: nowSec,
    }),
    refresh_token: createMockToken({
      sub: userId,
      roles,
      type: 'refresh',
      exp: nowSec + 604800, // 7 天
      iat: nowSec,
    }),
  };
}

/**
 * 构建 mock 登录 API 响应。
 * 模拟 AUTH-02 POST /api/v1/auth/login 的成功响应。
 *
 * @param _username - 用户名（mock 中忽略）
 * @param _password - 密码（mock 中忽略）
 * @returns snake_case 的 mock 响应（对齐 AUTH-02 意图文档）
 */
export function buildMockLoginResponse(_username: string, _password: string): {
  access_token: string;
  refresh_token: string;
  token_type: 'Bearer';
} {
  const nowSec: number = Math.floor(Date.now() / 1000);
  const userId: string = '550e8400-e29b-41d4-a716-446655440000';
  const roles: string[] = ['family'];

  return {
    access_token: createMockToken({
      sub: userId,
      roles,
      exp: nowSec + 900,
      iat: nowSec,
    }),
    refresh_token: createMockToken({
      sub: userId,
      roles,
      type: 'refresh',
      exp: nowSec + 604800,
      iat: nowSec,
    }),
    token_type: 'Bearer',
  };
}

// ============================================================================
// Snake-case → CamelCase 转换
// ============================================================================

/**
 * 将 AUTH-02/AUTH-03 API 响应的 snake_case 字段转换为 AUTH-06 内部 camelCase 格式。
 *
 * @param apiResponse - 蛇形命名的 API 响应
 * @returns 驼峰命名的 TokenPair
 */
function mapApiResponseToTokenPair(apiResponse: {
  access_token: string;
  refresh_token: string;
}): TokenPair {
  return {
    accessToken: apiResponse.access_token,
    refreshToken: apiResponse.refresh_token,
  };
}

/**
 * 从 JWT accessToken 解析 SessionUser。
 *
 * @param accessToken - JWT 访问令牌
 * @returns 解析出的 SessionUser，解析失败返回 null
 */
function parseUserFromToken(accessToken: string): SessionUser | null {
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

// ============================================================================
// TokenManager 对外接口
// ============================================================================

/**
 * Token 持久化与续期管理器。
 * 所有下游模块（含 httpClient）通过此对象操作 Token 数据，
 * 禁止直接调用 Taro.setStorageSync('auth:token_pair', ...)。
 */
export const tokenManager = {
  // ==========================================================================
  // getTokens —— 从 Storage 读取 TokenPair
  // ==========================================================================

  /**
   * 从 Taro Storage 同步读取持久化的 TokenPair，并执行结构和 JWT 格式校验。
   *
   * @returns 有效的 TokenPair，读取失败或校验失败返回 null
   */
  getTokens(): TokenPair | null {
    const raw = Taro.getStorageSync(STORAGE_KEYS.TOKEN_PAIR);
    if (raw === null || raw === undefined) {
      return null;
    }
    let parsed: unknown;
    try {
      parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;
    } catch {
      return null;
    }
    if (!validateTokenPairFormat(parsed)) {
      return null;
    }
    if (!validateJWTFormat(parsed.accessToken) || !validateJWTFormat(parsed.refreshToken)) {
      return null;
    }
    return parsed;
  },

  // ==========================================================================
  // setTokens —— 持久化 TokenPair 到 Storage
  // ==========================================================================

  /**
   * 将 TokenPair 写入 Taro Storage。
   * 同时写入时间戳键（auth:token_pair:timestamp）。
   * 容量超限时降级：清除旧数据后重试 1 次；仍失败则仅保留于内存。
   *
   * @param tokenPair - 待持久化的 TokenPair
   * @returns 写入是否成功
   */
  setTokens(tokenPair: TokenPair): boolean {
    const value: string = JSON.stringify(tokenPair);
    const success: boolean = safeSetStorage(STORAGE_KEYS.TOKEN_PAIR, value);
    if (success) {
      safeSetStorage(STORAGE_KEYS.TOKEN_TIMESTAMP, Date.now());
    }
    return success;
  },

  // ==========================================================================
  // clearTokens —— 清除 Storage 中的 TokenPair
  // ==========================================================================

  /**
   * 清除 Taro Storage 中 auth:token_pair 和 auth:token_pair:timestamp 两个键。
   * 不清除用户业务数据（草稿、设置等）。
   */
  clearTokens(): void {
    safeRemoveStorage(STORAGE_KEYS.TOKEN_PAIR);
    safeRemoveStorage(STORAGE_KEYS.TOKEN_TIMESTAMP);
  },

  // ==========================================================================
  // refreshTokens —— 续期 TokenPair
  // ==========================================================================

  /**
   * 调用 AUTH-03 POST /api/v1/auth/refresh 续期 TokenPair。
   * 当前使用 mock 实现（AUTH-03 后端未落地）。
   *
   * 续期流程：
   * 1. 从 Zustand Store 读取 refreshToken
   * 2. 发送续期请求（mock，超时 10s）
   * 3. 成功 → 更新 Store（setAuthenticated）+ Storage + 重置 failCount → resolve TokenPair
   * 4. 失败 → failCount += 1
   *    a. < 3 → restoreAuthenticated（保留原 Token，计数递增）→ reject RefreshInProgressError
   *    b. >= 3 → clearTokens + setUnauthenticated + reLaunch → reject SessionExpiredError
   *
   * @returns Promise<TokenPair> — 成功时返回新 TokenPair
   * @throws {RefreshInProgressError} 续期失败但计数 < 3
   * @throws {SessionExpiredError} 续期连续失败 >= 3 次
   */
  async refreshTokens(): Promise<TokenPair> {
    const store = useSessionStore.getState();
    const currentTokenPair: TokenPair | null = store.tokenPair;

    // 防御：无 refreshToken 时直接拒绝
    if (!currentTokenPair || !currentTokenPair.refreshToken) {
      store.setUnauthenticated();
      this.clearTokens();
      throw new SessionExpiredError('No refresh token available');
    }

    try {
      // ================================================================
      // Mock: AUTH-03 续期 API 调用（替换为真实 Taro.request 时仅需修改此处）
      // ================================================================
      const mockResponse = await new Promise<{
        access_token: string;
        refresh_token: string;
      }>((resolve) => {
        setTimeout(() => {
          resolve(buildMockRefreshResponse(currentTokenPair.refreshToken));
        }, 100); // 模拟网络延迟 100ms
      });
      // ================================================================
      // 真实实现参考（AUTH-03 后端就绪后取消注释，删除上方 mock）：
      // const response = await Taro.request({
      //   url: REFRESH_API_URL,
      //   method: 'POST',
      //   data: { refresh_token: currentTokenPair.refreshToken },
      //   timeout: REFRESH_TIMEOUT_MS,
      //   header: { 'Content-Type': 'application/json' },
      // });
      // const mockResponse = response.data as { access_token: string; refresh_token: string };
      // ================================================================

      // 成功：转换 snake_case → camelCase
      const newTokenPair: TokenPair = mapApiResponseToTokenPair(mockResponse);

      // 更新 Zustand Store（重置 failCount）
      store.setAuthenticated(newTokenPair);

      // 解析 user 信息
      const user: SessionUser | null = parseUserFromToken(newTokenPair.accessToken);
      if (user) {
        store.setUser(user);
      }

      // 持久化到 Taro Storage
      this.setTokens(newTokenPair);

      return newTokenPair;
    } catch (error: unknown) {
      // 续期失败处理
      store.incrementFailCount();
      const failCount: number = useSessionStore.getState().refreshFailCount;

      if (failCount < 3) {
        // 软失败：保持 authenticated，保留原 Token，等待下次 401 触发续期
        // 使用 restoreAuthenticated 保留 failCount 不清除
        store.restoreAuthenticated(currentTokenPair);
        throw new RefreshInProgressError(
          `Token refresh failed (attempt ${failCount}/3), will retry on next request`,
        );
      }

      // 硬失败：连续失败 >= 3 次，清除会话
      this.clearTokens();
      store.setUnauthenticated();

      // reLaunch 到登录页（避免重复跳转）
      try {
        const pages = Taro.getCurrentPages();
        const currentPage = pages.length > 0 ? pages[pages.length - 1] : null;
        if (!currentPage || currentPage.route !== 'pages/login/index') {
          Taro.reLaunch({ url: '/pages/login/index' });
        }
      } catch {
        // reLaunch 失败不影响状态清除
      }

      throw new SessionExpiredError(
        'Session expired after 3 consecutive refresh failures, please login again',
      );
    }
  },
};

// ============================================================================
// 自定义异常类型
// ============================================================================

/**
 * 会话过期异常。
 * 续期连续失败 3 次或 refreshToken 缺失时抛出。
 */
export class SessionExpiredError extends Error {
  public readonly code: string = 'SESSION_EXPIRED';

  constructor(message: string) {
    super(message);
    this.name = 'SessionExpiredError';
    // 确保 instanceof 检查在 TypeScript target ES5 时正常工作
    Object.setPrototypeOf(this, SessionExpiredError.prototype);
  }
}

/**
 * 续期进行中失败异常。
 * 续期失败但计数 < 3 时抛出，业务模块可选择重试。
 * 此异常为内部使用，不应对最终用户展示。
 */
export class RefreshInProgressError extends Error {
  public readonly code: string = 'REFRESH_IN_PROGRESS_FAILED';

  constructor(message: string) {
    super(message);
    this.name = 'RefreshInProgressError';
    Object.setPrototypeOf(this, RefreshInProgressError.prototype);
  }
}

/**
 * 登录失败异常。
 * useAuth.login() 调用 AUTH-02 登录 API 失败时抛出。
 */
export class LoginError extends Error {
  public readonly code: string = 'LOGIN_FAILED';

  constructor(message: string) {
    super(message);
    this.name = 'LoginError';
    Object.setPrototypeOf(this, LoginError.prototype);
  }
}
