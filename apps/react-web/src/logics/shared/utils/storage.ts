const PREFIX = 'campfire_';

function key(name: string): string {
  return `${PREFIX}${name}`;
}

export function getItem(name: string): string | null {
  return localStorage.getItem(key(name));
}

export function setItem(name: string, value: string): void {
  localStorage.setItem(key(name), value);
}

export function removeItem(name: string): void {
  localStorage.removeItem(key(name));
}

export function getJSON<T = unknown>(name: string): T | null {
  const raw = getItem(name);
  if (!raw) return null;
  try { return JSON.parse(raw) as T; } catch { return null; }
}

export function setJSON(name: string, value: unknown): void {
  setItem(name, JSON.stringify(value));
}

/**
 * Parse JWT payload without verification.
 * Returns the decoded payload object, or null on failure.
 */
export function parseJWTPayload<T = Record<string, unknown>>(token: string): T | null {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = parts[1];
    const decoded = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(decoded) as T;
  } catch {
    return null;
  }
}

// Re-export Taro-compatible API for gradual migration
export { getItem as getStorageSync, setItem as setStorageSync, removeItem as removeStorageSync };
