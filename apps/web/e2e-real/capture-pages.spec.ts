/**
 * 模块: e2e-real/capture-pages
 * 职责: 用 Playwright 复刻原 `marketing/promo-shotcraft/capture/` 里**真正被影片消费**的两个量取能力，
 *       产出与 `src/page-metrics.json` / `src/element-metrics.json` **同形状**的 JSON。
 *
 * 为什么在 `e2e-real/` 而不是 `e2e/`
 *
 *   它量的是**真实数据渲染后**的页面几何。`apps/web/e2e/`（`pnpm shots`）用 mock 夹具、免后端；
 *   而这两个量取的输入是「真 SuperTokens 会话 + 真后端 + 真库里的种子数据」，量出的高度随内容变化
 *   （影片的滚动量就是靠它随内容自动跟随）。⇒ 它属于本目录这套「真实依赖探针」装置。
 *
 * 被复刻的两个能力（原脚本）
 *
 *   1. `capture/measure-page-metrics.mjs` → `src/page-metrics.json`
 *      home / emergencyQ1 / profile / cases 四页的滚动容器 `scrollHeight` / `clientHeight` / `maxScroll`；
 *   2. `capture/measure-element-positions.mjs` → `src/element-metrics.json`
 *      cases 页「内部」「虚构样例」两个状态标 + profile 页「待确认」分组的 `offsetTop` / `ratio` / `scrollPx`。
 *
 * ⚠ 视口口径（**按原脚本，不是字面上的 390×844**）
 *
 *   原脚本 `page.setViewport({width: 1280, height: 1000})`，并注明「视口宽度必须 ≥560，否则产品外壳
 *   媒体查询不命中」。390×844 是**外壳内的屏幕区尺寸**（`global.css` 的 `--device-screen-width/height`），
 *   在 ≥560px 视口下由 `.device-screen` 承载，其 `clientHeight` 恰为 844——这正是 `page-metrics.json`
 *   里四个 `clientHeight` 全是 844 的原因。若真用 390×844 的**浏览器**视口，三层外壳退化为
 *   `display: contents`、滚动落到 `body`，量出的就是另一组数。⇒ 必须复刻 1280×1000。
 *
 * ⚠ 账号：本文件**不注册**，它用一个**已存在**的真实账号登录
 *
 *   原因不是偷懒：`page-metrics.json` / `element-metrics.json` 的数值取决于该账号在真库里的数据
 *   （影片用的是文档化的演示账号 `demo-parent`：支持对象「小满」含一条 `ai_inference` 候选 ⇒ 才存在
 *   「待确认」分组；案例库 4 条含 1 条 `fictional`）。新注册账号的档案是空的，「待确认」分组根本不存在
 *   ⇒ 量不出 pendingGroup，而 `src/lib/pageScroll.ts` 的 `markScrollPx` 对缺失 key 返回 0（静默降级成「不滚动」）。
 *   因此缺账号时本文件**失败**，不去写一份会读坏影片的 JSON。
 *
 *   | 变量 | 含义 | 默认 |
 *   | --- | --- | --- |
 *   | `T10_CAPTURE_ACCOUNT` | 采集用账号名 | `demo-parent`（与原 `capture/account.mjs` 一致） |
 *   | `T10_CAPTURE_PASSWORD` | 该账号口令（**不入库**，同原 `account.mjs` 的纪律） | 空 ⇒ 显式失败 |
 *   | `T10_CAPTURE_OUT` | 产物目录（**相对路径按 cwd 解析**，见下） | `<T10_OUT>/capture` |
 *
 *   ⚠ `T10_CAPTURE_OUT` 的相对路径由 `node:path.resolve` 按 **cwd** 解析，而用
 *   `pnpm --filter/--dir @campfire/web exec playwright …` 跑时 cwd 是 **`apps/web`**——
 *   写 `.tmp/X` 会落到 `apps/web/.tmp/X`（那是仓库根的 `.tmp/` 之外，虽然同样被 gitignore）。
 *   要指到影片真源就用 `resolve` 出来的形式，例如
 *   `T10_CAPTURE_OUT=E:/Project/Web_Development/Campfire-AI/marketing/promo-shotcraft/src`
 *   （或从仓库根以 `--dir apps/web` 等价方式明确 cwd），**不要**写相对的 `marketing/...`。
 *
 *   不消耗邀请码：本文件只登录、不注册 ⇒ 它与 `README.md` §4 的码池下标表**无耦合**，不会挤占
 *   `t10-real.spec.ts` 的下标 0（`ablation.spec.ts` / `control.spec.ts` 原本占 1～4，
 *   两者已于 2026-10-08 按用户裁决删除）。
 *
 * 真实性纪律：本文件**不调用任何 `page.route`**（本目录的定义性约束，见 README §7）。
 *
 * 运行：
 *   pnpm --filter @campfire/web exec playwright test \
 *     --config e2e-real/playwright.real.config.ts --grep "@capture" --reporter=list
 *
 * 刷新影片真源（本文件**不**默认写 `marketing/`，那一步由人执行——写入编外目录属于删除/接管决策）：
 *   T10_CAPTURE_OUT=<绝对路径>/marketing/promo-shotcraft/src … --grep "@capture"
 */

