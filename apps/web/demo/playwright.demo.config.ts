/**
 * 模块: demo/playwright.demo.config
 * 职责: 演示材料装置的独立 Playwright 配置——**不启动 webServer**（真实栈由使用者先起）
 * 数据来源:
 *   - docs/运维/演示材料生成.md: MUST — 运行前提、入口命令、产物落点
 *   - apps/web/e2e-real/playwright.real.config.ts: 同类装置的做法（`testDir: '.'` 的解析语义）
 * 边界:
 *   - 依赖: @playwright/test、./support/paths、./global.setup
 *   - 被依赖: `pnpm --filter @campfire/web demo`（scripts 里的入口）
 * 禁止行为:
 *   - 禁止声明 webServer：本装置测的是「真 Vite + 真 FastAPI + 真模型」，起假服务器就换了被测对象
 *   - 禁止开重试：演示材料要的是确定性；重试会把「这次刚好没崩」写成「跑通了」
 */

import { defineConfig, devices } from '@playwright/test';

import {
  BASE_URL,
  DEVICE_SCALE_FACTOR,
  PLAYWRIGHT_OUTPUT_DIR,
  SCENARIO_TIMEOUT_MS,
  SETTLE_TIMEOUT_MS,
  VIEWPORT,
} from './support/paths';

export default defineConfig({
  // `.` 而不是 `./scenarios`：testDir 相对**本配置文件所在目录**解析，
  // 而 global.setup 与 manifest.spec 也在这一层（写成 `./scenarios` 会让 globalSetup 解析错位）。
  testDir: '.',
  // 开新批：校验声明 → 清上一轮 → 写批号 → 检查真实栈前提。必须在所有 project 之前恰好跑一次。
  globalSetup: './global.setup.ts',
  // 串行：同一套真实库与同一份模型额度，并发跑既会互相干扰，也读不出「顺序即演示顺序」。
  fullyParallel: false,
  workers: 1,
  // 重试一次。**理由与闸门不同**：这不是「测试是否通过」的闸门，而是「生成一次能拿去讲的材料」的
  // 生成器，而真实模型有 180 秒单轮上限、TokenHub 也会偶发延迟尖峰（实测过 25 秒的探针请求与
  // 200 秒都等不到首字的轮次）。一次重试能把「模型这一次慢」与「链路不通」区分开：链路真不通时
  // 两次都红。重试会留在报告里（该用例标记为 flaky），不会被悄悄抹平。
  retries: 1,
  reporter: [['list']],
  outputDir: PLAYWRIGHT_OUTPUT_DIR,
  timeout: SCENARIO_TIMEOUT_MS,
  expect: { timeout: SETTLE_TIMEOUT_MS },
  use: {
    baseURL: BASE_URL,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    viewport: VIEWPORT,
    deviceScaleFactor: DEVICE_SCALE_FACTOR,
    // 三种产物全关：截图由本装置自己截并自算哈希；失败截图/视频/trace 会往产物区塞
    // 不可复现的二进制。**trace 尤其不能留**：实测失败用例的 `trace.zip` 里含
    // `sAccessToken`/`sRefreshToken` 与 `set-cookie`（独立复查 FAIL-8）——材料目录是要交给
    // 别人的，里面不该有可用凭据。需要排查时临时加 `--trace on` 并把产物指到 `.tmp/`。
    screenshot: 'off',
    video: 'off',
    trace: 'off',
  },
  projects: [
    {
      name: 'demo',
      testMatch: /scenarios\/.*\.spec\.ts$/,
      use: { ...devices['Desktop Chrome'], viewport: VIEWPORT, deviceScaleFactor: DEVICE_SCALE_FACTOR },
    },
    {
      // 汇总与复算必须在全部场景跑完之后执行，故用 dependencies 而不是 globalTeardown：
      // 后者的失败只被记成「清理期间的错误」，且拿不到用例级上下文。
      name: 'demo-manifest',
      testMatch: /manifest\.spec\.ts$/,
      dependencies: ['demo'],
    },
  ],
});
