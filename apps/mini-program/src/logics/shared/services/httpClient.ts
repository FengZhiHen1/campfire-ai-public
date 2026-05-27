/**
 * 统一 HTTP 客户端 —— 基于 Taro.addInterceptor 封装。
 *
 * 职责：
 * - 请求拦截器：从 Zustand Store 读取 accessToken → 注入 Authorization: Bearer <token>
 * - 响应拦截器：捕获 401 → Promise 队列锁 → 触发 tokenManager.refreshTokens()
 *   → 成功重放请求 / 失败 reject
 * - 防死递归：续期接口本身的 401 不触发续期
 * - 并发续期互斥：refreshPromise 单例，后续 401 请求 await 同一 Promise
 *
 * 所有 L1b 业务模块必须通过此客户端发送 API 请求，
 * 禁止绕过拦截器直接使用 Taro.request。
 *
 * 技术栈：Taro 4.x addInterceptor + Zustand 5.x Store
 *
 * 设计依据：AUTH-06 落地规范 §1.2、§1.5 步骤 2-3、§1.6.2
 * 契约对齐：docs/contracts/AUTH-06/httpClient.json
 */

import Taro from '@tarojs/taro';
import type { TokenPair } from '../store/userStore';
import { useSessionStore } from '../store/userStore';
import { tokenManager, SessionExpiredError, RefreshInProgressError } from './tokenManager';

// ============================================================================
// 类型定义
// ============================================================================

/**
 * httpClient.request() 的标准化返回值。
 * 与 Taro.request.SuccessCallbackResult 结构对齐。
 */
export interface IRequestResponse<T = unknown> {
  /** 响应数据（已自动 JSON.parse） */
  data: T;
  /** HTTP 状态码 */
  statusCode: number;
  /** 响应头 */
  header: Record<string, unknown>;
  /** 错误信息（Taro 内部使用） */
  errMsg: string;
}

// ============================================================================
// 续期接口路径（防死递归检查）
// ============================================================================

const REFRESH_API_PATH: string = '/api/v1/auth/refresh';

// ============================================================================
// Promise 队列锁 —— 续期单例
// ============================================================================

/**
 * 全局唯一的续期 Promise。
 * null = 当前无续期进行中。
 * 第一个 401 创建 Promise 并赋给此变量；
 * 后续并发 401 检测到非 null 时直接 await 同一 Promise。
 */
let refreshPromise: Promise<TokenPair> | null = null;

// ============================================================================
// 拦截器注册标志
// ============================================================================

let interceptorRegistered: boolean = false;

// ============================================================================
// 内部工具函数
// ============================================================================

/**
 * 检查给定 URL 是否为续期接口（防止死递归）。
 *
 * @param url - 请求 URL
 * @returns 是否匹配续期接口
 */
function isRefreshEndpoint(url: string): boolean {
  return url === REFRESH_API_PATH || url.endsWith(REFRESH_API_PATH);
}

/**
 * 使用新 token 重放原始请求。
 * 直接调用 Taro.request（不经过 httpClient.request），
 * 但会经过 Taro 拦截器链（Authorization 头由请求拦截器重新注入）。
 *
 * @param originalConfig - 原始请求配置
 * @returns 重放请求的响应
 */
async function retryRequest<T>(originalConfig: Taro.request.Option): Promise<IRequestResponse<T>> {
  // 确保 header 对象存在
  const config: Taro.request.Option = {
    ...originalConfig,
  };
  return Taro.request(config) as unknown as Promise<IRequestResponse<T>>;
}

// ============================================================================
// 拦截器注册
// ============================================================================

/**
 * 注册请求/响应拦截器到 Taro 拦截器链。
 * 仅应在应用启动时调用一次（httpClient 模块首次被导入时自动调用）。
 *
 * 请求拦截：
 * - 从 Zustand Store 读取 accessToken
 * - 非续期接口时注入 Authorization: Bearer <accessToken>
 *
 * 响应拦截：
 * - 非 401 响应 → 透传
 * - 401 且 URL 为续期接口 → 直接 reject（防死递归）
 * - 401 且 sessionState = unauthenticated → 直接 reject SessionExpiredError
 * - 401 且 sessionState = refreshing → await refreshPromise → 成功则重放
 * - 401 且 sessionState = authenticated → 创建 refreshPromise → 执行续期 → 成功则重放
 */