import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

import { test, expect, type BrowserContext, type Page } from '@playwright/test';

import { BASE_URL, OUT_DIR, waitMounted } from './support/real';

/**
 * 产物目录。
 *
 * 默认落在 `<T10_OUT>/capture` 而不是直接覆盖 `marketing/promo-shotcraft/src/*.json`：
 * 本目录的纪律是「只写 `.tmp/T10`」（见 `support/real.ts` 的 `OUT_DIR`），越界去写影片源码会让
 * 「跑一次探针」变成一次未申报的产物变更。要刷新真源时用 `T10_CAPTURE_OUT` 显式指过去。
 */
const CAPTURE_OUT = (() => {
  const override = process.env.T10_CAPTURE_OUT?.trim() ?? '';
  return override === '' ? resolve(OUT_DIR, 'capture') : resolve(override);
})();

/** 采集用账号名（与原 `capture/account.mjs` 的 `DEFAULT_ACCOUNT_NAME` 同值）。 */
const ACCOUNT = process.env.T10_CAPTURE_ACCOUNT?.trim() ?? 'demo-parent';

/** 采集用口令：只来自环境变量，**没有缺省值**（原 `account.mjs` 的同一纪律）。 */
const PASSWORD = process.env.T10_CAPTURE_PASSWORD ?? '';

/**
 * 外壳屏幕区高（逻辑 px）。
 *
 * 它是 `global.css` 的 `--device-screen-height: 844px`，也是原脚本里硬编码进 `844 * 0.25` 与
 * `844 * 0.18` 的那个数。抽成常量：它同时是「视口口径对不对」的判据（见 `measureScroller` 的
 * `clientHeight` 断言）——若外壳媒体查询没命中，这个断言会先红，而不是安静地量出另一组数。
 */
const DEVICE_SCREEN_HEIGHT = 844;

/** 案例库状态标滚到「屏幕上方 1/4」的落点比例（原脚本的 `844 * 0.25`）。 */
const CASES_MARK_TOP_RATIO = 0.25;

/** 档案页「待确认」分组滚到「屏幕上方 18%」的落点比例（原脚本的 `844 * 0.18`）。 */
const PROFILE_MARK_TOP_RATIO = 0.18;

/** 影片消费的四个页面（键名与 `page-metrics.json` 逐字一致，不得改名）。 */
const PAGES: Readonly<Record<PageMetricKey, string>> = {
  home: '/',
  emergencyQ1: '/consult/emergency',
  profile: '/profile',
  cases: '/cases',
};

/** `page-metrics.json` 的页键。 */
type PageMetricKey = 'home' | 'emergencyQ1' | 'profile' | 'cases';

/** 一整页的滚动读数（形状照 `page-metrics.json`）。 */
interface PageMetric {
  readonly selector: string;
  readonly scrollHeight: number;
  readonly clientHeight: number;
  readonly maxScroll: number;
}

/** 一个关键元素的落点读数（形状照 `element-metrics.json` 的单个 mark）。 */
interface MarkMetric {
  readonly offsetTop: number;
  readonly ratio: number;
  readonly scrollPx: number;
}

/** `element-metrics.json` 的形状。 */
interface ElementMetrics {
  readonly cases: { readonly maxScroll: number; readonly marks: Record<string, MarkMetric> };
  readonly profile: { readonly maxScroll: number; readonly marks: Record<string, MarkMetric> };
}

