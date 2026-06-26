/**
 * 统一 HTTP 客户端 —— MVP 匿名版（基于 Taro.request）。
 *
 * 职责：
 * - 请求拦截器：注入 X-Device-Id 请求头，自动拼接 API base URL
 * - 响应拦截器：非 2xx 响应统一抛异常
 *
 * 所有业务模块通过此客户端发送 API 请求。
 */

import Taro from '@tarojs/taro';
import { deviceManager } from './tokenManager';

export interface IRequestResponse<T = unknown> {
  data: T;
  statusCode: number;
  header: Record<string, unknown>;
  errMsg: string;
}

/** HTTP 错误异常 */
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

/** 编译时由 Taro defineConstants 注入：WeApp 模式为 http://127.0.0.1:8000，H5 为空（走 proxy） */
const API_BASE: string = process.env.TARO_APP_API_BASE || '';

function resolveUrl(path: string): string {
  return API_BASE ? API_BASE + path : path;
}

/**
 * 统一 HTTP 客户端。
 */
export const httpClient = {
  /**
   * 发送 HTTP 请求（自动注入 X-Device-Id，自动拼接 API base URL）。
   * 非 2xx 响应统一抛出 HttpError，调用方 catch 处理。
   */
  async request<T = unknown>(options: Taro.request.Option): Promise<IRequestResponse<T>> {
    if (process.env.TARO_APP_USE_MOCK === 'true') {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const { mockRequest } = require('./mock/mockRouter');
      return mockRequest(options) as Promise<IRequestResponse<T>>;
    }

    const deviceId = deviceManager.getDeviceId();

    const config: Taro.request.Option = {
      ...options,
      url: resolveUrl(options.url),
      header: {
        ...(options.header as Record<string, unknown> || {}),
        'X-Device-Id': deviceId,
        'ngrok-skip-browser-warning': '1',
      },
    };

    const res = await Taro.request(config) as unknown as IRequestResponse<T>;

    if (res.statusCode < 200 || res.statusCode >= 300) {
      const detail = (res.data as Record<string, unknown>)?.detail;
      const message = typeof detail === 'string' ? String(detail) : `HTTP ${res.statusCode}`;
      throw new HttpError(res.statusCode, message, res.data);
    }

    return res;
  },
};
