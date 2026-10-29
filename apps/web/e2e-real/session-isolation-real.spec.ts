/**
 * 模块: e2e-real/session-isolation-real
 * 职责: 账号隔离与「停止后可恢复」的真栈工程验收
 *
 * 需要真实栈：后端 8000（/readyz 200）、Vite 5173（/api 代理到 8000）、专用库与图库。
 * 本文件不启动服务、不清理既有数据，只创建本轮的新账号与新行；两条用例各自注册自己的账号，
 * 因此可以单独 --grep 跑（第 1 条要 2 枚邀请码，第 2 条要 1 枚）。
 *
 * 环境变量：SIA_INVITE_CODES（逗号分隔的一次性码池，下标 0/1 归账号 A/B，2 归 SSE 用例账号）、
 * SIA_ACCOUNT_A/B/C、SIA_PASSWORD_A/B/C（缺省按时间戳生成；指定必须是本轮新账号）；
 * T10_BASE_URL、T10_OUT 沿用 support/real.ts。缺邀请码即显式失败，不跳过。
 * 口令只用于填表，不打印、不落盘、不截图。
 *
 * 运行：pnpm --filter @campfire/web exec playwright test \
 *         --config e2e-real/playwright.real.config.ts --grep "@session-isolation" --reporter=list
 *
 * 与 README §7「不得 page.route / route.fulfill」的收窄：全文零处 fulfill；唯一一处 route 用
 * route.abort('failed') **注入一次分页失败**（被测场景本身）。注入前同一条请求真拿到 200，
 * 解除注入后「重试加载」又真拿到 200，且 requestfailed 记录证明失败的是注入的那条。
 */

import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';

import { expect, test, type Page } from '@playwright/test';

import {
  BASE_URL,
  OUT_DIR,
  createLog,
  installSseTap,
  readSseTap,
  saveLog,
  waitMounted,
  watchApi,
  watchConsole,
  type ApiTrace,
  type ConsoleRecord,
} from './support/real';
import {
  clearForbiddenHits,
  collectRequests,
  installForbiddenTextWatch,
  logoutViaSettings,
  readForbiddenHits,
  readSessionCookieFacts,
  registerWithInvite,
  signIn,
} from './support/sessionIsolation';

const STAMP = Date.now();

function inviteFor(index: number): string {
  const pool = (process.env.SIA_INVITE_CODES ?? '')
    .split(',')
    .map((code) => code.trim())
    .filter((code) => code !== '');
  return pool[index] ?? '';
}

function accountFor(envName: string, tag: string): string {
  const given = process.env[envName]?.trim() ?? '';
  return given === '' ? `sia-${tag}-${String(STAMP)}` : given;
}

// 口令满足产品策略（≥8 字符、含小写字母与数字）；只用于填表。
function passwordFor(envName: string, tag: string): string {
  const given = process.env[envName]?.trim() ?? '';
  return given === '' ? `sia${String(STAMP % 100000)}${tag}pw` : given;
}

const ACCOUNT_A = accountFor('SIA_ACCOUNT_A', 'a');
const ACCOUNT_B = accountFor('SIA_ACCOUNT_B', 'b');
const ACCOUNT_C = accountFor('SIA_ACCOUNT_C', 'c');
const PASSWORD_A = passwordFor('SIA_PASSWORD_A', 'a');
const PASSWORD_B = passwordFor('SIA_PASSWORD_B', 'b');
const PASSWORD_C = passwordFor('SIA_PASSWORD_C', 'c');

/** A 的独有标记；B 的界面上任何时刻都不该出现。 */
const OBJECT_A = `隔离验证档案-${String(STAMP)}`;
/** 阴性对照：任何一轮都不存在，命中它即说明观察口径坏了。 */
const NONCE = `sia-never-${String(STAMP)}`;
/** 契约 3.2：`limit` 默认 20；造 21 条才有第二页。 */
const PAGE_SIZE = 20;
const SESSIONS_TO_SEED = PAGE_SIZE + 1;
const RUN_TIMEOUT_MS = 330_000;

