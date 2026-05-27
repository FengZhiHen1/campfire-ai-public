/**
 * Taro Storage 安全封装
 *
 * 职责：
 * - 定义存储键常量（auth:token_pair, auth:token_pair:timestamp）
 * - 提供安全的同步读写方法（try-catch 包裹）
 * - setStorageSync 容量超限时清除旧数据重试 1 次
 * - JWT 格式校验与 payload 解析
 *
 * 技术栈：Taro 4.x 同步 Storage API
 */

import Taro from '@tarojs/taro';

// ============================================================================
// 存储键常量
// ============================================================================

export const STORAGE_KEYS = {
  /** TokenPair 持久化键名 */
  TOKEN_PAIR: 'auth:token_pair',
  /** TokenPair 写入时间戳键名 */
  TOKEN_TIMESTAMP: 'auth:token_pair:timestamp',
} as const;

// ============================================================================
// 安全读写方法
// ============================================================================

/**
 * 安全同步读取 Storage。
 * 所有异常被捕获，返回 null 表示读取失败或键不存在。
 *
 * @param key - 存储键名
 * @returns 解析后的值，读取失败或键不存在时返回 null
 */
export function safeGetStorage<T = unknown>(key: string): T | null {
  try {
    const raw: string = Taro.getStorageSync(key);
    if (raw === null || raw === undefined || raw === '') {
      return null;
    }
    try {
      return JSON.parse(raw) as T;
    } catch {
      // 非 JSON 字符串，尝试直接返回
      return raw as unknown as T;
    }
  } catch {
    return null;
  }
}

/**
 * 安全同步写入 Storage。
 * 异常被捕获；容量超限时清除旧数据后重试 1 次。
 *
 * @param key - 存储键名
 * @param data - 待写入数据（自动 JSON.stringify）
 * @returns 写入是否成功
 */
export function safeSetStorage(key: string, data: unknown): boolean {
  try {
    const value: string = typeof data === 'string' ? data : JSON.stringify(data);
    Taro.setStorageSync(key, value);
    return true;
  } catch (e: unknown) {
    const errMsg: string = String((e as { errMsg?: string })?.errMsg ?? String(e));
    // 容量超限时清除旧数据后重试 1 次
    if (errMsg.includes('storage limit') || errMsg.includes('limit exceeded')) {
      try {
        Taro.removeStorageSync(key);
        const value: string = typeof data === 'string' ? data : JSON.stringify(data);
        Taro.setStorageSync(key, value);
        return true;
      } catch {
        return false;
      }
    }
    return false;
  }
}

/**
 * 安全同步删除 Storage 键。
 *
 * @param key - 存储键名
 * @returns 删除是否成功（键不存在也返回 true）
 */
export function safeRemoveStorage(key: string): boolean {
  try {
    Taro.removeStorageSync(key);
    return true;
  } catch {
    return false;
  }
}

// ============================================================================
// TokenPair 结构校验
// ============================================================================

/**
 * 校验 TokenPair 结构是否符合契约定义。
 * 要求：对象类型，accessToken 与 refreshToken 均为非空 string。
 *
 * @param value - 待校验的值
 * @returns 是否通过结构校验
 */
export function validateTokenPairFormat(value: unknown): value is { accessToken: string; refreshToken: string } {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const obj = value as Record<string, unknown>;
  return (
    typeof obj.accessToken === 'string' &&
    obj.accessToken.length > 0 &&
    typeof obj.refreshToken === 'string' &&
    obj.refreshToken.length > 0
  );
}

// ============================================================================
// JWT 工具方法
// ============================================================================

