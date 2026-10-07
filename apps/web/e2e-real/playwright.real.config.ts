/**
 * 模块: e2e-real/playwright.real.config
 * 职责: 真实依赖端到端的独立 Playwright 配置——**不启动任何 webServer**（后端与前端由使用者起）
 *
 * ⚠ 需要真实栈，见支持模块 e2e-real/support/real.ts 的文件头。
 *
 * 与截图基建（apps/web/playwright.config.ts）的关系：两者互不影响。
 *   - 截图基建 testDir = ./e2e，本配置 `testDir: '.'`（**相对本配置文件所在目录**解析，
 *     而本文件就在 e2e-real/ 里 ⇒ `.` 等价于 `e2e-real`；理由见下方 `testDir` 处注释）
 *     ⇒ `pnpm shots` 收不到本目录；
 *   - 本配置**不声明 webServer**：它假设 5173（Vite dev，/api 代理到 8000）与 8000 已在跑。
 *     起不来时用例直接失败（缺环境 = 失败，不是静默 skip）。
 *
 * 运行：
 *   pnpm --filter @campfire/web exec playwright test --config e2e-real/playwright.real.config.ts --grep "@real"
 */

import { defineConfig, devices } from '@playwright/test';

import { BASE_URL, OUT_DIR } from './support/real';

export default defineConfig({
  // `.` 而不是 `./e2e-real`：testDir 相对**本配置文件所在目录**解析，而本文件就在
  // e2e-real/ 里。写成 `./e2e-real` 会让 Playwright 去找 e2e-real/e2e-real 并报
  // 「No tests found」——一个看起来像「没有用例」的假阴性。
  testDir: '.',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  // 真实模型调用在同一会话里串行发生；单条用例上界给到 180s（首字 ≤30s、整体 ≤120s 是判据，
  // 这里留出注册/登录/水合的余量）。
  timeout: 180_000,
  reporter: [['list']],
  outputDir: `${OUT_DIR}/.playwright-real`,
  expect: { timeout: 20_000 },
  use: {
    baseURL: BASE_URL,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    // 真实栈的调试价值高于产物整洁：失败时留 trace 与截图到 .tmp/T10。
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    ...devices['Desktop Chrome'],
    viewport: { width: 1280, height: 1000 },
  },
  projects: [{ name: 'real', use: { ...devices['Desktop Chrome'] } }],
});