function sessionRows(page: Page) {
  return page.locator('section[aria-label="咨询记录"] button.list-row');
}

/** 把真正的滚动容器（外壳内 .device-screen，或窄视口下的文档）滚到底。 */
async function scrollToBottom(page: Page): Promise<void> {
  await page.evaluate(() => {
    const row = document.querySelector('button.list-row');
    let node: HTMLElement | null = row === null ? null : row.parentElement;
    while (node !== null) {
      const overflowY = getComputedStyle(node).overflowY;
      if ((overflowY === 'auto' || overflowY === 'scroll') && node.scrollHeight > node.clientHeight) {
        node.scrollTop = node.scrollHeight;
        return;
      }
      node = node.parentElement;
    }
    const root = document.scrollingElement;
    if (root !== null) root.scrollTop = root.scrollHeight;
  });
}

/** 触底触发一次分页请求并返回其地址；滚不出请求即失败（夹具不足或触底加载坏了）。 */
async function triggerLoadMore(page: Page): Promise<string> {
  const watcher = collectRequests(page, (url) => url.includes('/api/consult/sessions?') && url.includes('cursor='));
  try {
    for (let attempt = 0; attempt < 10 && watcher.urls.length === 0; attempt += 1) {
      await scrollToBottom(page);
      await page.waitForTimeout(300);
    }
    const fired = watcher.urls[0];
    if (fired === undefined) throw new Error('触底十次仍无分页请求：没有第二页（夹具不足）或触底加载坏了');
    return fired;
  } finally {
    watcher.stop();
  }
}

/** 等这一轮跑到终态（SSE 的 run_finished / run_failed）。 */
async function waitRunTerminal(page: Page, label: string): Promise<'finished' | 'failed'> {
  await expect
    .poll(
      async () => {
        const tap = await readSseTap(page);
        if (tap.events.some((event) => event.event === 'run_failed')) return 'failed';
        return tap.events.some((event) => event.event === 'run_finished') ? 'finished' : 'running';
      },
      { timeout: RUN_TIMEOUT_MS, message: `等这一轮跑到终态：${label}` },
    )
    .not.toBe('running');
  const tap = await readSseTap(page);
  return tap.events.some((event) => event.event === 'run_failed') ? 'failed' : 'finished';
}

