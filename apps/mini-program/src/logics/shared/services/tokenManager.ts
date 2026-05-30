/**
 * Device ID 管理器（MVP 匿名版）
 *
 * 职责：
 * - 生成并持久化匿名设备 ID（16 位随机字符串）
 * - 提供 getDeviceId() 供 httpClient 注入 X-Device-Id 请求头
 * - 提供 Token 管理 stub（MVP 阶段不持久化 JWT，仅用于兼容已编译的 useAuth Hook）
 *
 * MVP 阶段：Token 相关为存根实现，不涉及真实 JWT 逻辑。
 */

import Taro from '@tarojs/taro';

const DEVICE_ID_KEY = 'campfire_device_id';
const DEVICE_ID_LENGTH = 16;

/**
 * 生成随机设备 ID（URL-safe base64 子集）。
 */
function generateDeviceId(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  return Array.from({ length: DEVICE_ID_LENGTH }, () =>
    chars.charAt(Math.floor(Math.random() * chars.length))
  ).join('');
}

/**
 * 从 Storage 读取设备 ID，不存在则生成并持久化。
 *
 * MVP 开发阶段：固定返回 mock device_id，直接绑定后端 mock 档案。
 * 生产环境应恢复为随机生成逻辑。
 */
function getOrCreateDeviceId(): string {
  // 固定 mock device_id，与 scripts/seed_mock_profile.py 保持一致
  return 'campfire-mock-device';

  /* 生产环境逻辑（恢复时取消下方注释，删除上方 return）
  let deviceId: string | null = null;
  try {
    deviceId = Taro.getStorageSync(DEVICE_ID_KEY) as string | null;
  } catch {
    deviceId = null;
  }

  if (!deviceId) {
    deviceId = generateDeviceId();
    try {
      Taro.setStorageSync(DEVICE_ID_KEY, deviceId);
    } catch {
      // Storage 写入失败（如容量超限），仅在内存中使用
    }
  }

  return deviceId;
  */
}

/**
 * Device 管理器对外接口。
 */
export const deviceManager = {
  /**
   * 获取当前设备匿名 ID。
   * 首次调用时若 Storage 中不存在，会自动生成并持久化。
   */
  getDeviceId(): string {
    return getOrCreateDeviceId();
  },

  /**
   * 强制重新生成设备 ID（调试用）。
   */
  regenerate(): string {
    const newId = generateDeviceId();
    try {
      Taro.setStorageSync(DEVICE_ID_KEY, newId);
    } catch {
      // ignore
    }
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
    access_token: 'REDACTED-SET-VIA-ENV' +
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
