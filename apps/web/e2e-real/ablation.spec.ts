/**
 * 消融探针：证明「`.tab-bar` 收在外壳内」这条判据**确实由 `.device` 的 transform 承担**，
 * 以及链路 7 的控制台分类器**真的能抓到应用侧 error**（非空泛检查）。
 *
 * ⚠ 需要真实栈。消融用例，不做验收判定——它证明的是**判据的因果性**与**检查的非空泛性**。
 *
 * 为什么必须做这两个消融（AGENTS.md 的纪律）：
 *   1. 「`.tab-bar` 在壳内」若在任何 CSS 下都成立，它就不是判据而是恒真式
 *      ⇒ 必须让它在去掉承重属性后**变假**；
 *   2. 「console 无 error」若采集器根本没在工作（或分类器把所有东西都归到别的桶），
 *      它同样恒真 ⇒ 必须用一个**真实的应用侧 console.error** 让判据变红。
 */

import { test, expect } from '@playwright/test';

import {
  BASE_URL,
  createLog,
  freshAccount,
  freshPassword,
  inviteCodeFor,
  saveLog,
  watchConsole,
  waitMounted,
  type ConsoleRecord,
} from './support/real';

test.describe.configure({ mode: 'serial' });

/**
 * 建一个真实会话（真邀请码注册）。
 *
 * 为什么消融也需要它：`.tab-bar` 只在一级页面渲染，而那些页面全部走 RequireSession
 * 守卫——没有会话时它们会重定向到 `/login`，而登录页**故意不渲染 tab 栏**
 * （它不是一级页面）。因此「在无会话的页面上量 tab 栏几何」会量到 null，
 * 那条判据就成了空泛的。
 */
async function registerRealSession(page: import('@playwright/test').Page, invitePoolIndex: number): Promise<string> {
  // 消融用码池下标 1 / 2：下标 0 留给验收链路 1，3 / 4 留给 e2e-real/control.spec.ts
  // 的两条控制臂（邀请码一次性使用，各文件的下标必须互不重叠——T11 实测踩到过：
  // 两文件共用下标 1 / 2 时后者拿到已用掉的码，注册静默失败）。
  const invite = inviteCodeFor(invitePoolIndex);
  expect(invite, '消融需要真实邀请码（T10_INVITE_CODES）').not.toBe('');
  const stamp = Date.now();
  const account = freshAccount(stamp);
  const password = freshPassword(stamp);

  await page.goto(`${BASE_URL}/login`);
  await waitMounted(page);
  const result = await page.evaluate(
    async (payload: { account: string; password: string; invite: string }) => {
      const response = await fetch('/api/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          formFields: [
            { id: 'email', value: payload.account },
            { id: 'password', value: payload.password },
            { id: 'inviteCode', value: payload.invite },
          ],
        }),
      });
      const text = await response.text();
      let status = '';
      try {
        status = (JSON.parse(text) as { status?: string }).status ?? '';
      } catch {
        status = '(非 JSON)';
      }
      return { httpStatus: response.status, status, body: text.slice(0, 200) };
    },
    { account, password, invite },
  );
  // ⚠ 判据是**响应体里的 `status`**，不是 HTTP 状态码：邀请码已被使用时
  // supertokens 返回 **HTTP 200 + `{"status":"GENERAL_ERROR"}`**，因此只断言
  // `200` 是一条恒真的检查——它会在注册实际失败时放行（T11 实测踩到，
  // 表现为后续「找不到 .tab-bar」超时）。这是「禁止永远不会失败的检查」的实例。
  expect(result.httpStatus, `消融的注册请求没被处理（HTTP ${String(result.httpStatus)}）：${result.body}`).toBe(200);
  expect(result.status, `消融的注册**没有成功**（body.status=${result.status}）：${result.body}`).toBe('OK');
  return account;
}