/** JWT 三段式格式正则：header.payload.signature */
const JWT_REGEX: RegExp = /^[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+$/;

/**
 * 校验 token 是否满足 JWT 三段式格式。
 *
 * @param token - 待校验 token 字符串
 * @returns 是否满足 JWT 格式
 */
export function validateJWTFormat(token: string): boolean {
  if (typeof token !== 'string' || token.length === 0) {
    return false;
  }
  return JWT_REGEX.test(token);
}

/** JWT payload 解析后的类型 */
export interface JWTPayload {
  sub?: string;
  roles?: string[];
  exp?: number;
  type?: string;
  [key: string]: unknown;
}

/**
 * 从 base64url 编码字符串解码为原始字符串。
 * 使用自定义实现，不依赖 atob/btoa（部分小程序环境不可用）。
 * 解码后的字节序列通过 decodeURIComponent 还原为 UTF-8 原始字符串，
 * 确保中文等多字节字符可逆编解码。
 *
 * @param base64url - base64url 编码字符串
 * @returns 解码后的 UTF-8 字符串
 */
function base64UrlDecode(base64url: string): string {
  // base64url -> base64
  let base64: string = base64url.replace(/-/g, '+').replace(/_/g, '/');
  // 补齐 padding
  while (base64.length % 4 !== 0) {
    base64 += '=';
  }

  const chars: string = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=';
  const bytes: number[] = [];
  let i: number = 0;

  while (i < base64.length) {
    const enc1: number = chars.indexOf(base64[i++]);
    const enc2: number = chars.indexOf(base64[i++]);
    const enc3: number = chars.indexOf(base64[i++]);
    const enc4: number = chars.indexOf(base64[i++]);

    if (enc1 === -1 || enc2 === -1) break;

    bytes.push((enc1 << 2) | (enc2 >> 4));

    if (enc3 !== -1 && enc3 !== 64) {
      bytes.push(((enc2 & 15) << 4) | (enc3 >> 2));
    }
    if (enc4 !== -1 && enc4 !== 64) {
      bytes.push(((enc3 & 3) << 6) | enc4);
    }
  }

  // 将字节序列转为 percent-encoded UTF-8，再用 decodeURIComponent 还原
  let percentEncoded: string = '';
  for (const byte of bytes) {
    percentEncoded += '%' + byte.toString(16).padStart(2, '0').toUpperCase();
  }

  try {
    return decodeURIComponent(percentEncoded);
  } catch {
    // 解码失败时返回原始字节字符串（兼容非 UTF-8 数据）
    let fallback: string = '';
    for (const byte of bytes) {
      fallback += String.fromCharCode(byte);
    }
    return fallback;
  }
}

/**
 * base64url 编码（不含 padding）。
 * 使用自定义实现，不依赖 atob/btoa（部分小程序环境不可用）。
 * 先将字符串通过 encodeURIComponent 转为 UTF-8 字节序列再编码，
 * 确保中文等多字节字符可逆编解码。
 *
 * @param str - 待编码字符串
 * @returns base64url 编码字符串
 */
export function base64UrlEncode(str: string): string {
  // 将字符串转换为 UTF-8 字节序列：encodeURIComponent 产生 %XX 形式，
  // 再通过正则替换提取出每个原始字节
  const utf8Str: string = encodeURIComponent(str).replace(/%([0-9A-F]{2})/g, (_match: string, hex: string): string => {
    return String.fromCharCode(parseInt(hex, 16));
  });

  const chars: string = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  let output: string = '';
  let i: number = 0;

  while (i < utf8Str.length) {
    const byte1: number = utf8Str.charCodeAt(i++);
    const byte2: number = i < utf8Str.length ? utf8Str.charCodeAt(i++) : NaN;
    const byte3: number = i < utf8Str.length ? utf8Str.charCodeAt(i++) : NaN;

    const enc1: number = byte1 >> 2;
    const enc2: number = ((byte1 & 3) << 4) | (isNaN(byte2) ? 0 : byte2 >> 4);
    const enc3: number = isNaN(byte2) ? 64 : ((byte2 & 15) << 2) | (isNaN(byte3) ? 0 : byte3 >> 6);
    const enc4: number = isNaN(byte3) ? 64 : byte3 & 63;

    output += chars[enc1] + chars[enc2];
    if (enc3 !== 64) output += chars[enc3];
    if (enc4 !== 64) output += chars[enc4];
  }

  // base64 -> base64url（替换 +/ 为 -_，移除 padding）
  return output.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/**
 * 解析 JWT token 的 payload 段。
 * 仅解析 payload（第二段），不验证签名。
 *
 * @param token - JWT token 字符串
 * @returns 解析后的 payload 对象，解析失败返回 null
 */
export function parseJWTPayload(token: string): JWTPayload | null {
  if (!validateJWTFormat(token)) {
    return null;
  }
  try {
    const parts: string[] = token.split('.');
    const payloadStr: string = base64UrlDecode(parts[1]);
    const payload: unknown = JSON.parse(payloadStr);
    if (typeof payload !== 'object' || payload === null) {
      return null;
    }
    return payload as JWTPayload;
  } catch {
    return null;
  }
}

/**
 * 检查 JWT token 是否已过期（基于 exp 声明）。
 *
 * @param token - JWT token 字符串
 * @returns 是否已过期。exp 字段缺失时视为已过期（安全优先）
 */
export function isTokenExpired(token: string): boolean {
  const payload: JWTPayload | null = parseJWTPayload(token);
  if (!payload || typeof payload.exp !== 'number') {
    return true;
  }
  // exp 是秒级 Unix 时间戳，Date.now() 返回毫秒
  return payload.exp * 1000 <= Date.now();
}

/**
 * 验证 TokenPair 完整性：
 * 1. 结构校验（两位均存在且为非空 string）
 * 2. JWT 格式校验（三段式正则）
 * 3. refreshToken 未过期
 *
 * @param tokenPair - 待验证的 TokenPair
 * @returns 是否有效
 */
export function validateTokenPair(tokenPair: unknown): tokenPair is { accessToken: string; refreshToken: string } {
  if (!validateTokenPairFormat(tokenPair)) {
    return false;
  }
  if (!validateJWTFormat(tokenPair.accessToken) || !validateJWTFormat(tokenPair.refreshToken)) {
    return false;
  }
  if (isTokenExpired(tokenPair.refreshToken)) {
    return false;
  }
  return true;
}
