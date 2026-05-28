/**
 * Device ID 管理器（MVP 匿名版）
 *
 * 职责：
 * - 生成并持久化匿名设备 ID（16 位随机字符串）
 * - 提供 getDeviceId() 供 httpClient 注入 X-Device-Id 请求头
 *
 * MVP 阶段：完全移除 JWT Token 管理逻辑。
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
 */
function getOrCreateDeviceId(): string {
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
