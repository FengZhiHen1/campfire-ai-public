/**
 * 模块: e2e-real/t10-real
 * 职责: T10 七条链路的真实依赖端到端探针——真浏览器 + 真 Vite 代理 + 真 FastAPI + 真 SuperTokens 会话
 *
 * ⚠ **需要真实栈**（见 support/real.ts 的文件头）。本目录不被 `pnpm shots` 的
 * playwright.config.ts（testDir=./e2e）收集，也没有任何 test.skip 静默降级：
 * 环境缺失时它**失败**，不假装通过。
 *
 * 真实性纪律（本文件最重要的约束）
 *
 *   本文件**不调用任何 `page.route(...)`**，因此不存在 `route.fulfill` 兜底的可能。
 *   每个 `/api/**` 请求都由浏览器发到 http://localhost:5173，再经 Vite 的 server.proxy
 *   转到真实 uvicorn（127.0.0.1:8000）。证据是响应体里的真实 id（session_id / run_id /
 *   SuperTokens user id）与真实 HTTP 状态码，而不是「页面上出现了某个字符串」。
 *
 * 为什么所有用例共用一个 BrowserContext
 *
 *   链路 1 建立的真实 SuperTokens 会话必须被后续链路复用（否则每个用例都要重新登录，
 *   而登录本身又依赖链路 1 的证据）。默认为每个用例新建 context 会让 cookie 失联，
 *   于是后面测的其实是「未登录被重定向到登录页」——那是最坏的假绿。
 *   因此 beforeAll 建一个 context，各用例从它开 page，afterAll 关闭。
 *
 * 用例顺序刻意如此：真实模型调用（链路 3）排在链路 5/6/2/4 之后、链路 7 之前，
 * 这样它因外部原因失败时，其余证据已经落盘。
 */

import { mkdir } from 'node:fs/promises';

import { test, expect, type BrowserContext, type Page } from '@playwright/test';

import {
  BASE_URL,
  OUT_DIR,
  createLog,
  elementsPastViewportRight,
  freshAccount,
  freshPassword,
  inviteCodeFor,
  saveLog,
  sessionCookies,
  installSseTap,
  readSseTap,
  seedMemoryEpisode,
  sheetFocusFacts,
  tallyResponses,
  waitMounted,
  watchApi,
  watchConsole,
  type ApiTrace,
  type ConsoleRecord,
  type SheetFocusFacts,
} from './support/real';

const log = createLog();
const apiTrace: ApiTrace[] = [];
const records: ConsoleRecord[] = [];

const STAMP = Date.now();
const ACCOUNT = freshAccount(STAMP);
const PASSWORD = freshPassword(STAMP);
const INVITE = inviteCodeFor(0);

let context: BrowserContext;

/**
 * 开一个受观测的页面：挂上控制台采集与 API 观测。
 *
 * 采集器都只**观察**（page.on），不注册任何 route —— 请求照常从浏览器发出。
 * 两个采集器都写进程级数组，因此链路 7 的「全程」汇总覆盖每一个页面。
 */
async function openPage(): Promise<Page> {
  const page = await context.newPage();
  watchConsole(page, records);
  watchApi(page, apiTrace);
  return page;
}

/**
 * 前置检查：真实会话已在链路 1 建立。
 *
 * 后续链路全部依赖它。没有这个检查时，会话缺失表现为「页面被重定向到 /login」，
 * 于是链路 2 会去量登录页的外壳、链路 4 会去点不存在的按钮——**测错对象却可能报绿**
 * （登录页同样有 DeviceFrame 与外层结构）。显式失败比那种假绿好。
 */
function requireSession(): void {
  expect(
    API_ROUNDS.authenticated,
    '真实会话尚未建立（链路 1 未成功）：后续链路会在登录页上测错对象，因此显式失败',
  ).toBe(true);
}

/** 链路 1 成功后置为 true；供 requireSession 判定。 */
const API_ROUNDS = { authenticated: false };

/**
 * 链路 1 建立的真实账号标识（SuperTokens 的 user id）。
 *
 * 为什么要在模块级记它：记忆面的分区键是**登录态里的 user id**（`routes.py` 的
 * `current_account` → `session.get_user_id()`），而**不是**注册用的邮箱。
 * 记忆夹具必须往那张图里写，否则页面读的是另一张图、夹具等于没种。
 * 这与链路 1 的「JWT 的 sub 必须等于注册返回的 user id」是同一个标识。
 */
const SESSION = { accountId: '' };

test.beforeAll(async ({ browser }) => {
  await mkdir(`${OUT_DIR}/shots`, { recursive: true });
  context = await browser.newContext({
    baseURL: BASE_URL,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    viewport: { width: 1280, height: 1000 },
  });
});

test.afterAll(async () => {
  await context.close();
});

/**
 * 刻意**不用** serial 模式，尽管这些用例共享一个 context 与一批累积记录。
 *
 * 为什么：serial 模式下任何一条失败都会**跳过其余全部**，而本任务明确要求
 * 「不要因为一条失败就放弃其余证据」——尤其链路 3（真调模型，最可能因外部原因失败）
 * 不该把链路 7（控制台汇总）一起带走。
 *
 * 顺序仍由 `workers: 1` + 文件内声明顺序保证（链路 1 建立真实会话，后续复用）。
 * 这是有意的耦合，因此下面 `requireSession()` 会在会话缺失时**显式失败**，
 * 而不是让后续链路以「未登录被重定向」的形式静默测错对象。
 */
