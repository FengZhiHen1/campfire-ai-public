/**
 * 统一 HTTP 客户端 —— MVP 匿名版（基于 Taro.request）。
 *
 * 职责：
 * - 请求拦截器：注入 X-Device-Id 请求头，自动拼接 API base URL
 * - 响应拦截器：透传，无 JWT 续期逻辑
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
   */
  async request<T = unknown>(options: Taro.request.Option): Promise<IRequestResponse<T>> {
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

    return Taro.request(config) as unknown as Promise<IRequestResponse<T>>;
  },
};