test('@ablation .device 的 transform 是「.tab-bar 收在壳内」的承重属性', async ({ browser }) => {
  const inviteIndex = 1;
  test.setTimeout(180_000);
  const log = createLog();
  const context = await browser.newContext({ baseURL: BASE_URL, viewport: { width: 1280, height: 1000 } });
  const page = await context.newPage();

  const measureTabBar = (): Promise<Record<string, unknown>> =>
    page.evaluate(() => {
      const tabBar = document.querySelector('.tab-bar')?.getBoundingClientRect() ?? null;
      const screen = document.querySelector('.device-screen')?.getBoundingClientRect() ?? null;
      const device = document.querySelector('.device');
      return {
        viewportWidth: window.innerWidth,
        tabBar: tabBar === null ? null : { left: tabBar.left, width: tabBar.width, right: tabBar.right, bottom: tabBar.bottom },
        screen: screen === null ? null : { left: screen.left, width: screen.width, right: screen.right, bottom: screen.bottom },
        deviceTransform: device === null ? null : getComputedStyle(device).transform,
        insideScreen:
          tabBar !== null && screen !== null && screen.width > 0
            ? tabBar.left >= screen.left - 0.5 && tabBar.right <= screen.right + 0.5
            : null,
      };
    });

  // 建真实会话：`.tab-bar` 只在一级页面渲染，而那些页面全部走守卫。
  await registerRealSession(page, inviteIndex);
  await page.goto(`${BASE_URL}/settings`);
  await waitMounted(page);
  await expect(page.locator('.tab-bar')).toBeVisible({ timeout: 25_000 });

  // ── 基线臂：现状（有 transform）──
  const baseline = await measureTabBar();

  // ── 消融臂：只去掉 .device 的 transform，其余一切不变 ──
  await page.addStyleTag({ content: '.device { transform: none !important; }' });
  await page.waitForTimeout(300);
  const ablated = await measureTabBar();

  // ── 复现臂：撤销消融（重新加载页面回到现状）──
  await page.reload();
  await waitMounted(page);
  const restored = await measureTabBar();

  log.record('ablation-transform', {
    baseline,
    ablated,
    restored,
    // 结论性判据：去掉 transform 后 .tab-bar 是否离开外壳屏幕区。
    // 实测它同时丢掉两条约束：宽度 390 → 480（=`--phone-shell-max`，即包含块从
    // .device 变成了 .phone-shell）与底边 922 → 1000（贴着浏览器视口底边）。
    tabBarLeavesShellWithoutTransform: ablated['insideScreen'] === false && baseline['insideScreen'] === true,
    ablationIsReversible:
      (restored['tabBar'] as { width: number } | null)?.width === (baseline['tabBar'] as { width: number } | null)?.width &&
      (restored['insideScreen'] as boolean | null) === true,
  });
  await saveLog(log, 'ablation-transform');

  expect(baseline['insideScreen'], '基线臂：.tab-bar 本来就不在壳内，这条判据没有意义').toBe(true);
  expect(
    (baseline['tabBar'] as { width: number }).width,
    '基线臂：.tab-bar 宽度不是屏幕区宽 390',
  ).toBe(390);
  expect(
    (ablated['tabBar'] as { width: number }).width,
    `消融臂：去掉 transform 后 .tab-bar 宽度没有变成 --phone-shell-max（480）⇒ transform 不是承重属性（实测 ${JSON.stringify(ablated)}）`,
  ).toBe(480);
  expect(
    (ablated['tabBar'] as { bottom: number }).bottom,
    `消融臂：去掉 transform 后 .tab-bar 底边没有贴到浏览器视口底边（1000）⇒ 包含块没换（实测 ${JSON.stringify(ablated)}）`,
  ).toBe(1000);
  expect(ablated['insideScreen'], '消融臂：去掉 transform 后 .tab-bar 仍在壳内 ⇒ 判据不是由 transform 承担').toBe(false);
  expect(
    (restored['tabBar'] as { width: number }).width,
    '复现臂：撤销消融后 .tab-bar 没有回到 390 ⇒ 消融效果不可逆，因果性证据不成立',
  ).toBe(390);

  await context.close();
});

