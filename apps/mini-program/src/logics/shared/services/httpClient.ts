/**
 * 统一 HTTP 客户端 —— MVP 匿名版（基于 Taro.request）。
 *
 * 职责：
 * - 请求拦截器：注入 X-Device-Id 请求头
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

/**
 * 统一 HTTP 客户端。
 */
export const httpClient = {
  /**
   * 发送 HTTP 请求（自动注入 X-Device-Id）。
   */
  async request<T = unknown>(options: Taro.request.Option): Promise<IRequestResponse<T>> {
    const deviceId = deviceManager.getDeviceId();

    const config: Taro.request.Option = {
      ...options,
      header: {
        ...(options.header as Record<string, unknown> || {}),
        'X-Device-Id': deviceId,
      },
    };

    return Taro.request(config) as unknown as Promise<IRequestResponse<T>>;
  },
};
