/**
 * 模块: src/test/setup
 * 职责: vitest 全局夹具——把 jsdom 环境补齐到应用代码需要的最小面
 * 数据来源:
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 5 节（SDK 读取 window）
 * 边界:
 *   - 依赖: @testing-library/react 的清理钩子
 *   - 被依赖: vite.config.ts 的 test.setupFiles
 * 禁止行为:
 *   - 禁止在此伪造业务数据（夹具只补运行环境，不造被测数据）
 */

import '@testing-library/react';

import { afterEach, beforeEach } from 'vitest';
import { cleanup } from '@testing-library/react';
import { clearUnauthorizedHandler } from '../infrastructure/http/client';
import { resetSessionInitForTests } from '../infrastructure/auth/session';

/**
 * jsdom 未实现 ResizeObserver，而 assistant-ui 的 Viewport 在挂载时用它观察内容尺寸。
 * 这里补一个不触发回调的空实现：本包不对滚动与自动吸底做断言，夹具只需要让挂载不抛错。
 */
if (globalThis.ResizeObserver === undefined) {
  globalThis.ResizeObserver = class {
    observe(): void {
      // 夹具实现：不观察也不回调。
    }
    unobserve(): void {
      // 夹具实现：无操作。
    }
    disconnect(): void {
      // 夹具实现：无操作。
    }
  };
}

/**
 * jsdom 的 Element 没有 scrollTo，而 assistant-ui 的 Viewport 自动吸底会调用它。
 * 补一个无操作实现：本包不对滚动位置做断言，只需让挂载与更新路径不抛错。
 */
if (typeof Element !== 'undefined' && Element.prototype.scrollTo === undefined) {
  Element.prototype.scrollTo = function scrollTo(): void {
    // 夹具实现：无操作。
  };
}

beforeEach(() => {
  resetSessionInitForTests();
});

afterEach(() => {
  cleanup();
  // 401 处置回调是模块级单例；不清理会让上一个用例装好的 spy 被下一个用例触发。
  clearUnauthorizedHandler();
});