test.describe('@session-isolation 账号隔离与停止后恢复（真实依赖）', () => {
  test('账号切换：A 的会话与档案不得闪到 B，分页失败后列表仍在', async ({ browser }) => {
    test.setTimeout(300_000);
    const log = createLog();
    const inviteA = inviteFor(0);
    const inviteB = inviteFor(1);
    expect(inviteA, '必须提供真实邀请码：SIA_INVITE_CODES 第 1 枚（账号 A）').not.toBe('');
    expect(inviteB, '必须提供真实邀请码：SIA_INVITE_CODES 第 2 枚（账号 B）').not.toBe('');
    expect(ACCOUNT_A, '两个账号不得同名（否则隔离断言分不清是谁的字）').not.toBe(ACCOUNT_B);

    const records: ConsoleRecord[] = [];
    const context = await browser.newContext({
      baseURL: BASE_URL,
      locale: 'zh-CN',
      timezoneId: 'Asia/Shanghai',
      viewport: { width: 1280, height: 1000 },
    });
    try {
      await mkdir(resolve(OUT_DIR, 'shots'), { recursive: true });
      const page = await context.newPage();
      watchConsole(page, records);
      // 先装观察口再首次导航；NONCE 是阴性对照。
      await installForbiddenTextWatch(page, [OBJECT_A, ACCOUNT_A, NONCE]);

      await registerWithInvite(page, ACCOUNT_A, PASSWORD_A, inviteA);
      const cookiesA = await readSessionCookieFacts(context, page);
      expect(cookiesA.tokenCookies.some((cookie) => cookie.name === 'sAccessToken')).toBe(true);
      expect(cookiesA.tokenCookies.every((cookie) => cookie.httpOnly), '会话凭据必须 httpOnly').toBe(true);
      expect(cookiesA.jsVisibleCookieNames).not.toContain('sAccessToken');

      // A 建档案对象（真 201）
      await page.goto(`${BASE_URL}/profile`);
      await waitMounted(page);
      await page.getByRole('button', { name: '+ 新建对象', exact: true }).click();
      const sheet = page.getByRole('dialog', { name: '给 TA 起个称呼' });
      await sheet.getByRole('textbox', { name: '称呼' }).fill(OBJECT_A);
      const objectAnswered = page.waitForResponse(
        (response) => response.url().endsWith('/api/profile/objects') && response.request().method() === 'POST',
      );
      await sheet.getByRole('button', { name: '创建', exact: true }).click();
      const objectResponse = await objectAnswered;
      expect(objectResponse.status()).toBe(201);
      const object = (await objectResponse.json()) as { id: string; display_name: string };
      expect(object.display_name).toBe(OBJECT_A);
      expect(object.id).not.toBe('');

      // 造两页会话（每条都要 201）
      const seeded = await page.evaluate(
        async (payload: { objectId: string; count: number }) => {
          const statuses: number[] = [];
          const sessionIds: string[] = [];
          for (let index = 0; index < payload.count; index += 1) {
            const response = await fetch('/api/consult/sessions', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ support_object_id: payload.objectId }),
            });
            statuses.push(response.status);
            if (response.ok) {
              const body = (await response.json()) as { session_id?: string };
              if (typeof body.session_id === 'string') sessionIds.push(body.session_id);
            }
          }
          return { statuses, sessionIds };
        },
        { objectId: object.id, count: SESSIONS_TO_SEED },
      );
      expect(seeded.statuses).toEqual(Array.from({ length: SESSIONS_TO_SEED }, () => 201));
      const firstSessionId = seeded.sessionIds[0] ?? '';
      expect(firstSessionId, '第一条会话没有真实 id').not.toBe('');

      // 阳性对照：观察口在 A 的页面上抓得到；阴性对照：不存在的串不命中
      await page.goto(`${BASE_URL}/consult`);
      await waitMounted(page);
      await expect(sessionRows(page)).toHaveCount(PAGE_SIZE, { timeout: 30_000 });
      await expect
        .poll(async () => (await readForbiddenHits(page)).some((hit) => hit.needle === OBJECT_A), {
          timeout: 20_000,
          message: '阳性对照失败：观察口没抓到 A 的档案名，「没抓到」就不能证明任何事',
        })
        .toBe(true);
      expect((await readForbiddenHits(page)).some((hit) => hit.needle === NONCE), '阴性对照失败').toBe(false);
      await page.screenshot({ path: resolve(OUT_DIR, 'shots', 'session-isolation-a-list.png'), animations: 'disabled' });

      // 真实正控：触底加载成功一次（20 → 21 行）
      const firstMore = page.waitForResponse(
        (response) => response.url().includes('/api/consult/sessions?') && response.url().includes('cursor='),
      );
      await triggerLoadMore(page);
      const firstMoreResponse = await firstMore;
      expect(firstMoreResponse.status()).toBe(200);
      await expect(sessionRows(page)).toHaveCount(SESSIONS_TO_SEED, { timeout: 20_000 });

      // 故障注入：只让「下一页」这条请求失败（唯一一处 route，绝不 fulfill）
      await page.reload();
      await waitMounted(page);
      await expect(sessionRows(page)).toHaveCount(PAGE_SIZE, { timeout: 30_000 });
      const failedRequests: string[] = [];
      page.on('requestfailed', (request) => {
        if (request.url().includes('cursor=')) failedRequests.push(request.url());
      });
      const cursorPredicate = (url: URL): boolean =>
        url.pathname === '/api/consult/sessions' && url.searchParams.has('cursor');
      await page.route(cursorPredicate, (route) => route.abort('failed'));
      try {
        expect(await triggerLoadMore(page)).toContain('cursor=');
        await expect(
          page.locator('.error-card').filter({ hasText: '更早的会话没有加载出来' }),
          '分页失败要给原因与重试，而不是整页错误卡',
        ).toBeVisible({ timeout: 20_000 });
        await expect(sessionRows(page), '分页失败后已加载的记录必须还在').toHaveCount(PAGE_SIZE);
        await expect
          .poll(() => failedRequests.length, {
            timeout: 15_000,
            message: '没有观察到被注入失败的请求：错误卡可能来自别处',
          })
          .toBeGreaterThan(0);
      } finally {
        await page.unroute(cursorPredicate);
      }

      // 解除注入后的真实正控：手动重试拿到 200
      const retried = page.waitForResponse((response) => response.url().includes('cursor='));
      await page.getByRole('button', { name: '重试加载' }).click();
      expect((await retried).status()).toBe(200);
      await expect(sessionRows(page)).toHaveCount(SESSIONS_TO_SEED, { timeout: 20_000 });
      await expect(page.locator('.error-card')).toHaveCount(0);

      // A 打开自己的对话页：把会话级缓存真的填上
      await page.goto(`${BASE_URL}/consult/sessions/${firstSessionId}`);
      await waitMounted(page);
      await expect(page.locator('#consult-composer')).toBeVisible({ timeout: 40_000 });

      // 切换：登出 A → 注册并进入 B
      await logoutViaSettings(page);
      expect((await context.cookies()).some((cookie) => cookie.name === 'sAccessToken')).toBe(false);
      expect(await page.evaluate(() => localStorage.getItem('campfire.account-name'))).toBeNull();
      expect((await context.request.get(`${BASE_URL}/api/consult/sessions`)).status(), '未登录必须 401').toBe(401);
      // 命中在这里清零：A 的页面（含设置页上的 A 账号名）到此为止，之后看到的每一条都属于 B。
      await clearForbiddenHits(page);

      await registerWithInvite(page, ACCOUNT_B, PASSWORD_B, inviteB);
      expect(await page.evaluate(() => localStorage.getItem('campfire.account-name'))).toBe(ACCOUNT_B);
      expect(
        (await readSessionCookieFacts(context, page)).tokenCookies.every((cookie) => cookie.httpOnly),
        'B 的凭据同样必须 httpOnly',
      ).toBe(true);

      // B：三处界面都不该有 A 的东西（界面 + 接口两层）
      await page.goto(`${BASE_URL}/consult`);
      await waitMounted(page);
      await expect(page.getByText('还没有咨询记录', { exact: true })).toBeVisible({ timeout: 30_000 });
      await expect(sessionRows(page)).toHaveCount(0);
      const bSessions = await context.request.get(`${BASE_URL}/api/consult/sessions`);
      expect(bSessions.status()).toBe(200);
      expect(((await bSessions.json()) as { items: unknown[] }).items.length).toBe(0);

      await page.goto(`${BASE_URL}/profile`);
      await waitMounted(page);
      await expect(page.getByText('还没有记录', { exact: true }).first()).toBeVisible({ timeout: 30_000 });

      await page.goto(`${BASE_URL}/settings`);
      await waitMounted(page);
      await expect(page.getByRole('heading', { name: ACCOUNT_B, exact: true })).toBeVisible({ timeout: 20_000 });
      await expect(page.getByText(ACCOUNT_A), '设置页不得显示 A 的账号名').toHaveCount(0);
      await page.screenshot({
        path: resolve(OUT_DIR, 'shots', 'session-isolation-b-settings.png'),
        animations: 'disabled',
      });

      // 真实登录（不消耗邀请码）：B 登出再登入，界面仍只属于 B
      await logoutViaSettings(page);
      await signIn(page, ACCOUNT_B, PASSWORD_B);
      expect(await page.evaluate(() => localStorage.getItem('campfire.account-name'))).toBe(ACCOUNT_B);

      // B 打开 A 的会话地址：真 404，而不是缓存内容
      const crossAccount = await context.request.get(`${BASE_URL}/api/consult/sessions/${firstSessionId}/messages`);
      expect(crossAccount.status(), '越权读取他人会话必须 404').toBe(404);
      await page.goto(`${BASE_URL}/consult/sessions/${firstSessionId}`);
      await waitMounted(page);
      await expect(page.getByText('找不到这条内容', { exact: true })).toBeVisible({ timeout: 40_000 });
      await expect(page.locator('#consult-composer')).toHaveCount(0);

      const leaked = (await readForbiddenHits(page)).filter(
        (hit) => hit.needle === OBJECT_A || hit.needle === ACCOUNT_A,
      );
      expect(leaked, `B 的界面闪现了 A 的内容：${JSON.stringify(leaked)}`).toEqual([]);
      const pageErrors = records.filter((record) => record.kind === 'pageerror');
      expect(pageErrors, `页面未捕获异常：${JSON.stringify(pageErrors)}`).toEqual([]);

      log.record('account-switch', {
        accountA: ACCOUNT_A,
        accountB: ACCOUNT_B,
        objectId: object.id,
        sessionCount: seeded.sessionIds.length,
        firstSessionId,
        pagination: { firstMore: firstMoreResponse.status(), injectedFailures: failedRequests.length },
        forbiddenHits: await readForbiddenHits(page),
        console: records,
      });
      await saveLog(log, 'session-isolation-account-switch');
    } finally {
      await context.close();
    }
  });

  test('SSE 中途停止后刷新水合，并能继续发送', async ({ browser }) => {
    test.setTimeout(600_000);
    const log = createLog();
    const invite = inviteFor(2);
    expect(invite, '必须提供真实邀请码：SIA_INVITE_CODES 第 3 枚（SSE 用例账号）').not.toBe('');

    const records: ConsoleRecord[] = [];
    const trace: ApiTrace[] = [];
    const context = await browser.newContext({
      baseURL: BASE_URL,
      locale: 'zh-CN',
      timezoneId: 'Asia/Shanghai',
      viewport: { width: 1280, height: 1000 },
    });
    try {
      const page = await context.newPage();
      watchConsole(page, records);
      watchApi(page, trace);
      await installSseTap(page);
      await registerWithInvite(page, ACCOUNT_C, PASSWORD_C, invite);

      // 建本用例自己的会话（真 201 + 真 session id）
      await page.goto(`${BASE_URL}/consult`);
      await waitMounted(page);
      const created = page.waitForResponse(
        (response) => response.url().endsWith('/api/consult/sessions') && response.request().method() === 'POST',
      );
      await page.getByRole('button', { name: /开始新的日常咨询/ }).click();
      expect((await created).status()).toBe(201);
      await expect(page).toHaveURL(/\/consult\/sessions\/[0-9a-f-]{32,36}/, { timeout: 40_000 });
      const sessionId = page.url().split('/').pop() ?? '';
      expect(sessionId, 'URL 里没有真实 session id').toMatch(/^[0-9a-f-]{32,36}$/);

      // 跳过一次性引导（产品自己的入口，走真端点）
      const skip = page.getByRole('button', { name: '跳过引导' });
      await expect(skip).toBeVisible({ timeout: 25_000 });
      const skipAnswered = page.waitForResponse((response) => response.url().endsWith('/onboarding/skip'));
      await skip.click();
      expect((await skipAnswered).status()).toBe(200);
      await expect(skip).toHaveCount(0, { timeout: 20_000 });

      // 第一次真实发送：SSE 跑起来之后再停止
      const firstText = '请用一句话说明你能在什么情况下帮我。';
      const composer = page.locator('#consult-composer');
      await expect(composer).toBeVisible({ timeout: 30_000 });
      const accepted = page.waitForResponse(
        (response) => response.url().endsWith('/messages') && response.request().method() === 'POST',
      );
      await composer.fill(firstText);
      await page.getByRole('button', { name: '发送', exact: true }).click();
      const acceptedResponse = await accepted;
      expect(acceptedResponse.status(), '发消息应被受理（202）').toBe(202);
      const runId = ((await acceptedResponse.json()) as { run_id: string }).run_id;
      expect(runId).not.toBe('');

      await expect
        .poll(async () => (await readSseTap(page)).url, { timeout: 60_000, message: 'SSE 流没有建立' })
        .toContain('/stream');
      await expect.poll(async () => (await readSseTap(page)).status).toBe(200);
      // 至少收到一帧再停：这时运行确实已开始（使用者消息已进真源），
      // 「刷新后还在」才是对产品承诺的检验，而不是对「刚发送就取消」的猜测。
      await expect
        .poll(async () => (await readSseTap(page)).events.length, { timeout: 90_000, message: 'SSE 一帧都没到' })
        .toBeGreaterThan(0);

      const stop = page.getByRole('button', { name: '停止', exact: true });
      await expect(stop, '运行中应有停止按钮').toBeVisible({ timeout: 30_000 });
      const cancelled = page.waitForResponse((response) => response.url().endsWith('/cancel'));
      await stop.click();
      expect((await cancelled).status(), '停止要真的打到取消端点（202）').toBe(202);
      await expect(page.getByText('本次回答中断', { exact: true })).toBeVisible({ timeout: 20_000 });
      await expect(page.locator('.error-card'), '停止不是失败').toHaveCount(0);
      await expect(composer, '停止之后必须还能继续输入').toBeVisible({ timeout: 20_000 });

      // 刷新：历史水合必须含这条使用者消息
      await page.reload();
      await waitMounted(page);
      await expect(page.locator('.bubble-user').filter({ hasText: firstText }), '刷新后丢了这条消息').toHaveCount(1, {
        timeout: 40_000,
      });
      await expect(page.locator('.error-card'), '刷新水合不得变成错误卡').toHaveCount(0);
      const historyCall = (): ApiTrace[] =>
        trace.filter(
          (entry) => entry.method === 'GET' && entry.url.includes(`/api/consult/sessions/${sessionId}/messages`),
        );
      await expect
        .poll(() => historyCall().length, { timeout: 20_000, message: '刷新后没有读到历史' })
        .toBeGreaterThan(0);
      expect(historyCall().every((entry) => entry.status === 200)).toBe(true);

      // 恢复发送：409 session_busy 会在这里被抓到
      const secondText = '那在家里可以怎么安排？';
      await expect(composer).toBeVisible({ timeout: 30_000 });
      const secondAccepted = page.waitForResponse(
        (response) => response.url().endsWith('/messages') && response.request().method() === 'POST',
      );
      await composer.fill(secondText);
      await page.getByRole('button', { name: '发送', exact: true }).click();
      const secondResponse = await secondAccepted;
      expect(secondResponse.status(), '停止之后必须还能起新一轮（202；409 说明被卡住）').toBe(202);
      const secondRunId = ((await secondResponse.json()) as { run_id: string }).run_id;
      expect(secondRunId).not.toBe('');

      let outcome = await waitRunTerminal(page, '停止后的第二轮');
      if (outcome === 'failed') {
        // 外部抖动按产品的处置走：点它自己的「重试」，只重试一次。
        const retry = page.locator('.error-card').getByRole('button', { name: '重试' });
        await expect(retry).toBeVisible({ timeout: 20_000 });
        await retry.click();
        outcome = await waitRunTerminal(page, '点重试之后的那一轮');
      }
      expect(outcome, '停止后重新起的一轮没有跑到 run_finished').toBe('finished');
      await expect(page.locator('.bubble-user').filter({ hasText: secondText })).toHaveCount(1);
      await expect(page.locator('.error-card')).toHaveCount(0);
      const tap = await readSseTap(page);
      // 模型可以先提问再作答，故「有内容事件」取 text_delta 或 question 之一。
      expect(
        tap.events.some((event) => event.event === 'text_delta' || event.event === 'question'),
        `真实 SSE 应至少有一帧内容事件，实际：${tap.events.map((event) => event.event).join(',')}`,
      ).toBe(true);

      log.record('sse-stop-resume', {
        account: ACCOUNT_C,
        sessionId,
        runIds: { stopped: runId, resumed: secondRunId },
        terminal: outcome,
        hydratedStatuses: historyCall().map((entry) => entry.status),
        console: records,
      });
      await saveLog(log, 'session-isolation-sse-stop-resume');
    } finally {
      await context.close();
    }
  });
});