function registerInterceptor(): void {
  if (interceptorRegistered) {
    return;
  }
  interceptorRegistered = true;

  Taro.addInterceptor(
    (chain: Taro.Chain): Promise<unknown> => {
      // ====================================================================
      // 请求拦截器
      // ====================================================================
      const requestParams: Taro.request.Option = chain.requestParams;
      const store = useSessionStore.getState();

      // 非续期接口时注入 Authorization 头
      if (!isRefreshEndpoint(requestParams.url)) {
        const accessToken: string | undefined = store.tokenPair?.accessToken;
        if (accessToken) {
          requestParams.header = {
            ...(requestParams.header as Record<string, unknown>),
            Authorization: `Bearer ${accessToken}`,
          };
        }
      }

      // ====================================================================
      // 响应拦截器
      // ====================================================================
      return chain.proceed(requestParams).then(async (res: Taro.request.SuccessCallbackResult) => {
        // 非 401 响应 → 透传
        if (res.statusCode !== 401) {
          return res;
        }

        // 续期接口本身返回 401 → 直接 reject（防死递归）
        if (isRefreshEndpoint(requestParams.url)) {
          return Promise.reject(new SessionExpiredError('Refresh token is invalid or expired'));
        }

        // 获取当前 Store 状态
        const currentState = useSessionStore.getState();

        // ------------------------------------------------------------------
        // 状态 = unauthenticated → 直接 reject
        // ------------------------------------------------------------------
        if (currentState.sessionState === 'unauthenticated') {
          return Promise.reject(new SessionExpiredError('User is not authenticated'));
        }

        // ------------------------------------------------------------------
        // 状态 = refreshing → 等待已有的 refreshPromise
        // ------------------------------------------------------------------
        if (currentState.sessionState === 'refreshing' && refreshPromise !== null) {
          try {
            const newTokens: TokenPair = await refreshPromise;
            // 续期成功 → 用新 token 重放原始请求
            return retryRequest(requestParams);
          } catch (refreshError: unknown) {
            // 续期失败 → 透传错误
            return Promise.reject(refreshError);
          }
        }

        // ------------------------------------------------------------------
        // 状态 = authenticated → 发起续期
        // ------------------------------------------------------------------
        if (currentState.sessionState === 'authenticated') {
          // 尝试进入 refreshing 状态（幂等：仅从 authenticated 可进入）
          useSessionStore.getState().setRefreshing();

          // 双重检查：确认已进入 refreshing 状态
          const afterSetState = useSessionStore.getState();
          if (afterSetState.sessionState !== 'refreshing') {
            // 另一个并发请求已抢先进入 refreshing
            if (refreshPromise !== null) {
              try {
                const newTokens: TokenPair = await refreshPromise;
                return retryRequest(requestParams);
              } catch (refreshError: unknown) {
                return Promise.reject(refreshError);
              }
            }
            // 极端情况：状态为 refreshing 但 refreshPromise 为 null → 拒绝
            return Promise.reject(new RefreshInProgressError('Refresh is already in progress'));
          }

          // 创建续期 Promise 单例
          refreshPromise = tokenManager.refreshTokens();

          try {
            const newTokens: TokenPair = await refreshPromise;
            // 续期成功 → 用新 token 重放原始请求
            return retryRequest(requestParams);
          } catch (refreshError: unknown) {
            // 续期失败 → 透传错误（由 tokenManager 内部已处理状态更新和 clearSession）
            return Promise.reject(refreshError);
          } finally {
            // 无论成功或失败，清除 refreshPromise 单例
            refreshPromise = null;
          }
        }

        // 不应到达此处（状态机已覆盖所有情况）
        return Promise.reject(new SessionExpiredError('Unknown session state'));
      });
    },
  );
}

// ============================================================================
// 模块加载时自动注册拦截器
// ============================================================================

registerInterceptor();

// ============================================================================
// httpClient 对外接口
// ============================================================================

/**
 * 统一 HTTP 客户端。
 * 所有 L1b 业务模块通过此客户端发送 API 请求。
 *
 * 自动行为：
 * 1. 请求拦截器：注入 Authorization: Bearer <accessToken>
 * 2. 响应拦截器：捕获 401 → 触发续期 → 成功时重放请求
 * 3. 续期失败 >= 3 次：清除会话 + reLaunch 登录页 + reject 所有等待请求
 *
 * 契约文件：docs/contracts/AUTH-06/httpClient.json
 */
export const httpClient = {
  /**
   * 发送 HTTP 请求（带自动 Token 注入和 401 续期）。
   *
   * @param options - Taro 标准请求配置（url, method, data, header 等）
   * @returns Promise<IRequestResponse<T>> — 请求响应
   *
   * @throws {SessionExpiredError} 续期连续失败 3 次或会话已过期
   * @throws {RefreshInProgressError} 续期进行中失败（业务可自行重试）
   *
   * @example
   * ```typescript
   * const res = await httpClient.request<ProfileData>({
   *   url: '/api/v1/profiles/123',
   *   method: 'GET',
   * });
   * console.log(res.data);
   * ```
   */
  async request<T = unknown>(options: Taro.request.Option): Promise<IRequestResponse<T>> {
    // 拦截器已在模块加载时注册，直接使用 Taro.request 即可
    // 所有 Token 注入和 401 续期由拦截器自动处理
    return Taro.request(options) as unknown as Promise<IRequestResponse<T>>;
  },
};