/**
 * 把一份产物按 `support/real.ts:saveLog` **逐字相同的序列化**落盘（2 空格缩进 + 结尾换行）。
 *
 * 为什么不用 `saveLog`：它把落点硬绑到 `OUT_DIR`，而本文件需要「指到影片真源」的显式出口
 * （`T10_CAPTURE_OUT`），且要写的两份 JSON 不是 `ProbeLog.entries` 那样的「一轮观察汇总」。
 * 序列化形式刻意与它一致——影片侧的 `JSON.parse` 不受缩进影响，但**逐字一致**让
 * 「新产物与旧产物是否只是数值差异」这件事可以直接用 diff 判定。
 */
async function saveJson(value: unknown, name: string): Promise<string> {
  await mkdir(CAPTURE_OUT, { recursive: true });
  const path = resolve(CAPTURE_OUT, `${name}.json`);
  await writeFile(path, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  return path;
}

/**
 * 等到「字体就绪 + 静置 ms」——原脚本 `settle()` 的等价物。
 *
 * 字体就绪是必须的：字形未定时行高与折行都可能变，量出的 `scrollHeight` 会偏小，而影片的滚动量
 * 直接建立在这个数上。`document.fonts.ready` 本身不可序列化，故在页面里 `then` 成一个布尔量再返回
 * ——直接 `page.evaluate(() => document.fonts.ready)` 会在返回值序列化那一步失败。
 *
 * 静置延时保留原脚本的取值（700 / 1800 / 2500 …）：这是**内容驱动**的等待（档案页取数、案例库检索
 * 落地都在网络空闲之后仍有 React 渲染尾巴），不是「等一个固定东西出现」能替代的。
 */
async function settle(page: Page, ms: number): Promise<void> {
  await page.evaluate(() => document.fonts.ready.then(() => true));
  await page.waitForTimeout(ms);
}

/**
 * 找页面里真正的滚动容器并读数——**逐字复刻** `measure-page-metrics.mjs` 的 `measure()`。
 *
 * 候选顺序 `.device-screen` → `.phone-shell` → `body` 与原脚本一致；「溢出」的判据是
 * `scrollHeight > clientHeight + 8`（8px 容差，滤掉亚像素与滚动条抖动造成的伪溢出）。
 * 都不溢出时回一个 `'.device-screen(fallback)'` 的结果（便于确认「这页本来就不需要滚动」）。
 *
 * 返回值含 `selector`：它让「量到的是哪个容器」这件事本身成为可复核的证据，
 * 而不是只看三个数。
 */
function measureScroller(): PageMetric {
  const candidates = ['.device-screen', '.phone-shell', 'body'];
  for (const selector of candidates) {
    const element = document.querySelector(selector);
    if (element === null) continue;
    const scrollHeight = element.scrollHeight;
    const clientHeight = element.clientHeight;
    if (scrollHeight > clientHeight + 8) {
      return { selector, scrollHeight, clientHeight, maxScroll: scrollHeight - clientHeight };
    }
  }
  const fallback = document.querySelector('.device-screen') ?? document.body;
  return {
    selector: '.device-screen(fallback)',
    scrollHeight: fallback.scrollHeight,
    clientHeight: fallback.clientHeight,
    maxScroll: Math.max(0, fallback.scrollHeight - fallback.clientHeight),
  };
}

/**
 * cases 页：量「内部」「虚构样例」两个状态标，换算成滚动落点——复刻原脚本的 `out.cases` 段。
 *
 * 与原脚本一致的两处口径（不是随手写的）：
 *   - 选择器 `.tag, .status, [class*="tag"]` 后按 `textContent` 精确匹配「内部」/「虚构样例」，
 *     取**第一个**命中的元素（`marks[t] === undefined` 才写）——页面里同名的状态标可能有多处；
 *   - `offsetTop` 用「相对滚动容器内容坐标系」：`rect.top - scrollerRect.top + scroller.scrollTop`。
 *     它对当前 `scrollTop` **不敏感**（滚动时 rect.top 与 scrollTop 等量反向变化），因此无需先归零。
 *
 * `.device-screen` 不存在时返回 `null`（而不是让原脚本那样 `null.scrollHeight` 抛 TypeError）：
 * 失败信息要说清「是视口口径没命中外壳，不是页面缺陷」。
 */
function measureCaseMarks(options: {
  screenHeight: number;
  topRatio: number;
}): { maxScroll: number; marks: Record<string, MarkMetric> } | null {
  const scroller = document.querySelector('.device-screen');
  if (scroller === null) return null;
  const scrollerRect = scroller.getBoundingClientRect();
  const maxScroll = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
  const offsetTops: Record<string, number> = {};

  for (const element of Array.from(document.querySelectorAll('.tag, .status, [class*="tag"]'))) {
    const text = (element.textContent ?? '').trim();
    if (text !== '虚构样例' && text !== '内部') continue;
    if (offsetTops[text] !== undefined) continue;
    const rect = element.getBoundingClientRect();
    offsetTops[text] = Math.round(rect.top - scrollerRect.top + scroller.scrollTop);
  }

  const marks: Record<string, MarkMetric> = {};
  for (const [text, offsetTop] of Object.entries(offsetTops)) {
    // 「希望该元素滚到屏幕上方 1/4 处」⇒ 滚动量 = offsetTop - 屏高 × 比例（原脚本注释里的同一意图）。
    const target = Math.max(0, offsetTop - options.screenHeight * options.topRatio);
    marks[text] = {
      offsetTop,
      ratio: maxScroll === 0 ? 0 : Math.min(1, target / maxScroll),
      scrollPx: Math.round(Math.min(maxScroll, target)),
    };
  }
  return { maxScroll, marks };
}

/**
 * profile 页：量「待确认」分组——复刻原脚本的 `out.profile` 段。
 *
 * 判据是 `details.group-collapse` 的 `summary` 文本**包含**「待确认」（实际文案是「待确认（N）」，
 * 故不能用精确等于）。多个同名前缀分组时取**最后一个**：与原脚本的赋值语义一致（它每次命中都覆盖
 * `res.marks.pendingGroup`，循环结束后留下的是最后一个）。
 */
function measurePendingGroup(options: {
  screenHeight: number;
  topRatio: number;
}): { maxScroll: number; marks: Record<string, MarkMetric> } | null {
  const scroller = document.querySelector('.device-screen');
  if (scroller === null) return null;
  const scrollerRect = scroller.getBoundingClientRect();
  const maxScroll = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
  const marks: Record<string, MarkMetric> = {};

  for (const group of Array.from(document.querySelectorAll('details.group-collapse'))) {
    const summary = group.querySelector('summary');
    const text = (summary?.textContent ?? '').trim();
    if (!text.includes('待确认')) continue;
    const rect = group.getBoundingClientRect();
    const offsetTop = Math.round(rect.top - scrollerRect.top + scroller.scrollTop);
    const target = Math.max(0, offsetTop - options.screenHeight * options.topRatio);
    // 刻意覆盖而不是「首个胜出」：与原脚本的赋值语义逐字一致（见函数说明）。
    marks.pendingGroup = {
      offsetTop,
      scrollPx: Math.round(Math.min(maxScroll, target)),
      ratio: maxScroll === 0 ? 0 : Math.min(1, target / maxScroll),
    };
  }
  return { maxScroll, marks };
}

/** 登录状态（beforeAll 建立，两个用例共用）。 */
const SESSION = { ready: false };
let context: BrowserContext;

/**
 * 建立真实会话：在 `/login` 上走**真实 UI** 填表提交。
 *
 * 为什么不直接 `fetch('/api/auth/signup')`：原脚本走的就是 UI 登录，且 UI 路径同时覆盖了
 * 「SDK 已 init、anti-CSRF 头已注入、cookie 已落地」这几件真实性事实。失败时把页面上的错误卡文案
 * 一并抛出来——只说「没跳转」会把「口令不对」和「后端 500」混成一件事。
 */
async function loginReal(page: Page): Promise<void> {
  // 口令缺失先显式失败：否则会走到「填一个空密码 → 提交 → 停在 /login」，
  // 报出来的是超时，而真正的原因是夹具没配。原 `account.mjs` 的同一纪律（缺了不静默降级）。
  expect(
    PASSWORD,
    '必须提供 T10_CAPTURE_PASSWORD（采集账号口令）：本文件用一个**已存在**的真实账号登录，' +
      '不注册、不消耗邀请码。口令不入库（原 capture/account.mjs 的纪律），因此只能由环境变量提供。',
  ).not.toBe('');
  await page.goto(`${BASE_URL}/login`);
  await waitMounted(page);
  await page.fill('#auth-account', ACCOUNT);
  await page.fill('#auth-password', PASSWORD);
  await page.locator('button[type="submit"]').click();
  try {
    await expect(page).toHaveURL(`${BASE_URL}/`, { timeout: 45_000 });
  } catch (error) {
    const failure = await page
      .locator('.error-card')
      .first()
      .innerText()
      .catch(() => '(页面上没有错误卡)');
    throw new Error(
      `采集账号登录失败（账号 ${ACCOUNT}）：请确认 T10_CAPTURE_PASSWORD 正确、后端与真库在跑。` +
        `页面错误卡文案：${failure.replaceAll('\n', ' ')}`,
      { cause: error },
    );
  }
  await expect(page.locator('.tab-bar')).toBeVisible({ timeout: 20_000 });
}

test.beforeAll(async ({ browser }) => {
  // 视口必须 1280×1000：宽度 ≥560 才命中外壳媒体查询，高度 1000（>915px 缩放档上界）保证 zoom=1、
  // 屏幕区恰为 844。两处都是原脚本的取值，理由见文件头「视口口径」。
  context = await browser.newContext({
    baseURL: BASE_URL,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    viewport: { width: 1280, height: 1000 },
  });
  const page = await context.newPage();
  try {
    await loginReal(page);
    SESSION.ready = true;
  } finally {
    await page.close();
  }
});

test.afterAll(async () => {
  await context.close();
});

/**
 * 前置检查：真实会话已建立。
 *
 * 没有它的话，未登录时后面每个页面都会被 `RequireSession` 转到 `/login`，而登录页同样有
 * `.device-screen` 与 `.phone-shell` ⇒ 会**量到登录页的高度并当成产品页的读数**：
 * 一份形状正确、数值全错的产物，正是最难发现的那类坏。显式失败比那种假绿好。
 */
function requireSession(): void {
  expect(
    SESSION.ready,
    '真实会话未建立（beforeAll 的登录失败）：后续页面会被守卫转到 /login，量到的将是登录页——显式失败',
  ).toBe(true);
}

test.describe('@capture 页面量取（复刻 measure-page-metrics / measure-element-positions）', () => {
  test('page-metrics：四页滚动容器 scrollHeight/clientHeight/maxScroll', async () => {
    test.setTimeout(180_000);
    requireSession();
    const page = await context.newPage();
    try {
      await page.setViewportSize({ width: 1280, height: 1000 });
      const metrics: Record<string, PageMetric> = {};

      for (const [key, url] of Object.entries(PAGES)) {
        await page.goto(`${BASE_URL}${url}`, { waitUntil: 'networkidle' });
        // 档案页要多等一段（取数完成后仍有渲染尾巴）——原脚本对 profile 额外 settle 1500ms。
        await settle(page, key === 'profile' ? 3300 : 1800);
        metrics[key] = await page.evaluate(measureScroller);
      }

      const path = await saveJson(metrics, 'page-metrics');

      // ── 判据 1：外壳媒体查询命中（否则量的是 body，数不可比）────────────────
      for (const [key, metric] of Object.entries(metrics)) {
        expect(
          metric.clientHeight,
          `${key} 的滚动容器 ${metric.selector} 的 clientHeight=${String(metric.clientHeight)}，` +
            `期望 ${String(DEVICE_SCREEN_HEIGHT)}（.device-screen）⇒ 外壳媒体查询没命中：` +
            `视口宽度必须 ≥560（原脚本口径 1280×1000），否则三层外壳退化为 display:contents、滚动落到 body`,
        ).toBe(DEVICE_SCREEN_HEIGHT);
      }

      // ── 判据 2：三数自洽（防止读数被写坏成形状对、语义错的产物）────────────
      for (const [key, metric] of Object.entries(metrics)) {
        expect(metric.scrollHeight, `${key}：scrollHeight < clientHeight`).toBeGreaterThanOrEqual(metric.clientHeight);
        expect(
          metric.maxScroll,
          `${key}：maxScroll ≠ scrollHeight - clientHeight`,
        ).toBe(metric.scrollHeight - metric.clientHeight);
      }

      // ── 判据 3：四个键齐备且键名与影片消费方逐字一致（缺一个 ⇒ maxScrollOf 返回 0 静默不滚动）──
      //
      // 逐个断言而不是「排序后比对数组」：`toSorted()` 需要 ES2023 的 lib（本包 tsconfig 是 ES2022），
      // 而 `sort()` 会被 `unicorn/no-array-sort` 拦下（它会原地改写入参）。逐个比对同时给出更准确的
      // 失败信息——说清是哪一个键缺失。
      const keys = Object.keys(metrics);
      expect(keys, `页键数量与 page-metrics.json 不一致；产物：${path}`).toHaveLength(4);
      for (const key of ['home', 'emergencyQ1', 'profile', 'cases'] satisfies PageMetricKey[]) {
        expect(keys, `页键「${key}」缺失：影片的 maxScrollOf('${key}') 会静默返回 0；产物：${path}`).toContain(key);
      }
    } finally {
      await page.close();
    }
  });

  test('element-metrics：cases 两个状态标 + profile 待确认分组的位置与滚动落点', async () => {
    test.setTimeout(180_000);
    requireSession();
    const page = await context.newPage();
    try {
      await page.setViewportSize({ width: 1280, height: 1000 });

      // ── 案例库：虚构样例 / 内部 两个状态标 ──────────────────────────────
      await page.goto(`${BASE_URL}/cases`, { waitUntil: 'networkidle' });
      await settle(page, 2000);
      const cases = await page.evaluate(measureCaseMarks, {
        screenHeight: DEVICE_SCREEN_HEIGHT,
        topRatio: CASES_MARK_TOP_RATIO,
      });
      expect(
        cases,
        'cases 页找不到 .device-screen ⇒ 外壳媒体查询没命中（视口宽度必须 ≥560），量取口径不成立',
      ).not.toBeNull();
      if (cases === null) throw new Error('unreachable：上面已断言非 null');

      // ── 档案页：待确认分组 ────────────────────────────────────────────
      await page.goto(`${BASE_URL}/profile`, { waitUntil: 'networkidle' });
      await settle(page, 2500);
      const profile = await page.evaluate(measurePendingGroup, {
        screenHeight: DEVICE_SCREEN_HEIGHT,
        topRatio: PROFILE_MARK_TOP_RATIO,
      });
      expect(profile, 'profile 页找不到 .device-screen ⇒ 量取口径不成立').not.toBeNull();
      if (profile === null) throw new Error('unreachable：上面已断言非 null');

      const metrics: ElementMetrics = { cases, profile };
      const path = await saveJson(metrics, 'element-metrics');

      // ── 判据：三个 mark 都必须真的量到 ──────────────────────────────────
      //
      // 这一条不是「形式要求」：`src/lib/pageScroll.ts` 的 `markScrollPx` / `markOffsetTop` 对缺失的
      // mark 返回 0（`?? 0`）⇒ 缺项不会报错，只会让影片**该滚的镜头不滚**。若这里静默放行，
      // 就等于产出一份「看着有、实际读坏」的 JSON。缺项时如实失败，并说清是夹具前提不成立。
      for (const mark of ['虚构样例', '内部']) {
        expect(
          cases.marks[mark],
          `cases 页没量到状态标「${mark}」：账号 ${ACCOUNT} 下案例库必须含对应状态的真实条目` +
            `（原影片用演示种子数据：1 条 fictional + 3 条 internal）。这**不是**产品缺陷，是夹具前提不成立；` +
            `不得放宽断言（缺项会让 markScrollPx 返回 0、影片该滚的镜头不滚）。实测 marks：${JSON.stringify(cases.marks)}；产物：${path}`,
        ).toBeDefined();
      }
      expect(
        profile.marks['pendingGroup'],
        `profile 页没量到「待确认」分组（details.group-collapse 的 summary 含「待确认」）：账号 ${ACCOUNT} ` +
          `下必须有至少一条 origin 为 ai_inference / system_observation 的候选条目——它**只由 Worker 写入路径产生**，` +
          `产品的「补充一条」入口恒为 user_statement（confirmed），因此空账号量不出这一项。` +
          `这**不是**产品缺陷，是夹具前提不成立；不得放宽断言（缺项会让 markScrollPx 返回 0）。` +
          `实测 marks：${JSON.stringify(profile.marks)}；产物：${path}`,
      ).toBeDefined();

      // ── 判据：maxScroll > 0 才有「滚动」可言 ─────────────────────────────
      // maxScroll === 0 时 ratio 恒为 0（原脚本的三元分支）⇒ 产物数值全部退化为 0，
      // 那是「这页没有内容」而不是「量过了」。
      expect(cases.maxScroll, `cases 页 maxScroll=0：没有可滚动内容，位置量取退化为常数 0`).toBeGreaterThan(0);
      expect(
        profile.maxScroll,
        `profile 页 maxScroll=0：账号 ${ACCOUNT} 的档案页没有内容（原影片的档案页 maxScroll 约 4194）`,
      ).toBeGreaterThan(0);
    } finally {
      await page.close();
    }
  });
});
