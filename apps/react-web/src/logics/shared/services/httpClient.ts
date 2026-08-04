/**
 * 统一 HTTP 客户端 —— React 移植版（基于 fetch）。
 *
 * 职责：
 * - 请求拦截器：注入 Authorization Bearer token（ADR-013，经新 tokenStorage 桥接）
 * - 响应拦截器：非 2xx 响应统一抛异常
 *
 * 过渡形态：S1 起 token 注入桥接至 infrastructure/http/tokenManager；
 * 本客户端整体将在 S6 五层重组时被 infrastructure/http/httpClient 取代并删除。
 */

import { tokenStorage } from '@/infrastructure/http/tokenManager';
import { deviceManager } from './tokenManager';

export interface IRequestResponse<T = unknown> {
  data: T;
  statusCode: number;
  header: Record<string, unknown>;
  errMsg: string;
}

export class HttpError extends Error {
  statusCode: number;
  data: unknown;

  constructor(statusCode: number, message: string, data: unknown) {
    super(message);
    this.name = 'HttpError';
    this.statusCode = statusCode;
    this.data = data;
  }
}

const API_BASE: string = import.meta.env.VITE_API_BASE || '';

function resolveUrl(path: string): string {
  return API_BASE ? API_BASE + path : path;
}

export interface RequestOptions {
  url: string;
  method?: string;
  data?: unknown;
  header?: Record<string, unknown>;
  timeout?: number;
}

export const httpClient = {
  async request<T = unknown>(options: RequestOptions): Promise<IRequestResponse<T>> {
    if (import.meta.env.VITE_USE_MOCK === 'true') {
      const { mockRequest } = await import('./mock/mockRouter');
      return mockRequest(options) as Promise<IRequestResponse<T>>;
    }

    const deviceId = deviceManager.getDeviceId();
    const url = resolveUrl(options.url);
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-Device-Id': deviceId,
      'ngrok-skip-browser-warning': '1',
      ...(options.header as Record<string, string> || {}),
    };
    // ADR-013：携带已认证 token（未登录时为空，由后端守卫 401 拒绝）
    const accessToken = tokenStorage.getAccessToken();
    if (accessToken) {
      headers['Authorization'] = `Bearer ${accessToken}`;
    }

    const controller = new AbortController();
    const timeoutId = options.timeout ? setTimeout(() => controller.abort(), options.timeout) : null;

    try {
      const res = await fetch(url, {
        method: options.method || 'GET',
        headers,
        body: options.data ? JSON.stringify(options.data) : undefined,
        signal: controller.signal,
      });

      if (timeoutId) clearTimeout(timeoutId);

      const contentType = res.headers.get('content-type') || '';
      const body = contentType.includes('application/json')
        ? await res.json()
        : await res.text();

      const responseHeaders: Record<string, unknown> = {};
      res.headers.forEach((v, k) => { responseHeaders[k] = v; });

      if (!res.ok) {
        const detail = (body as Record<string, unknown>)?.detail;
        let message: string;
        if (detail && typeof detail === 'object') {
          const detailMessage = (detail as Record<string, unknown>).message;
          if (typeof detailMessage === 'string') {
            message = detailMessage;
          } else {
            message = `HTTP ${res.status}`;
          }
        } else if (typeof detail === 'string') {
          message = detail;
        } else if (typeof (body as Record<string, unknown>)?.message === 'string') {
          message = (body as Record<string, unknown>).message as string;
        } else {
          message = `HTTP ${res.status}`;
        }
        throw new HttpError(res.status, message, body);
      }

      return {
        data: body as T,
        statusCode: res.status,
        header: responseHeaders,
        errMsg: 'request:ok',
      };
    } catch (err) {
      if (timeoutId) clearTimeout(timeoutId);
      if (err instanceof HttpError) throw err;
      if ((err as Error).name === 'AbortError') {
        throw new HttpError(408, 'Request timeout', null);
      }
      throw new HttpError(0, (err as Error).message || 'Network error', null);
    }
  },
};
