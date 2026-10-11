/**
 * 模块: playwright.config
 * 职责: 截图基建的 Playwright 配置——构建产物服务器、两视口 project 与产物落点
 * 数据来源:
 *   - docs/证据/orchestrator-20261002-001/T01.md: MUST — 裁决 A/B/E（配置位置、preview 端口与生命周期、
 *     两视口均 deviceScaleFactor 2、落点支持 --out 等价通道）
 *   - apps/web/vite.config.ts: MUST — 既有 dev/preview 与 vitest 配置（本文件与它不冲突）
 * 边界:
 *   - 依赖: e2e/support/paths（落点与矩阵常量）、@playwright/test
 *   - 被依赖: `pnpm --filter @campfire/web shots`
 * 禁止行为:
 *   - 禁止把截图对象换成 dev server（裁决 B：单测绿 ≠ 样式到运行时，契约样式断言只在 build 后跑）
 *   - 禁止在本文件里写路径字面量（落点归 e2e/support/paths，默认值只有一份）
 */

import { defineConfig, devices } from '@playwright/test';

import {
  BASE_URL,
  DEVICE_SCALE_FACTOR,
  PLAYWRIGHT_OUTPUT_DIR,
  PREVIEW_PORT,
  RENDER_SETTLE_TIMEOUT_MS,
  VIEWPORTS,
} from './e2e/support/paths';

/** 构建 + 预览的总上界（毫秒）；本机 vite build 在 10 秒级，留足余量但不无限等。 */
const WEB_SERVER_TIMEOUT_MS = 240_000;

export default defineConfig({
  testDir: './e2e',

  // 开一轮新批：清上一轮残留（旧 manifest 与旧 sidecar）、生成本轮批号。
  // 必须在所有 project 之前恰好跑一次——放在某个 spec 的 beforeAll 里，
  // 两个视口 project 会并发各清一次，先跑的会把另一个已写的 sidecar 删掉（P2-3）。
  globalSetup: './e2e/global.setup.ts',

  // 逐页用例彼此独立（各起自己的 page 与夹具），并行不会互相污染：
  // 夹具都是内存 fulfill，不存在并发写同一份共享资源的路径。
  fullyParallel: true,

  // 显式关掉重试：截图基建要的是确定性。开着重试，「非 0 退出并点名 URL」这类消融证据
  // 会变成一条闪烁的日志——第一次失败、第二次侥幸通过，于是没人再看它。
  // 字体闸门此前有约 1/9 的假红（P2-2），修的是竞态本身（有界轮询等 @font-face 落定），
  // 而不是靠重试把红抹掉——重试会让「真的没加载」也变得可以侥幸通过。
  retries: 0,

  // 只留行式报告：HTML 报告是需要在浏览器里打开的应用，与「可重新生成的证据」无关。
  reporter: [['list']],

  outputDir: PLAYWRIGHT_OUTPUT_DIR,

  timeout: 60_000,

  expect: {
    // 断言轮询上界；与 e2e/support/assertions 用同一个常量，两处不各自定义。
    timeout: RENDER_SETTLE_TIMEOUT_MS,
  },

  use: {
    baseURL: BASE_URL,
    // 三种产物都关掉：截图由本基建自己截并自算哈希，trace/video 只会往产物目录塞
    // 不可复现的二进制，与「产物只含 PNG + manifest」的承诺冲突。
    trace: 'off',
    screenshot: 'off',
    video: 'off',
    // 中文界面依赖系统字体回退；固定 locale 与 timezone 让「相对时间」与「M月D日」
    // 这类文案不随机器区域设置漂移。
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    deviceScaleFactor: DEVICE_SCALE_FACTOR,
  },

  projects: [
    {
      // 截图入口的两条 project（外加汇总用的 manifest）。
      //
      // 为什么用 testMatch 而不是靠命令行传文件名（2026-10-07 实测的坑）：manifest
      // project 声明了 `dependencies: ['mobile', 'desktop']`，因此**只要它的用例被选中，
      // 两个视口 project 就会连带把各自目录下的全部 spec 都跑一遍**——实测
      // `playwright test shots.spec.ts manifest.spec.ts` 收集到的是 43 条（含 content.spec.ts
      // 的 20 条），而不是预期的 21 条。那样内容断言一红又会挡住截图，拆分就白做了。
      // 把「哪个 project 跑哪些 spec」写进配置，才能让 `pnpm shots` 与 `pnpm e2e` 真的互不牵连。
      name: 'mobile',
      testMatch: /(shots|guard-nonvacuity)\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: VIEWPORTS.mobile, deviceScaleFactor: DEVICE_SCALE_FACTOR },
    },
    {
      name: 'desktop',
      testMatch: /(shots|guard-nonvacuity)\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: VIEWPORTS.desktop, deviceScaleFactor: DEVICE_SCALE_FACTOR },
    },
    {
      // 内容断言入口（`pnpm e2e`）：两条 project 各自对应一个视口，与截图保持同一组视口，
      // 避免「截图看的视口」与「断言验的视口」不一致。
      name: 'content-mobile',
      testMatch: /(content|ui-interactions)\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: VIEWPORTS.mobile, deviceScaleFactor: DEVICE_SCALE_FACTOR },
    },
    {
      name: 'content-desktop',
      testMatch: /(content|ui-interactions)\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: VIEWPORTS.desktop, deviceScaleFactor: DEVICE_SCALE_FACTOR },
    },
    {
      // 汇总与复算必须在两个截图 project 都跑完之后执行，因此用 dependencies 而不是
      // globalTeardown：后者的失败只被记成「清理期间的错误」，诊断价值低，且它拿不到
      // 用例级的失败上下文。
      name: 'manifest',
      testMatch: /manifest\.spec\.ts/,
      dependencies: ['mobile', 'desktop'],
    },
    {
      // 关键状态图的核对（`pnpm e2e` 的最后一步）：交互态由两条内容断言 project 各自截，
      // 核对必须等它们都写完，故同样用 dependencies。
      //
      // 文件名刻意不叫 `states-manifest.spec.ts`：manifest project 的 testMatch 是
      // `/manifest\.spec\.ts/`，那个名字会被它一并收走，于是 `pnpm shots` 会去核对
      // 一份只属于 `pnpm e2e` 的产物（实测过的连带行为，与上面 testMatch 注释同源）。
      name: 'states-manifest',
      testMatch: /states\.spec\.ts/,
      dependencies: ['content-mobile', 'content-desktop'],
    },
  ],

  webServer: {
    // 先构建再预览：截图对象是构建产物（裁决 B）。`pnpm build` 内含 sync-tokens、
    // tsc --noEmit、vite build 与契约样式断言，因此这一步顺带把构建门禁跑了一遍。
    command: `pnpm build && pnpm preview --port ${String(PREVIEW_PORT)} --strictPort --host 127.0.0.1`,
    url: BASE_URL,
    // 不复用既有服务器：本机若残留一个用旧产物起的 4173，复用它会让截图对应到上一份 dist，
    // 「截图对应本次构建产物」这条证据就断了。
    reuseExistingServer: false,
    timeout: WEB_SERVER_TIMEOUT_MS,
    // 构建输出要出现在运行日志里：报告要贴 dist 的产物名与 mtime 作为一致性证据。
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