test('@ablation 链路7 的控制台分类器能抓到应用侧 console.error', async ({ browser }) => {
  const inviteIndex = 2;
  const log = createLog();
  const context = await browser.newContext({ baseURL: BASE_URL, viewport: { width: 1280, height: 1000 } });
  const page = await context.newPage();

  // 用同一个分类器（watchConsole），只注入一条**人为的**应用侧 console.error。
  // 若它被归到 consoleErrors，说明这条检查不是空泛的「永远通过」。
  const records: ConsoleRecord[] = [];
  watchConsole(page, records);

  // 先建一个真实会话再注入：这条消融要在**与链路 7 相同的运行时条件**下做
  // （链路 7 汇总的是登录后各页面的控制台）。
  //
  // 注意：注册过程本身要先访问一次未登录的 `/login`，而那次访问**会**产生
  // 一条浏览器 401 网络日志（既有探测行为，见 t10-real.spec.ts 的链路 7 说明）。
  // 因此判据不是「全程 0 条网络日志」，而是「**拿到会话之后**不再新增」——
  // 那才是「这条 401 属于未登录探测、不属于已登录页面」的正面证据。
  await registerRealSession(page, inviteIndex);
  await page.goto(`${BASE_URL}/settings`);
  await waitMounted(page);
  await page.waitForTimeout(1200);

  /** 已登录后的记录起点：此后新增的网络错误都归因于已登录页面。 */
  const authenticatedMark = records.length;
  const beforeInjection = records.filter((record) => record.kind === 'console-error').length;
  const networkErrorsBeforeInjection = records.filter((record) => record.kind === 'console-network-error').length;
  const networkErrorsDuringAnonymousLoad = networkErrorsBeforeInjection;

  // 这条 console.error 就是本次消融的**输入**：没有它，「链路 7 无 console error」
  // 就无法被证明是一条**能失败**的检查（而不是一条永远通过的检查）。
  const urlAtInjection = page.url();
  await page.evaluate(() => {
    // oxlint-disable-next-line no-console -- 消融的输入，见上
    console.error('T10 消融：这是一条人为的应用侧 console.error');
  });
  await page.waitForTimeout(500);

  const afterInjection = records.filter((record) => record.kind === 'console-error');
  const browserNetworkErrors = records.filter((record) => record.kind === 'console-network-error');
  /** 已登录之后新增的浏览器网络日志（应为 0）。 */
  const networkErrorsAfterAuthenticatedMark = records
    .slice(authenticatedMark)
    .filter((record) => record.kind === 'console-network-error');

  log.record('ablation-console-classifier', {
    urlAtInjection,
    authenticatedMark,
    beforeInjection,
    networkErrorsDuringAnonymousLoad,
    networkErrorsAfterAuthenticatedMark,
    afterInjection,
    browserNetworkErrors,
    note: [
      'beforeInjection 是真实运行时（登录后页面）的应用侧 error 数；afterInjection 应恰好比它多 1。',
      'networkErrorsDuringAnonymousLoad 是注册过程中访问未登录 /login 产生的那条 401（既有探测行为）。',
      'networkErrorsAfterAuthenticatedMark 是拿到会话之后新增的浏览器网络日志——判据要求它为 0。',
      '这条消融同时证明分类器在起作用：应用侧 error 进 consoleErrors，浏览器自动的失败资源日志进 browserNetworkErrors。',
    ].join(' '),
  });
  await saveLog(log, 'ablation-console-classifier');

  expect(afterInjection.length, '注入的应用侧 console.error 没有被采集到 ⇒ 链路 7 的检查是空泛的').toBe(beforeInjection + 1);
  expect(
    afterInjection.some((record) => record.text.includes('T10 消融')),
    '采集到的 error 文本里没有注入的那条',
  ).toBe(true);
  // 关键分离判据：那条浏览器 401 日志**不在** consoleErrors 桶里。
  expect(
    afterInjection.every((record) => !record.text.startsWith('Failed to load resource:')),
    `consoleErrors 桶里混进了浏览器自动的资源日志：${JSON.stringify(afterInjection, null, 1)}`,
  ).toBe(true);
  expect(networkErrorsDuringAnonymousLoad, '未登录 /login 那次访问应当产生 1 条浏览器 401 网络日志').toBeGreaterThan(0);
  expect(
    networkErrorsAfterAuthenticatedMark,
    `拿到会话之后的页面不该新增浏览器网络错误日志（实测 ${JSON.stringify(networkErrorsAfterAuthenticatedMark, null, 1)}）`,
  ).toHaveLength(0);

  await context.close();
});
