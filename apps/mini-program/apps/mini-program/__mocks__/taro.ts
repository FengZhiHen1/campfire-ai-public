/**
 * Taro 最小 mock —— 供 vitest 测试环境使用。
 * 仅覆盖 CSLT-08 模块实现中实际调用的 Taro API。
 */

const storage: Record<string, string> = {};

export default {
  setStorageSync(key: string, data: string): void {
    storage[key] = data;
  },
  getStorageSync(key: string): string {
    return storage[key] ?? '';
  },
  removeStorageSync(key: string): void {
    delete storage[key];
  },
  navigateTo(_options: { url: string }): Promise<unknown> {
    return Promise.resolve({ errMsg: 'navigateTo:ok' });
  },
  request<T = unknown>(_options: Record<string, unknown>): Promise<T> {
    return Promise.resolve({ data: {}, statusCode: 200, header: {}, errMsg: 'request:ok' } as unknown as T);
  },
  getCurrentPages(): Array<{ route: string }> {
    return [];
  },
  reLaunch(_options: { url: string }): Promise<unknown> {
    return Promise.resolve({ errMsg: 'reLaunch:ok' });
  },
  addInterceptor(_fn: unknown): void {},
  interceptors: {} as unknown,
};
