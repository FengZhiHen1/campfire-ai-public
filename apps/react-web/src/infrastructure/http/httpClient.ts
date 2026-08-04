/**
 * 模块: react-web.infrastructure.http.httpClient
 * 职责: 全站统一 HTTP 客户端（S6 起为全站基础设施）。
 *       - 请求拦截：注入 Authorization Bearer token
 *       - 响应拦截：401 时单飞刷新（refresh token 轮换）后重试一次；
 *         刷新失败清空会话并跳转登录页
 *       - 错误规范化：后端 detail（code/message）→ HttpError
 * 数据来源:
 *   - py-schemas (auth): MUST — Token 端点契约
 * 边界:
 *   - 依赖: tokenManager（Token 存取）
 *   - 被依赖: infrastructure/repositories（S6 起全部仓储实现）
 * 禁止行为:
 *   - 禁止在业务层直接 fetch——必须经此客户端（token 注入与刷新唯一入口）
 */

import { tokenStorage } from './tokenManager';

export class HttpError extends Error {
  readonly statusCode: number;
  readonly code: string;
  readonly data: unknown;

  constructor(statusCode: number, message: string, code = '', data: unknown = null) {
    super(message);
    this.name = 'HttpError';
    this.statusCode = statusCode;
    this.code = code;
    this.data = data;
  }
}

/** 会话失效回调——由 viewModel 层注册（清空 store 并跳登录页） */
let onSessionExpired: (() => void) | null = null;
export function registerSessionExpiredHandler(handler: () => void): void {
  onSessionExpired = handler;
}

const API_BASE: string = import.meta.env.VITE_API_BASE || '';

function resolveUrl(path: string): string {
  return API_BASE ? API_BASE + path : path;
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  data?: unknown;
  /** 显式跳过 token 注入（登录/注册等公开端点） */
  skipAuth?: boolean;
  /** 显式跳过 401 刷新重试（refresh 端点自身） */
  skipRefresh?: boolean;
}

// ---------------------------------------------------------------------------
// 401 单飞刷新：并发 401 只触发一次 refresh，其余等待同一 Promise
// ---------------------------------------------------------------------------

let refreshingPromise: Promise<boolean> | null = null;

async function tryRefreshToken(): Promise<boolean> {
  if (refreshingPromise) return refreshingPromise;

  refreshingPromise = (async () => {
    const refreshToken = tokenStorage.getRefreshToken();
    if (!refreshToken) return false;
    try {
      const res = await fetch(resolveUrl('/api/v1/auth/refresh'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) return false;
      const body = (await res.json()) as { access_token: string; refresh_token: string };
      tokenStorage.setTokens({ accessToken: body.access_token, refreshToken: body.refresh_token });
      return true;
    } catch {
      return false;
    }
  })();

  try {
    return await refreshingPromise;
  } finally {
    refreshingPromise = null;
  }
}

function handleSessionExpired(): void {
  tokenStorage.clearTokens();
  onSessionExpired?.();
}

// ---------------------------------------------------------------------------
// 核心请求
// ---------------------------------------------------------------------------

export async function request<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (!options.skipAuth) {
    const accessToken = tokenStorage.getAccessToken();
    if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`;
  }

  let res: Response;
  try {
    res = await fetch(resolveUrl(path), {
      method: options.method || 'GET',
      headers,
      body: options.data !== undefined ? JSON.stringify(options.data) : undefined,
    });
  } catch (err) {
    throw new HttpError(0, (err as Error).message || '网络异常，请稍后重试');
  }

  // 401 → 尝试刷新后重试一次
  if (res.status === 401 && !options.skipAuth && !options.skipRefresh) {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      return request<T>(path, { ...options, skipRefresh: true });
    }
    handleSessionExpired();
    throw new HttpError(401, '登录已过期，请重新登录', 'SESSION_EXPIRED');
  }

  const contentType = res.headers.get('content-type') || '';
  const body: unknown = contentType.includes('application/json') ? await res.json() : await res.text();

  if (!res.ok) {
    throw new HttpError(res.status, extractMessage(body, res.status), extractCode(body), body);
  }

  return body as T;
}

/** 从后端错误体提取面向用户的消息（兼容 detail 对象/字符串两种形态） */
function extractMessage(body: unknown, status: number): string {
  if (body && typeof body === 'object') {
    const detail = (body as Record<string, unknown>).detail;
    if (detail && typeof detail === 'object') {
      const message = (detail as Record<string, unknown>).message;
      if (typeof message === 'string') return message;
    }
    if (typeof detail === 'string') return detail;
    const message = (body as Record<string, unknown>).message;
    if (typeof message === 'string') return message;
  }
  return `请求失败（${status}）`;
}

function extractCode(body: unknown): string {
  if (body && typeof body === 'object') {
    const detail = (body as Record<string, unknown>).detail;
    if (detail && typeof detail === 'object') {
      const code = (detail as Record<string, unknown>).code;
      if (typeof code === 'string') return code;
    }
  }
  return '';
}

export const httpClient = { request };