test.describe('@real T10 真实依赖端到端', () => {
  test('链路1 注册（真邀请码）+ 登录 + 登出（真 SuperTokens）', async () => {
    test.setTimeout(120_000);
    const page = await openPage();
    try {
      expect(INVITE, '必须提供真实邀请码（T10_INVITE_CODE）：没有它就不是真实注册').not.toBe('');

      await page.goto(`${BASE_URL}/login`);
      await waitMounted(page);

      await page.getByRole('button', { name: '已有邀请码？注册账号' }).click();
      await expect(page.locator('#auth-invite')).toBeVisible();

      await page.fill('#auth-account', ACCOUNT);
      await page.fill('#auth-password', PASSWORD);
      await page.fill('#auth-invite', INVITE);
      await page.locator('button[type="submit"]').click();

      await expect(page).toHaveURL(`${BASE_URL}/`, { timeout: 45_000 });
      await expect(page.locator('.tab-bar')).toBeVisible({ timeout: 20_000 });

      // ── 真实性判据 1：注册响应来自真后端，带真实 user id，且经 5173 代理 ──
      const signup = apiTrace.find((entry) => entry.url.includes('/api/auth/signup'));
      expect(signup, '浏览器里没有出现 /api/auth/signup 请求——注册没走真后端').toBeDefined();
      expect(signup?.status, `注册状态码不是 200：${JSON.stringify(signup)}`).toBe(200);
      expect(signup?.viaProxy, '注册请求必须打在 5173（经 Vite 代理到真后端）').toBe(true);
      const userId = /(?:^|\s)id=([0-9a-f-]{32,36})/.exec(signup?.bodyKeyIds.join(' ') ?? '')?.[1] ?? '';
      expect(userId, `注册响应体里没有真实 user id：${JSON.stringify(signup?.bodyKeyIds)}`).not.toBe('');

      // ── 真实性判据 2：真实 SuperTokens 会话 cookie（httpOnly）──────────
      const cookiesAfterRegister = await sessionCookies(context);
      const access = cookiesAfterRegister.find((cookie) => cookie.name === 'sAccessToken');
      const refresh = cookiesAfterRegister.find((cookie) => cookie.name === 'sRefreshToken');
      expect(access, '没有 sAccessToken：会话不是 SuperTokens 签发的').toBeDefined();
      expect(refresh, '没有 sRefreshToken：会话不是 SuperTokens 签发的').toBeDefined();
      expect(access?.httpOnly, 'access token 必须是 httpOnly cookie').toBe(true);

      // ── 真实性判据 3：access token 是可真解析的 JWT，签发者是真后端 ────
      // 只取子集字段落盘：完整载荷含 sessionHandle 与 refreshTokenHash1，
      // 那是凭据材料，不得进任何报告或日志（apps/web 的凭据纪律）。
      const rawAccess = (await context.cookies()).find((cookie) => cookie.name === 'sAccessToken')?.value ?? '';
      const decoded = Buffer.from(rawAccess.split('.')[1] ?? '', 'base64url').toString('utf8');
      const jwt = JSON.parse(decoded) as { iss?: string; sub?: string; tId?: string; exp?: number; iat?: number };
      const jwtSummary = { iss: jwt.iss, sub: jwt.sub, tId: jwt.tId, hasExp: typeof jwt.exp === 'number', hasIat: typeof jwt.iat === 'number' };
      expect(jwtSummary.iss, 'sAccessToken 不是可解析的 JWT').toContain('/api/auth');
      expect(jwtSummary.sub, 'JWT 的 sub 必须等于注册返回的 user id').toBe(userId);

      // ── 真实性判据 4：浏览器内直打受限端点，拿到真数据 ─────────────────
      const authed = await page.evaluate(async () => {
        const response = await fetch('/api/consult/sessions');
        return { status: response.status, body: await response.text(), url: response.url };
      });
      expect(authed.status, `受限端点应 200，实际 ${String(authed.status)}：${authed.body}`).toBe(200);
      expect(authed.url, '请求必须打在 5173 源上（经代理到真后端）').toContain('localhost:5173');
      expect(authed.body, '受限端点返回的不是会话列表 JSON').toMatch(/next_cursor/);

      // ── 登出：真 SuperTokens 会话被撤销 ────────────────────────────────
      await page.goto(`${BASE_URL}/settings`);
      await waitMounted(page);
      await page.getByRole('button', { name: '退出登录' }).click();
      await expect(page.locator('.confirm-sheet')).toBeVisible();
      await page.locator('.confirm-sheet').getByRole('button', { name: '退出', exact: true }).click();
      await expect(page).toHaveURL(`${BASE_URL}/login`, { timeout: 30_000 });

      const cookiesAfterLogout = await sessionCookies(context);
      expect(
        cookiesAfterLogout.some((cookie) => cookie.name === 'sAccessToken'),
        '登出后 sAccessToken 仍在：登出没走真 SuperTokens',
      ).toBe(false);

      // ── 再次登录（同一账号、真凭据）──────────────────────────────────
      await page.fill('#auth-account', ACCOUNT);
      await page.fill('#auth-password', PASSWORD);
      await page.locator('button[type="submit"]').click();
      await expect(page).toHaveURL(`${BASE_URL}/`, { timeout: 45_000 });

      const signin = apiTrace.find((entry) => entry.url.includes('/api/auth/signin'));
      expect(signin, '浏览器里没有出现 /api/auth/signin 请求').toBeDefined();
      expect(signin?.status, `登录状态码不是 200：${JSON.stringify(signin)}`).toBe(200);
      const cookiesAfterLogin = await sessionCookies(context);
      expect(cookiesAfterLogin.some((cookie) => cookie.name === 'sAccessToken'), '再次登录后没有 sAccessToken').toBe(true);

      // 真实会话已建立：放行后续链路的前置检查，并把分区键记下来（记忆夹具要用它）。
      API_ROUNDS.authenticated = true;
      SESSION.accountId = userId;

      log.record('link1-auth', {
        account: ACCOUNT,
        userId,
        signup: { status: signup?.status, viaProxy: signup?.viaProxy, bodyKeyIds: signup?.bodyKeyIds },
        signin: { status: signin?.status, url: signin?.url },
        cookiesAfterRegister,
        cookiesAfterLogout,
        cookiesAfterLogin,
        authedApi: { status: authed.status, url: authed.url, body: authed.body },
        jwtSummary,
      });
      log.record('consoleAfterLink1', [...records]);
      await saveLog(log, 't10-real-log');
    } finally {
      await page.close();
    }
  });

  test('链路6 四处硬文案已去句末标点', async () => {
    test.setTimeout(120_000);
    const page = await openPage();
    requireSession();
    const seen: Record<string, unknown> = {};
    try {
      await page.setViewportSize({ width: 390, height: 844 });

      // 处 1：会话列表页空态
      await page.goto(`${BASE_URL}/consult`);
      await waitMounted(page);
      await expect(page.getByText('还没有咨询记录')).toBeVisible({ timeout: 25_000 });
      seen['consultList.before'] = {
        visible: await page.getByText('从上面开始第一次咨询', { exact: true }).isVisible(),
        trailingPeriodVariantVisible: await page.getByText('从上面开始第一次咨询。', { exact: true }).isVisible().catch(() => false),
      };

      // 处 2：应急表单页跳过语义
      await page.goto(`${BASE_URL}/consult/emergency`);
      await waitMounted(page);
      await expect(page.getByText('跳过 = 未排除，不会当作正常', { exact: true })).toBeVisible({ timeout: 20_000 });
      seen['emergency.skipSemantics'] = {
        visible: true,
        trailingPeriodVariantVisible: await page
          .getByText('跳过 = 未排除，不会当作正常。', { exact: true })
          .isVisible()
          .catch(() => false),
      };

      // 处 3：记忆页空态
      await page.goto(`${BASE_URL}/settings/memory`);
      await waitMounted(page);
      await expect(page.getByText('还没有记录').first()).toBeVisible({ timeout: 25_000 });
      seen['memory.emptyDescription'] = {
        visible: await page.getByText('你在咨询中说过的事，会记在这里', { exact: true }).isVisible(),
        trailingPeriodVariantVisible: await page
          .getByText('你在咨询中说过的事，会记在这里。', { exact: true })
          .isVisible()
          .catch(() => false),
      };
      const memoryText = await page.locator('body').innerText();
      seen['memory.bodyHasTrailingPeriodVariant'] = memoryText.includes('你在咨询中说过的事，会记在这里。');

      // 处 4：档案页空态。**两处空态文案不同，必须先分清哪一处才谈得上逐字核对**：
      //   - 没有任何支持对象（objects.length === 0）⇒ noObjectDescription
      //     「先给 TA 起个称呼，之后咨询中说的相关事情会记在这里。」——**这句设计原文就带句号**，
      //     它不在本次改动的四处之列；
      //   - 有支持对象但没有任何条目（!hasEntries）⇒ emptyDescription
      //     「咨询中你说的关于 TA 的事，会自动记在这里；也可以现在补充一条」——**这句是本次去掉句末句号的**。
      // 全新账号落在前者，因此要真建一个对象才能看到后者。这里经页面自己的 fetch
      // （被 SDK 包装过 ⇒ 带 anti-CSRF 头）建对象，响应的真实 id 就是「数据真进了后端」的证据。
      await page.goto(`${BASE_URL}/profile`);
      await waitMounted(page);
      await expect(page.getByText('还没有记录').first()).toBeVisible({ timeout: 25_000 });
      seen['profile.noObjectDescription'] = {
        visible: await page
          .getByText('先给 TA 起个称呼，之后咨询中说的相关事情会记在这里。', { exact: true })
          .isVisible()
          .catch(() => false),
        // 设计原文带句号 ⇒ 这一处**应当**保留句号。记下来是为了证明我没有把「去掉句号」
        // 误扩到设计上本来带句号的那一句。
        note: '这句设计原文带句末句号，不属本次去标点的四处；此处如实记录它的存在。',
      };

      const seeded = await page.evaluate(async () => {
        const response = await fetch('/api/profile/objects', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ display_name: 'T10 文案核对对象' }),
        });
        const text = await response.text();
        return { status: response.status, id: (JSON.parse(text) as { id?: string }).id ?? '', body: text.slice(0, 300) };
      });
      expect(seeded.id, `建档对象失败（status=${String(seeded.status)}）：${seeded.body}`).toMatch(/^[0-9a-f-]{32,36}$/);

      await page.goto(`${BASE_URL}/profile`);
      await waitMounted(page);
      await expect(page.getByText('还没有记录').first()).toBeVisible({ timeout: 25_000 });
      const profileWithObjectText = await page.locator('body').innerText();
      seen['profile.seededObjectId'] = seeded.id;
      seen['profile.addEntryDescriptionWithoutPeriod'] = profileWithObjectText.includes(
        '咨询中你说的关于 TA 的事，会自动记在这里；也可以现在补充一条',
      );
      seen['profile.addEntryDescriptionWithPeriodPresent'] = profileWithObjectText.includes(
        '咨询中你说的关于 TA 的事，会自动记在这里；也可以现在补充一条。',
      );
      seen['profile.withObjectBodySample'] = profileWithObjectText.slice(0, 600);

      log.record('link6-hard-copy', seen);
      log.record('consoleAfterLink6', [...records]);
      await saveLog(log, 't10-real-log');

      // ── 断言：三处去标点的文案逐字可见，且带句号的旧形态不存在 ──────────
      expect(seen['consultList.before']).toMatchObject({ visible: true, trailingPeriodVariantVisible: false });
      expect(seen['emergency.skipSemantics']).toMatchObject({ trailingPeriodVariantVisible: false });
      expect(seen['memory.emptyDescription']).toMatchObject({ visible: true, trailingPeriodVariantVisible: false });
      expect(seen['memory.bodyHasTrailingPeriodVariant']).toBe(false);
      expect(seen['profile.addEntryDescriptionWithoutPeriod']).toBe(true);
      expect(seen['profile.addEntryDescriptionWithPeriodPresent']).toBe(false);
    } finally {
      await page.close();
    }
  });

  test('链路5 textarea 不再是 UA 默认样式', async () => {
    test.setTimeout(120_000);
    const page = await openPage();
    requireSession();
    try {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`${BASE_URL}/consult/emergency`);
      await waitMounted(page);

      // UA 默认基线：一个没有任何页面样式作用的 iframe 里的 textarea。
      // 同浏览器、同一次运行 ⇒ 可直接对比的负对照（不是硬编码的期望色值）。
      const uaDefault = await page.evaluate(() => {
        const frame = document.createElement('iframe');
        frame.style.cssText = 'position:absolute;left:-9999px;top:0;width:400px;height:200px';
        document.body.appendChild(frame);
        const doc = frame.contentDocument;
        if (doc === null) return null;
        const probe = doc.createElement('textarea');
        doc.body.appendChild(probe);
        const style = frame.contentWindow?.getComputedStyle(probe);
        const result =
          style === undefined || style === null
            ? null
            : {
                backgroundColor: style.backgroundColor,
                borderTopWidth: style.borderTopWidth,
                borderTopStyle: style.borderTopStyle,
                borderTopColor: style.borderTopColor,
                fontFamily: style.fontFamily,
                resize: style.resize,
                paddingTop: style.paddingTop,
              };
        frame.remove();
        return result;
      });
      expect(uaDefault, '无法构造 UA 默认 textarea 负对照').not.toBeNull();

      const readStyle = (selector: string): Promise<Record<string, string>> =>
        page.evaluate((sel: string) => {
          const element = document.querySelector(sel);
          if (element === null) return {} as Record<string, string>;
          const style = getComputedStyle(element);
          return {
            backgroundColor: style.backgroundColor,
            borderTopWidth: style.borderTopWidth,
            borderTopStyle: style.borderTopStyle,
            borderTopColor: style.borderTopColor,
            borderRadius: style.borderRadius,
            fontFamily: style.fontFamily,
            resize: style.resize,
            paddingTop: style.paddingTop,
            minHeight: style.minHeight,
            width: style.width,
          } satisfies Record<string, string>;
        }, selector);

      /**
       * 读出设计 token 的**计算值**（同一个浏览器解析，不硬编码色值）。
       *
       * 两个陷阱都在这里显式避开：
       *   1. 颜色要读 `color` 属性。`border-top-width` 在 UA 默认样式下**也是 1px**
       *      （UA 的 textarea 是 `1px solid`），拿它当「是否还是 UA 默认」的判据会得到
       *      「两者相同」——那是我第一版探针的缺陷，不是产品缺陷。
       *   2. `--radius-sm` 要直接 resolve 成字符串。把它写成 `border-top-width` 去读
       *      只能得到 0px：border-style 缺省为 none 时，used width 恒为 0。
       */
      const tokens = await page.evaluate(() => {
        const rootStyle = getComputedStyle(document.documentElement);
        const probe = document.createElement('div');
        probe.style.backgroundColor = 'var(--surface)';
        probe.style.borderTopColor = 'var(--border)';
        probe.style.borderTopStyle = 'solid';
        document.body.appendChild(probe);
        const computed = getComputedStyle(probe);
        const result = {
          surface: computed.backgroundColor,
          border: computed.borderTopColor,
          radiusSm: rootStyle.getPropertyValue('--radius-sm').trim(),
        };
        probe.remove();
        return result;
      });

      // 走到第 4 题（distress：allowNote=true 且 control='single' ⇒ #emergency-extra）
      for (let step = 0; step < 3; step += 1) await page.getByRole('button', { name: '下一题' }).click();
      await expect(page.locator('#emergency-extra')).toBeVisible({ timeout: 15_000 });
      const extraStyle = await readStyle('#emergency-extra');

      // 再走到第 6 题（what_happened：control='text' ⇒ #emergency-note）
      for (let step = 0; step < 2; step += 1) await page.getByRole('button', { name: '下一题' }).click();
      await expect(page.locator('#emergency-note')).toBeVisible({ timeout: 15_000 });
      const noteStyle = await readStyle('#emergency-note');

      await page.screenshot({ path: `${OUT_DIR}/shots/emergency-textarea-390.png`, fullPage: true });

      const checks = {
        // ── 正判据：真的应用了设计 token（这是「不再是 UA 默认」的充分证据）──
        'extra background is --surface': extraStyle['backgroundColor'] === tokens.surface,
        'note background is --surface': noteStyle['backgroundColor'] === tokens.surface,
        'extra border color is --border': extraStyle['borderTopColor'] === tokens.border,
        'note border color is --border': noteStyle['borderTopColor'] === tokens.border,
        'extra border radius is non-zero': parseFloat(extraStyle['borderRadius'] ?? '0') > 0,
        'note border radius is non-zero': parseFloat(noteStyle['borderRadius'] ?? '0') > 0,
        'extra padding is the design value (12px), not the UA value (2px)':
          extraStyle['paddingTop'] !== uaDefault?.paddingTop && extraStyle['paddingTop'] === '12px',
        'note padding is the design value (12px), not the UA value (2px)':
          noteStyle['paddingTop'] !== uaDefault?.paddingTop && noteStyle['paddingTop'] === '12px',
        'extra resize is the design value (vertical), not the UA value (both)':
          extraStyle['resize'] === 'vertical' && uaDefault?.resize === 'both',
        // ── 负判据：与 UA 默认基线在**可区分的**属性上确实不同 ──
        // 用 border-top-color（UA 是 rgb(118,118,118)）而不是 border-top-width
        // （UA 也是 1px ⇒ 比宽度会得到「相同」，那是个假判据）。
        'extra border color differs from UA baseline': extraStyle['borderTopColor'] !== uaDefault?.borderTopColor,
        'note border color differs from UA baseline': noteStyle['borderTopColor'] !== uaDefault?.borderTopColor,
        'extra background differs from UA baseline': extraStyle['backgroundColor'] !== uaDefault?.backgroundColor,
        'note background differs from UA baseline': noteStyle['backgroundColor'] !== uaDefault?.backgroundColor,
        'note font family differs from UA baseline (not monospace)':
          noteStyle['fontFamily'] !== uaDefault?.fontFamily && uaDefault?.fontFamily === 'monospace',
      };

      log.record('link5-textarea', {
        uaDefault,
        tokens,
        emergencyExtraStyle: extraStyle,
        emergencyNoteStyle: noteStyle,
        checks,
      });
      log.record('consoleAfterLink5', [...records]);
      await saveLog(log, 't10-real-log');

      for (const [label, ok] of Object.entries(checks)) {
        expect(ok, `textarea 判据未成立：${label}；实测 ${JSON.stringify({ uaDefault, tokens, extraStyle, noteStyle }, null, 1)}`).toBe(true);
      }
    } finally {
      await page.close();
    }
  });

  test('链路2 外壳几何（1280/768 有壳居中、390 无壳、.tab-bar 收在外壳内）', async () => {
    test.setTimeout(120_000);
    const page = await openPage();
    requireSession();
    try {
      const measure = (): Promise<Record<string, unknown>> =>
        page.evaluate(() => {
          type Rect = { left: number; top: number; width: number; height: number; right: number; bottom: number };
          const rectOf = (selector: string): Rect | null => {
            const element = document.querySelector(selector);
            if (element === null) return null;
            const rect = element.getBoundingClientRect();
            return { left: rect.left, top: rect.top, width: rect.width, height: rect.height, right: rect.right, bottom: rect.bottom };
          };
          const displayOf = (selector: string): string | null => {
            const element = document.querySelector(selector);
            return element === null ? null : getComputedStyle(element).display;
          };
          const device = rectOf('.device');
          const screen = rectOf('.device-screen');
          const tabBar = rectOf('.tab-bar');
          const deviceElement = document.querySelector('.device');
          return {
            viewport: { width: window.innerWidth, height: window.innerHeight },
            device,
            deviceDisplay: displayOf('.device'),
            deviceStageDisplay: displayOf('.device-stage'),
            deviceScreenDisplay: displayOf('.device-screen'),
            deviceScreen: screen,
            deviceZoom: deviceElement === null ? null : getComputedStyle(deviceElement).zoom,
            deviceBorderTopWidth: deviceElement === null ? null : getComputedStyle(deviceElement).borderTopWidth,
            tabBar,
            tabBarDisplay: displayOf('.tab-bar'),
            tabBarPosition: (() => {
              const element = document.querySelector('.tab-bar');
              return element === null ? null : getComputedStyle(element).position;
            })(),
            tabBarInsideDeviceScreen:
              tabBar !== null && screen !== null && screen.width > 0
                ? tabBar.left >= screen.left - 0.5 && tabBar.right <= screen.right + 0.5
                : null,
            tabBarBottomAlignedToScreen:
              tabBar !== null && screen !== null && screen.height > 0 ? Math.abs(tabBar.bottom - screen.bottom) <= 1.5 : null,
            tabItemCount: document.querySelectorAll('.tab-item').length,
            documentScrollWidth: document.documentElement.scrollWidth,
            documentClientWidth: document.documentElement.clientWidth,
            documentScrollHeight: document.documentElement.scrollHeight,
            documentClientHeight: document.documentElement.clientHeight,
            bodyScrollWidth: document.body.scrollWidth,
          };
        });

      const cases: Record<string, Record<string, unknown>> = {};
      const visit = async (width: number, height: number, key: string): Promise<void> => {
        await page.setViewportSize({ width, height });
        await page.goto(`${BASE_URL}/settings`);
        await waitMounted(page);
        await expect(page.locator('.tab-bar')).toBeVisible({ timeout: 20_000 });
        cases[key] = await measure();
        await page.screenshot({ path: `${OUT_DIR}/shots/shell-${key}.png` });
      };

      await visit(1280, 1000, '1280x1000');
      await visit(768, 1024, '768x1024');
      await visit(390, 844, '390x844');

      const wide = cases['1280x1000'] ?? {};
      const mid = cases['768x1024'] ?? {};
      const narrow = cases['390x844'] ?? {};
      const device1280 = wide['device'] as { width: number; left: number } | null;
      const device768 = mid['device'] as { width: number; left: number } | null;
      const device390 = narrow['device'] as { width: number; left: number } | null;
      const screen390 = narrow['deviceScreen'] as { width: number } | null;

      const expectations: Record<string, boolean> = {
        '1280 .device width ≈ 414': device1280 !== null && Math.abs(device1280.width - 414) <= 1,
        '1280 .device horizontally centered': device1280 !== null && Math.abs(device1280.left - (1280 - device1280.width) / 2) <= 1,
        '768 .device width ≈ 414': device768 !== null && Math.abs(device768.width - 414) <= 1,
        '768 .device horizontally centered': device768 !== null && Math.abs(device768.left - (768 - device768.width) / 2) <= 1,
        '390 .device degenerates to display:contents': narrow['deviceDisplay'] === 'contents',
        '390 .device-stage degenerates to display:contents': narrow['deviceStageDisplay'] === 'contents',
        '390 .device-screen degenerates to display:contents': narrow['deviceScreenDisplay'] === 'contents',
        '390 .device box width is 0': device390 !== null && device390.width === 0,
        '390 no bezel (device-screen width 0)': screen390 !== null && screen390.width === 0,
        '390 no document-level horizontal overflow':
          (narrow['documentScrollWidth'] as number) <= (narrow['documentClientWidth'] as number) + 1,
        '1280 .tab-bar inside .device-screen': wide['tabBarInsideDeviceScreen'] === true,
        '768 .tab-bar inside .device-screen': mid['tabBarInsideDeviceScreen'] === true,
        '1280 .tab-bar bottom aligned to shell bottom': wide['tabBarBottomAlignedToScreen'] === true,
        '768 .tab-bar bottom aligned to shell bottom': mid['tabBarBottomAlignedToScreen'] === true,
        '4 tab items in all three viewports':
          (wide['tabItemCount'] as number) === 4 && (mid['tabItemCount'] as number) === 4 && (narrow['tabItemCount'] as number) === 4,
      };

      log.record('link2-shell-geometry', { cases, expectations });
      log.record('consoleAfterLink2', [...records]);
      await saveLog(log, 't10-real-log');

      for (const [label, ok] of Object.entries(expectations)) {
        expect(ok, `外壳几何判据未成立：${label}；实测 ${JSON.stringify(cases, null, 1)}`).toBe(true);
      }
    } finally {
      await page.close();
    }
  });

  test('链路4 确认单 5 处全覆盖（焦点进入 / Tab 不逃出 / Esc / 背景 inert + 非空洞前置）', async () => {
    test.setTimeout(240_000);
    const page = await openPage();
    requireSession();
    const session: Record<string, unknown> = {};
    try {
      await page.setViewportSize({ width: 1280, height: 1000 });

      /**
       * 单打开时收集可达性事实。
       *
       * **不再内联实现**（T11 第 1 条的修法之一）：读数逻辑收进
       * `support/real.sheetFocusFacts`，于是
       *   - 链路 4 的判据读的量，与 `e2e-real/control.spec.ts` 证明能红的量，
       *     是**同一段代码**产出的；
       *   - 「恒真路径」的存在位置（候选为空 ⇒ focusEscaped 恒 false）在实现处
       *     一眼可见，而不是埋在用例的匿名 evaluate 里。
       */
      const sheetFacts = async (): Promise<SheetFocusFacts> => page.evaluate(sheetFocusFacts);

      /** 在一张单上走完四条判据：焦点进入 → 背景 inert → Tab 不逃出 → Esc 关闭。 */
      const examineSheet = async (label: string, open: () => Promise<void>): Promise<void> => {
        await open();
        await expect(page.locator('.confirm-sheet')).toBeVisible({ timeout: 15_000 });
        const facts = await sheetFacts();
        session[`${label}:opened`] = facts;

        expect(facts.activeElementInsideSheet, `${label}：焦点没有进入确认单：${JSON.stringify(facts)}`).toBe(true);
        expect(facts.sheetRole, `${label}：role 不是 dialog`).toBe('dialog');
        expect(facts.sheetAriaModal, `${label}：aria-modal 不是 true`).toBe('true');
        expect(facts.inertCount, `${label}：确认单打开时背景没有被标记 inert`).toBeGreaterThan(0);

        // ── 非空洞性前置（T11 第 1 条）：堵死 backgroundFocusEscaped 的恒真路径 ──
        // 为什么必须有这一条：候选选择是 `outside.find(...) ?? outside[0] ?? null`，
        // 若单外**一个匹配元素都没有**则 candidate 为 null ⇒ `backgroundFocusEscaped`
        // 恒为 false ⇒ 下一行断言**无条件通过**。也就是说「背景不可聚焦」这个结论
        // 在无候选时从未被检验。本断言让那种情形**显式失败**，而不是安静地绿。
        //
        // 实测五处的候选数（见报告第 3 节）均 > 0，本断言因此成立；若将来某处背景
        // 真的没有可聚焦元素，本断言会红——那正是它存在的意义。届时应**如实报告
        // 该处 inert 结论强度受限**（结论是「没得测」而不是「测过了」），不得放宽判据。
        expect(
          facts.outsideSelectorMatchCount,
          `${label}：单外没有匹配元素（outsideSelectorMatchCount=0）⇒ backgroundFocusEscaped 会恒为 false、` +
            `这条 inert 判据在该处是空洞的。这**不是**产品缺陷，是判据前置不成立；` +
            `须如实报告该处 inert 结论强度受限，不得放宽断言。实测事实：${JSON.stringify(facts)}`,
        ).toBeGreaterThan(0);

        // ── 非空洞性前置之二（T11-r2 的 P2-1）：候选必须**真的被渲染** ──
        // 为什么上面那一条不够：`outsideSelectorMatchCount > 0` 只证明「选择器匹配到了元素」。
        // `display:none` / `visibility:hidden` 的元素**照样被匹配到**、`candidateTag` 也非 null，
        // 但 `focus()` 对它们静默失败 ⇒ `backgroundFocusEscaped` 仍为 false
        // ⇒ 「inert 挡住了背景聚焦」这条结论在该处**从未被检验**——与「无候选」是同一个
        // 空洞，只是入口更隐蔽（计数 > 0 让上一条前置放行）。本断言把那个入口也堵死。
        // 能红证明见 `e2e-real/control.spec.ts` 判据1 的臂 D（注入 display:none）。
        expect(
          facts.candidateVisible,
          `${label}：候选元素存在但**未被渲染**（candidateVisible=false，candidateTag=${String(facts.candidateTag)}）` +
            `⇒ \`focus()\` 会静默失败、backgroundFocusEscaped 恒为 false，这条 inert 判据在该处是空洞的。` +
            `这**不是**产品缺陷，是判据前置不成立；须如实报告该处 inert 结论强度受限，不得放宽断言。` +
            `实测事实：${JSON.stringify(facts)}`,
        ).toBe(true);

        expect(facts.backgroundFocusEscaped, `${label}：背景元素仍可被聚焦（inert 未生效）：${JSON.stringify(facts)}`).toBe(false);

        const insideCount = await page.locator('.confirm-sheet').locator('button, a[href], input, textarea, select').count();
        const trail: boolean[] = [];
        for (let press = 0; press < insideCount + 3; press += 1) {
          await page.keyboard.press('Tab');
          trail.push(
            await page.evaluate(() => {
              const sheet = document.querySelector('.confirm-sheet');
              return sheet !== null && document.activeElement !== null && sheet.contains(document.activeElement);
            }),
          );
        }
        session[`${label}:tabTrail`] = { insideCount, trail };
        expect(trail.every(Boolean), `${label}：Tab 逃出了确认单（trail=${JSON.stringify(trail)}）`).toBe(true);

        await page.screenshot({ path: `${OUT_DIR}/shots/confirm-sheet-${label}.png` });

        await page.keyboard.press('Escape');
        await expect(page.locator('.confirm-sheet')).toHaveCount(0, { timeout: 8_000 });
        const leftover = await page.evaluate(() => document.querySelectorAll('[inert]').length);
        session[`${label}:inertAfterEsc`] = leftover;
        expect(leftover, `${label}：Esc 关闭后 inert 没有恢复`).toBe(0);
      };

      // ── 单 1：设置页登出确认单 ────────────────────────────────────────
      await page.goto(`${BASE_URL}/settings`);
      await waitMounted(page);
      await examineSheet('settings-logout', async () => {
        await page.getByRole('button', { name: '退出登录' }).click();
      });

      // ── 单 2：档案页新建对象确认单（真实用户路径，无需预置数据）────────
      await page.goto(`${BASE_URL}/profile`);
      await waitMounted(page);
      await expect(page.getByRole('button', { name: '+ 新建对象' })).toBeVisible({ timeout: 25_000 });
      await examineSheet('profile-create-object', async () => {
        await page.getByRole('button', { name: '+ 新建对象' }).click();
      });

      // ── 单 3：档案页条目删除确认单 ───────────────────────────────────
      // 先经页面的真实 fetch（同一个被 SDK 包装过的 fetch ⇒ 带 anti-CSRF 头）
      // 建对象与条目。响应体里的真实 id 就是「数据真进了后端」的证据。
      const seed = await page.evaluate(async () => {
        const objectResponse = await fetch('/api/profile/objects', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ display_name: 'T10 真实栈探针对象' }),
        });
        const objectText = await objectResponse.text();
        const objectId = (JSON.parse(objectText) as { id?: string }).id ?? '';
        const itemResponse = await fetch(`/api/profile/objects/${objectId}/items`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            domain: 'physical_medical',
            topic: 'T10 探针条目',
            description: '这条由真实栈探针经真实后端写入，用于验证删除确认单',
          }),
        });
        const itemText = await itemResponse.text();
        return {
          objectStatus: objectResponse.status,
          objectId,
          objectBody: objectText.slice(0, 400),
          itemStatus: itemResponse.status,
          itemBody: itemText.slice(0, 400),
        };
      });
      session['seed'] = seed;
      expect(seed.objectId, `建档对象失败（status=${String(seed.objectStatus)}）：${seed.objectBody}`).toMatch(/^[0-9a-f-]{32,36}$/);
      expect(seed.itemStatus, `建档条目失败（status=${String(seed.itemStatus)}）：${seed.itemBody}`).toBe(201);

      await page.goto(`${BASE_URL}/profile`);
      await waitMounted(page);
      await page.getByRole('button', { name: 'T10 真实栈探针对象' }).click();
      await expect(page.getByText('T10 探针条目')).toBeVisible({ timeout: 25_000 });
      await examineSheet('profile-delete-item', async () => {
        await page
          .locator('.list-row', { hasText: 'T10 探针条目' })
          .getByRole('button', { name: '删除', exact: true })
          .click();
      });

      // ── 单 4（T11 补测）：档案页**对象菜单单**（`kind=menu`）────────────────
      // 为什么必须补：`ProfilePage.tsx` 里菜单单（`labelledBy="profile-object-title"`）
      // 与表单单（`profile-object-form-title`）是**两张用途不同的单**，共用同一个
      // `ObjectSheet` 位置、靠 `key={kind}` 强制重挂载。只测表单单（新建对象）时，
      // 菜单单的模态语义从未被真实浏览器检验过。
      // 入口：chip 尾随的「⋯」（`aria-label="对象操作"`），仅在有选中对象时渲染。
      await page.goto(`${BASE_URL}/profile`);
      await waitMounted(page);
      await page.getByRole('button', { name: 'T10 真实栈探针对象' }).click();
      await expect(page.getByRole('button', { name: '对象操作' })).toBeVisible({ timeout: 25_000 });
      await examineSheet('profile-object-menu', async () => {
        await page.getByRole('button', { name: '对象操作' }).click();
      });

      // ── 单 5（T11 补测）：记忆页删除确认单 ───────────────────────────────
      // 记忆面没有创建端点，episode 由 `write_memory` → `pending_write` → Worker 产生；
      // 而该写路径在本机当前因嵌入缺陷不可用（见 `support/real.seedMemoryEpisode`
      // 的说明与 `docs/TODO.md` 第四节的登记）。因此这里从存储层种一条**只写读路径
      // 最小字段集**的 episode 作为夹具——它不是响应伪造（全程无 `page.route`），
      // 页面经真实 HTTP API 读到它、经真实 DELETE 撤下它。
      //
      // 分区键必须用**链路 1 记下的 user id**（`SESSION.accountId`），不是邮箱：
      // 记忆的分区键取自登录态（`routes.py` 的 `current_account`），在 FalkorDB 后端
      // 它就是图名。用邮箱会种进另一张图，页面读不到——实测正是这样失败的。
      expect(SESSION.accountId, '链路 1 没有建立会话：记忆夹具不知道往哪张图写').not.toBe('');
      const memoryText = `T11 记忆页确认单夹具 ${String(Date.now())}`;
      const seededEpisode = await seedMemoryEpisode(SESSION.accountId, memoryText);
      session['memorySeed'] = { episodeKey: seededEpisode, content: memoryText, accountId: SESSION.accountId };

      await page.goto(`${BASE_URL}/settings/memory`);
      await waitMounted(page);
      const memoryRow = page.locator('.list-row', { hasText: memoryText });
      await expect(memoryRow).toBeVisible({ timeout: 25_000 });
      // 正面证据：这条记忆是经**真实 HTTP API** 读到的（真后端 + 真图库），不是夹具直接塞进 DOM。
      const memoryApiSeen = apiTrace.find(
        (entry) => entry.method === 'GET' && entry.url.includes('/api/memory/episodes') && entry.status === 200,
      );
      expect(
        memoryApiSeen,
        '记忆页没有经真实 API（GET /api/memory/episodes）取数——种下的片段不是经后端读到的',
      ).toBeDefined();
      session['memorySeedApiTrace'] = memoryApiSeen;
      await examineSheet('memory-delete', async () => {
        await memoryRow.getByRole('button', { name: '删除', exact: true }).click();
      });

      log.record('link4-confirm-sheets', {
        sheetsExercised: [
          'settings-logout',
          'profile-create-object',
          'profile-delete-item',
          'profile-object-menu',
          'memory-delete',
        ],
        // 五处「单外匹配元素数」的实测值集中列出：复查者一眼可核「无一处为空」。
        // 这就是非空洞性前置读的那个量（`outsideSelectorMatchCount`）。
        outsideSelectorMatchCounts: Object.fromEntries(
          [
            'settings-logout',
            'profile-create-object',
            'profile-delete-item',
            'profile-object-menu',
            'memory-delete',
          ].map((label) => [label, (session[`${label}:opened`] as SheetFocusFacts | undefined)?.outsideSelectorMatchCount]),
        ),
        // 五处「候选是否真的被渲染」（T11-r2 的 P2-1）：`outsideSelectorMatchCount > 0`
        // 不足以证明结论被测过，这一列才是「真的有可聚焦对象」的证据。
        candidateVisible: Object.fromEntries(
          [
            'settings-logout',
            'profile-create-object',
            'profile-delete-item',
            'profile-object-menu',
            'memory-delete',
          ].map((label) => [label, (session[`${label}:opened`] as SheetFocusFacts | undefined)?.candidateVisible]),
        ),
        // 同五处的其余读数（inert 数、候选标签、是否逃逸）——判据强度的完整依据。
        sheetFactsSummary: Object.fromEntries(
          [
            'settings-logout',
            'profile-create-object',
            'profile-delete-item',
            'profile-object-menu',
            'memory-delete',
          ].map((label) => {
            const facts = session[`${label}:opened`] as SheetFocusFacts | undefined;
            return [
              label,
              facts === undefined
                ? null
                : {
                    sheetRole: facts.sheetRole,
                    sheetAriaModal: facts.sheetAriaModal,
                    activeElementInsideSheet: facts.activeElementInsideSheet,
                    inertCount: facts.inertCount,
                    outsideSelectorMatchCount: facts.outsideSelectorMatchCount,
                    outsideNonInertCount: facts.outsideNonInertCount,
                    outsideDisabledCount: facts.outsideDisabledCount,
                    outsideVisibleCount: facts.outsideVisibleCount,
                    candidateTag: facts.candidateTag,
                    candidateVisible: facts.candidateVisible,
                    backgroundFocusEscaped: facts.backgroundFocusEscaped,
                  },
            ];
          }),
        ),
        memorySeed: session['memorySeed'],
        memorySeedApiTrace: session['memorySeedApiTrace'],
        session,
      });
      log.record('consoleAfterLink4', [...records]);
      await saveLog(log, 't10-real-log');
    } finally {
      await page.close();
    }
  });

  test('链路3 对话页：真实建会话 + 真实 SSE（真调 TokenHub）+ 无横向溢出 + 输入区贴底', async () => {
    test.setTimeout(300_000);
    const page = await openPage();
    requireSession();
    try {
      await page.setViewportSize({ width: 1280, height: 1000 });

      /**
       * 装一个**只读** SSE 字节观察口（见 support/real.ts 的 installSseTap）。
       *
       * 为什么不用 CDP 的 `Network.eventSourceMessageReceived`：本应用的 SSE 走
       * `fetch` + 流式 `ReadableStream`，**不是 `EventSource`**（契约第 2 节禁用它，
       * 因为 EventSource 无法带 anti-CSRF 自定义头）。实测该 CDP 事件 0 触发。
       * 为什么不用 `response.text()`：流已被页面自己消费，实测返回空串。
       * 观察口只 clone 一份流来读，**原请求照发、原响应原样给应用**，不是 mock。
       */
      await installSseTap(page);

      await page.goto(`${BASE_URL}/consult`);
      await waitMounted(page);
      const newConversation = page.getByRole('button', { name: /开始新的日常咨询/ });
      await expect(newConversation).toBeVisible({ timeout: 25_000 });

      const startedAt = Date.now();
      await newConversation.click();
      await expect(page).toHaveURL(/\/consult\/sessions\/[0-9a-f-]{32,36}/, { timeout: 40_000 });
      const sessionId = page.url().split('/').pop() ?? '';
      expect(sessionId, 'URL 里没有真实 session id').toMatch(/^[0-9a-f-]{32,36}$/);

      const createTrace = apiTrace.filter(
        (entry) => entry.method === 'POST' && entry.url.endsWith('/api/consult/sessions'),
      );
      expect(createTrace.length, '浏览器没有发出建会话请求').toBeGreaterThan(0);
      const lastCreate = createTrace[createTrace.length - 1];
      expect(lastCreate?.status, `建会话状态码不是 201：${JSON.stringify(lastCreate)}`).toBe(201);
      expect(lastCreate?.bodyKeyIds.join(' '), '建会话响应里没有真实 session_id').toMatch(/session_id=/);

      const composer = page.locator('#consult-composer');
      await expect(composer).toBeVisible({ timeout: 25_000 });

      /**
       * 对话页布局快照。
       *
       * `elementsPastViewportRight` 不在这里内联，而是**单列一次** `page.evaluate(共用函数)`
       * （见下方 `readOverflow`）。理由（T11 第 2 条）：元素级信号是「无横向溢出」的**判据**，
       * 而负面控制臂（`e2e-real/control.spec.ts`）必须证明**同一个量**能红。两处各写一份
       * 选择器时，控制臂证明的只是「另一个量会红」——那正是 T06 的 P1-1 踩过的坑
       * （生产喂文档级、证明喂内层级）。
       */
      const readLayout = (): Promise<Record<string, unknown>> =>
        page.evaluate(() => {
          const screenRect = document.querySelector('.device-screen')?.getBoundingClientRect() ?? null;
          const composerRect = document.querySelector('#consult-composer')?.getBoundingClientRect() ?? null;
          // 输入区所在容器（chatPage.module.css 的 .footer）：按「包含 composer 或
          // .chat-progress 的那一层」识别，不靠 CSS Modules 的哈希类名猜。
          const footerCandidate = Array.from(document.querySelectorAll('div')).find(
            (element) =>
              element.className.includes('footer') &&
              (element.querySelector('#consult-composer') !== null || element.querySelector('.chat-progress') !== null),
          );
          const footerRect = footerCandidate?.getBoundingClientRect() ?? null;
          return {
            documentScrollWidth: document.documentElement.scrollWidth,
            documentClientWidth: document.documentElement.clientWidth,
            bodyScrollWidth: document.body.scrollWidth,
            screenBottom: screenRect?.bottom ?? null,
            screenHeight: screenRect?.height ?? null,
            composerBottom: composerRect?.bottom ?? null,
            composerInsideShell: composerRect !== null && screenRect !== null ? composerRect.bottom <= screenRect.bottom + 1 : null,
            footerBottom: footerRect?.bottom ?? null,
            footerClass: footerCandidate === undefined ? null : footerCandidate.className,
          };
        });

      /**
       * 元素级横向溢出读数——**与负面控制臂共用同一个取量函数**。
       *
       * 为什么文档级 `scrollWidth <= clientWidth` 不够（`(z17)`：判据会不会被我自己的
       * 布局裁掉/吸收？）：宽视口下 `.device { overflow: hidden }`（`global.css:152`）
       * 把外壳内的横向溢出裁掉，于是它**不会传递到** `documentElement.scrollWidth`——
       * 判据在自己的布局里被吸收了，读数恒等于 0。T10 两处实测该文档级判据均为「无溢出」，
       * 而元素级数组同样为 `[]`：两者在真出现内部溢出时才会分道扬镳。
       *
       * 因此判据落在**元素级** `elementsPastViewportRight`（视口右边界之外的元素清单）：
       * 它读的是每个元素自己的 rect，不经过任何 overflow 裁切。
       */
      const readOverflow = (): Promise<string[]> => page.evaluate(elementsPastViewportRight);

      // ── 布局判据在「输入区可见」的初始态测量 ───────────────────────────
      // 为什么不在运行结束后测：本产品在「待作答」时会**按设计收起输入区**
      // （对话页设计布局结构第 3 节），那时 composer 根本不在 DOM 里，
      // 拿它判「贴底」会得到 null —— 判据必须落在它存在的状态上。
      const layoutBeforeSend = await readLayout();
      const overflowBeforeSend = await readOverflow();

      const message = '你好，请用一句话说明你能帮我做什么';
      await composer.fill(message);
      await page.getByRole('button', { name: '发送' }).click();

      // 首字到达（≤30s 判据）
      const assistantDoc = page.locator('.msg-doc').first();
      await expect(assistantDoc).toBeVisible({ timeout: 35_000 });
      await expect
        .poll(async () => (await assistantDoc.innerText()).trim().length, {
          message: '首字未在 35 秒内到达：助手正文仍为空',
          timeout: 35_000,
        })
        .toBeGreaterThan(0);
      const firstTokenAt = Date.now();

      // ── 整体完成（≤120s 判据）─────────────────────────────────────────
      // 判据用**运行已结束**的可观测证据：「停止」按钮消失（运行中才渲染），
      // 且不再有「正在…」之外的新增正文。
      //
      // 为什么不把 `.chat-progress` 消失也当判据：它由 `statusText !== null` 决定，
      // 而 statusText 有多个来源（待作答的「请先处理上面的问题」、重连、慢运行、
      // progress 事件）。把「进度容器存在」等同「运行未结束」会把**待作答**这种
      // 正常的终态误判成超时——那不是产品缺陷，是判据写错了。
      // 因此这里只等「停止按钮消失」，并把进度容器的**实际文案**一并记录下来。
      await expect
        .poll(
          async () =>
            page.evaluate(() => ({
              hasStop: Array.from(document.querySelectorAll('button')).some((button) => button.textContent?.trim() === '停止'),
              progressText: document.querySelector('.chat-progress')?.textContent?.trim() ?? null,
              hasComposer: document.querySelector('#consult-composer') !== null,
              questionCards: document.querySelectorAll('.question-card').length,
            })),
          { message: '等待运行结束超时（停止按钮未消失）', timeout: 180_000 },
        )
        .toMatchObject({ hasStop: false });
      const finishedAt = Date.now();

      /** 运行结束后的终态快照（进度容器文案、是否有待作答卡、输入区是否在）。 */
      const terminal = await page.evaluate(() => ({
        progressText: document.querySelector('.chat-progress')?.textContent?.trim() ?? null,
        hasComposer: document.querySelector('#consult-composer') !== null,
        questionCards: document.querySelectorAll('.question-card').length,
        errorCards: document.querySelectorAll('.error-card').length,
        interruptedNote: document.querySelector('.status.off')?.textContent?.trim() ?? null,
      }));

      const assistantText = (await assistantDoc.innerText()).trim();

      // ── SSE 证据：观察口采到的**真实到达浏览器的帧** ──────────────────
      const streamTrace = apiTrace.find(
        (entry) => entry.url.includes('/api/consult/runs/') && entry.url.includes('/stream'),
      );
      const tap = await readSseTap(page);
      const sseEventCounts: Record<string, number> = {};
      for (const frame of tap.events) {
        sseEventCounts[frame.event] = (sseEventCounts[frame.event] ?? 0) + 1;
      }
      // 从 text_delta 帧里取一段真实正文片段，证明事件流里确实带内容
      // （不是「有帧但帧是空的」）。
      const textDeltaSamples = tap.events
        .filter((frame) => frame.event === 'text_delta')
        .slice(0, 3)
        .map((frame) => frame.data.slice(0, 200));

      const layout = await readLayout();
      const overflowAfterRun = await readOverflow();

      const result = {
        sessionId,
        sessionUrl: page.url(),
        message,
        assistantTextLength: assistantText.length,
        assistantTextPreview: assistantText.slice(0, 500),
        firstTokenMs: firstTokenAt - startedAt,
        finishedMs: finishedAt - startedAt,
        terminal,
        createTrace: lastCreate,
        sse: {
          // 帧来自 SSE 观察口（support/real.ts 的 installSseTap）；
          // 请求本身由 apiTrace 记录（浏览器真实发出的 /api/consult/runs/*/stream）。
          requestSeenInApiTrace: streamTrace !== undefined,
          requestUrl: streamTrace?.url ?? null,
          requestStatus: streamTrace?.status ?? null,
          tappedUrl: tap.url,
          tappedContentType: tap.contentType,
          tappedStatus: tap.status,
          frameCount: tap.events.length,
          rawFrameCount: tap.raw.length,
          eventCounts: sseEventCounts,
          textDeltaSamples,
        },
        layoutBeforeSend,
        layoutAfterRun: layout,
        overflowBeforeSend,
        overflowAfterRun,
        layoutChecks: {
          // 文档级读数**保留为登记项**（不删）：它与元素级信号的关系本身是证据——
          // 两者在「真有内部溢出」时才会分道扬镳，只留一个就看不到这件事。
          documentScrollWidthFitsBeforeSend:
            (layoutBeforeSend['documentScrollWidth'] as number) <= (layoutBeforeSend['documentClientWidth'] as number) + 1,
          documentScrollWidthFitsAfterRun:
            (layout['documentScrollWidth'] as number) <= (layout['documentClientWidth'] as number) + 1,
          // 承重判据（T11 第 2 条）：元素级信号为空。`(z17)`——文档级读数会被
          // `.device{overflow:hidden}` 裁掉，只有元素级读数能捕捉外壳内部的横向溢出。
          noElementPastViewportRightBeforeSend: overflowBeforeSend.length === 0,
          noElementPastViewportRightAfterRun: overflowAfterRun.length === 0,
          // 「输入区贴底」在**输入区存在**的初始态上判：它由 .footer 承担，
          // footer 底边应贴外壳屏幕区底边。
          footerPinnedToShellBottomBeforeSend:
            layoutBeforeSend['footerBottom'] !== null && layoutBeforeSend['screenBottom'] !== null
              ? Math.abs((layoutBeforeSend['footerBottom'] as number) - (layoutBeforeSend['screenBottom'] as number)) <= 2
              : null,
          composerInsideShellBeforeSend: layoutBeforeSend['composerInsideShell'],
        },
        leftoverInert: await page.evaluate(() => document.querySelectorAll('[inert]').length),
      };

      log.record('link3-chat-sse', result);
      await saveLog(log, 't10-real-log');
      await page.screenshot({ path: `${OUT_DIR}/shots/chat-real-sse.png`, fullPage: true });

      // ── 逐条断言 ─────────────────────────────────────────────────────
      expect(streamTrace, '浏览器没有发起 /api/consult/runs/{id}/stream 请求：SSE 没走真后端').toBeDefined();
      expect(streamTrace?.status, 'SSE 响应状态不是 200').toBe(200);
      expect(tap.contentType, 'SSE 响应的 content-type 不是 text/event-stream').toContain('text/event-stream');
      expect(tap.url, 'SSE 观察口没有捕获到任何事件流').not.toBe('');
      expect(tap.events.length, 'SSE 事件流里没有任何帧：没有内容从事件流到达').toBeGreaterThan(0);
      expect(
        (sseEventCounts['text_delta'] ?? 0) > 0,
        `SSE 里没有 text_delta 事件（事件计数 ${JSON.stringify(sseEventCounts)}）`,
      ).toBe(true);
      expect(
        textDeltaSamples.some((sample) => sample.length > 0),
        `text_delta 帧里没有内容：${JSON.stringify(textDeltaSamples)}`,
      ).toBe(true);
      expect(assistantText.length, '助手正文为空：模型没有返回内容').toBeGreaterThan(0);
      expect(result.firstTokenMs, `首字耗时 ${String(result.firstTokenMs)}ms 超过 30s`).toBeLessThanOrEqual(30_000);
      expect(result.finishedMs, `整体耗时 ${String(result.finishedMs)}ms 超过 120s`).toBeLessThanOrEqual(120_000);
      expect(
        result.layoutChecks.noElementPastViewportRightBeforeSend,
        `发送前有元素越出视口右边界（元素级横向溢出）：${JSON.stringify(overflowBeforeSend)}；` +
          `同一次的文档级读数 ${JSON.stringify({ scrollWidth: layoutBeforeSend['documentScrollWidth'], clientWidth: layoutBeforeSend['documentClientWidth'] })}` +
          `（文档级会被 .device{overflow:hidden} 裁掉，因此它是登记项、不是判据）`,
      ).toBe(true);
      expect(
        result.layoutChecks.noElementPastViewportRightAfterRun,
        `运行后有元素越出视口右边界（元素级横向溢出）：${JSON.stringify(overflowAfterRun)}；` +
          `同一次的文档级读数 ${JSON.stringify({ scrollWidth: layout['documentScrollWidth'], clientWidth: layout['documentClientWidth'] })}`,
      ).toBe(true);
      expect(
        result.layoutChecks.footerPinnedToShellBottomBeforeSend,
        `输入区没有贴外壳底边：${JSON.stringify(layoutBeforeSend)}`,
      ).toBe(true);
      expect(result.layoutChecks.composerInsideShellBeforeSend, `输入区落在外壳之外：${JSON.stringify(layoutBeforeSend)}`).toBe(true);
      expect(result.leftoverInert, '对话页上仍有残留的 inert 属性').toBe(0);
    } finally {
      await page.close();
    }
  });

  test('链路7 全程 console 无 error、无未捕获异常、无 5xx', async () => {
    // ── 采集器活性探针（T11-r2 的 P2-2）──────────────────────────────────
    //
    // 为什么必须有它：`unparsedCount === 0` 只挡**格式漂移**，挡不住「**零条 response 记录**」
    // ——那时 `serverErrors` 是空数组，5xx 判据**以空数组静默通过**。本轮之前这条一直是
    // 靠链路 1 那条真实 401 兜着的，**代码里没钉**。这里主动发一个**必然 404** 的请求：
    // 它必须落进 `tally.clientErrors` ⇒ 给采集器一条「真的在记录非 2xx 响应」的证据。
    // 能红证明见 `e2e-real/control.spec.ts` 判据4（同一 404、采集器未挂时计数不增长）。
    const livenessPage = await openPage();
    let livenessProbe: { status: number; url: string; collectorGrew: boolean } = {
      status: 0,
      url: '',
      collectorGrew: false,
    };
    try {
      await livenessPage.goto(`${BASE_URL}/`, { waitUntil: 'domcontentloaded' });
      await waitMounted(livenessPage);
      const before = records.filter((record) => record.kind === 'response-4xx-5xx').length;
      const probe = await livenessPage.evaluate(async () => {
        // 该路径在真实后端上不存在 ⇒ 必然 404（经 Vite 的 /api 代理打到 8000）。
        const response = await fetch('/api/__t11_collector_liveness_probe__');
        return { status: response.status, url: response.url };
      });
      // `page.on('response')` 是异步投递的：等它落进 sink，避免与采集器赛跑产生假红。
      await expect
        .poll(() => records.filter((record) => record.kind === 'response-4xx-5xx').length, {
          message: '采集器活性探针：发出的 404 没有落进 response-4xx-5xx 记录 —— 采集器可能没在记',
          timeout: 10_000,
        })
        .toBeGreaterThan(before);
      livenessProbe = {
        status: probe.status,
        url: probe.url,
        collectorGrew: records.filter((record) => record.kind === 'response-4xx-5xx').length > before,
      };
    } finally {
      await livenessPage.close();
    }

    const consoleErrors = records.filter((record) => record.kind === 'console-error');
    const browserNetworkErrors = records.filter((record) => record.kind === 'console-network-error');
    const pageErrors = records.filter((record) => record.kind === 'pageerror');
    const failedRequests = records.filter((record) => record.kind === 'requestfailed');
    const badResponses = records.filter((record) => record.kind === 'response-4xx-5xx');

    // ── 5xx 判据（T11 第 3 条）────────────────────────────────────────────
    //
    // 修前：三类响应信号（browserNetworkErrors / badResponses / failedRequests）
    // **完全不断言**——采集了但没有任何判据读它们，于是新增的真 4xx/5xx 不会让链路 7 变红。
    //
    // 修后：断言 **5xx 数为 0**。5xx 是真正的缺陷信号（服务端自己的错误），
    // 与「使用者请求了不存在的东西」（4xx）是两类事实，前者无条件应为空。
    //
    // 4xx **不做全局断言**：其中含**预期的**未登录 `session/refresh` 401
    // （supertokens-web-js 在没有 sRefreshToken 时的首载探测；T10 实测在
    // 未登录的 `/`、`/login` 与未知路由上都发生，登录后 reload 不再发生）。
    // 它是既有探测行为，不是缺陷。
    //
    // ⚠ 口径，不是过滤：那几条 401 **原样留在产物 JSON**（`badResponses` / `browserNetworkErrors`
    // 两个桶都不删）。`tallyResponses` 只做分类计数。下面 `unexpectedClientErrorCount`
    // 也落盘，但**本包不对它断言**——它的期望值取决于本轮探针覆盖了哪些页面，
    // 写死一个「应该为 0」会在新增任何页面用例时变成假红。
    const tally = tallyResponses(records);

    // 采集器活性：那个**必然 404** 的探针必须出现在 clientErrors 里。
    // 判据用「URL 逐字匹配」而不是「计数 > 0」——后者会被任何一条无关 4xx 满足（含预期的 401），
    // 那又会变成一条读不到被测事实的检查。
    const livenessInTally = tally.clientErrors.filter((reading) => reading.url.endsWith('/api/__t11_collector_liveness_probe__'));

    log.record('link7-console', {
      total: records.length,
      consoleErrors,
      browserNetworkErrors,
      pageErrors,
      failedRequests,
      badResponses,
      // 分类计数（**不改动上面的原始桶**——它们是「未静默过滤」的自证）。
      tally,
      livenessProbe: { ...livenessProbe, inTallyCount: livenessInTally.length },
      note: [
        'consoleErrors = 页面 JS 主动的 console.error（应用侧）。',
        'browserNetworkErrors = 浏览器为失败响应自动记的「Failed to load resource: …」（不是应用异常）。',
        '两者分开陈述，不互相掩盖，也不把浏览器日志从判据里静默过滤掉。',
        'tally.serverErrors 为 5xx 判据的原料；tally.clientErrors 保留全部 4xx，不对其做全局断言。',
        `预期口径：未登录 POST /api/auth/session/refresh 的 401（本轮 ${String(tally.expectedAnonymousRefreshCount)} 条），` +
          '它是 supertokens-web-js 的首载探测行为，不是缺陷——但它仍原样留在产物里。',
        'livenessProbe 是**采集器活性**的证据：它主动发一个必然 404，并断言该请求出现在 clientErrors 里，' +
          '从而排除「零条 response 记录 ⇒ serverErrors 空数组静默通过」这一形态。',
      ].join(' '),
    });
    await saveLog(log, 't10-real-log');

    expect(pageErrors, `存在未捕获异常：${JSON.stringify(pageErrors, null, 1)}`).toHaveLength(0);
    expect(consoleErrors, `存在 console.error：${JSON.stringify(consoleErrors, null, 1)}`).toHaveLength(0);
    expect(
      tally.serverErrors,
      `全程出现 5xx 响应（服务端错误，真正的缺陷信号）：${JSON.stringify(tally.serverErrors, null, 1)}`,
    ).toHaveLength(0);
    // 解析失败必须可见：采集格式漂移会让 5xx 判据**静默退化**成空数组（一条永远不会失败的检查）。
    expect(
      tally.unparsedCount,
      `有 ${String(tally.unparsedCount)} 条 response-4xx-5xx 记录无法解析 ⇒ 5xx 判据会静默退化，必须显式失败`,
    ).toBe(0);
    // ── 采集器活性（T11-r2 的 P2-2）──────────────────────────────────────
    // 上面三条都可能在「采集器一条都没记」时安静通过。本断言要求那条第 404 的探针
    // **确实出现在 `clientErrors` 里** —— 这是「采集器活着」的直接证据，而不是靠
    // 「恰好有别的 4xx」间接推断。
    expect(
      livenessProbe.status,
      `采集器活性探针：/api/__t11_collector_liveness_probe__ 返回 ${String(livenessProbe.status)}（期望 404）` +
        `⇒ 该路径不存在这一前提不成立，本活性证明无效（不要放宽，须换一个必然非 2xx 的探针）`,
    ).toBe(404);
    expect(
      livenessInTally.length,
      `采集器活性探针：发出的 404（${livenessProbe.url}）没有出现在 tally.clientErrors 里 ` +
        `⇒ 采集器没有把非 2xx 响应记进 sink，serverErrors 的空数组**不能**读成「没有 5xx」。` +
        `本轮 clientErrors 全量：${JSON.stringify(tally.clientErrors, null, 1)}`,
    ).toBeGreaterThan(0);
  });
});