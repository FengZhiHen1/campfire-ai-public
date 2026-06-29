/**
 * Device ID 管理器（MVP 匿名版）—— React 移植版
 *
 * 职责：
 * - 生成并持久化匿名设备 ID（16 位随机字符串）
 * - 提供 getDeviceId() 供 httpClient 注入 X-Device-Id 请求头
 * - 提供 Token 管理 stub（MVP 阶段不持久化 JWT，仅用于兼容已编译的 useAuth Hook）
 *
 * MVP 阶段：Token 相关为存根实现，不涉及真实 JWT 逻辑。
 */

import { getItem, setItem } from '../utils/storage';

const DEVICE_ID_KEY = 'campfire_device_id';
const DEVICE_ID_LENGTH = 16;

function generateDeviceId(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  return Array.from({ length: DEVICE_ID_LENGTH }, () =>
    chars.charAt(Math.floor(Math.random() * chars.length))
  ).join('');
}

function getOrCreateDeviceId(): string {
  // MVP 评委体验阶段：后端已固定映射到预置 judge 账号，
  // device_id 仅作为请求头占位，不再决定用户身份。
  // 本地持久化一个稳定随机值即可，避免每次刷新变化。
  try {
    const stored = getItem(DEVICE_ID_KEY);
    if (stored) return stored;
  } catch { /* ignore */ }

  const newId = generateDeviceId();
  try { setItem(DEVICE_ID_KEY, newId); } catch { /* ignore */ }
  return newId;
}

export const deviceManager = {
  getDeviceId(): string {
    return getOrCreateDeviceId();
  },

  regenerate(): string {
    const newId = generateDeviceId();
    try { setItem(DEVICE_ID_KEY, newId); } catch { /* ignore */ }
    return newId;
  },
};

// ============================================================================
// Token 管理存根（MVP 匿名版 — 兼容 useAuth Hook 编译）
// ============================================================================

export class LoginError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'LoginError';
  }
}

export class SessionExpiredError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SessionExpiredError';
  }
}

export function buildMockLoginResponse(
  _username: string,
  _password: string,
): { access_token: string; refresh_token: string; token_type: 'Bearer' } {
  return {
    access_token: 'mock-jwt-header.' +
      btoa(JSON.stringify({ sub: 'mock-user', roles: [] })) +
      '.mock-signature',
    refresh_token: 'mock-refresh-token',
    token_type: 'Bearer',
  };
}

export const tokenManager = {
  setTokens(_tokens: { accessToken: string; refreshToken: string }): void {
    // MVP: no-op
  },
  clearTokens(): void {
    // MVP: no-op
  },
};
