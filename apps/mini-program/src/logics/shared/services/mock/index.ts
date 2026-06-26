/**
 * MOCK 模块桶导出。
 */
export { MockDatabase } from './mockDatabase';
export { mockRequest } from './mockRouter';
export { MockSseSimulator } from './mockSseSimulator';

/** 编译时常量：仅在 USE_MOCK=true 构建时为 true。 */
export const isMockEnabled = (): boolean =>
  process.env.TARO_APP_USE_MOCK === 'true';
