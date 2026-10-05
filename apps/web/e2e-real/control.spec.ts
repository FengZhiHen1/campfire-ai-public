/**
 * 模块: e2e-real/control
 * 职责: T11/T11-r2 新加固判据的**非空洞性证明**——用同一个取量函数与同一个判据函数，
 *       在注入/构造的负面条件下让它们**真的变红**（T11-r2 新增第 4 条：采集器活性）。
 *
 * ⚠ 需要真实栈（同 `t10-real.spec.ts`）。本文件不做验收判定，它证明的是**判据能失败**。
 *
 * 为什么必须有这个文件（AGENTS.md 的硬纪律）
 *
 * 「留下永远不会失败的检查」是本项目反复踩的一类缺陷（T10 复查 P2-1/P2-2/P2-4 三条
 * 全是同一形状：量被采集了但判据读不到它，或判据在某个分支恒真）。给判据加断言之后，
 * **断言本身**同样需要证明能红——否则只是把一条空洞判据换成另一条。
 *
 * 四条证明与它们各自的关键约束（每条都写清「用什么量、为什么必须是那个量」）
 *
 *   1. `outsideSelectorMatchCount > 0` 与 `candidateVisible === true`：
 *      臂 A/B/C 覆盖前者（移除元素 ⇒ 计数落到 0；撤掉 inert ⇒ escaped 翻转），
 *      **臂 D** 覆盖后者（注入 `display:none` ⇒ 计数仍 > 0、候选仍在，但不可渲染 ⇒ 新断言必须红）。
 *      为什么臂 D 不可省：它造的是**能穿过** `outsideSelectorMatchCount > 0` 的空洞
 *      （T11-r2 的 P2-1 正是这条残余），因此是新增断言存在的全部理由。
 *      全部用**同一个** `sheetFocusFacts()`（与链路 4 的判据同源）。
 *      为什么不是「把它们 `disabled`」：`disabled` **不改变** `document.querySelectorAll` 的
 *      匹配结果（实测计数仍是 6）——那会让本臂变成一条恒真的控制，见下方测试体里的臂说明。
 *   2. `elementsPastViewportRight` 为空：注入一个越出视口右边界的元素，数组应非空；
 *      用**同一个** `elementsPastViewportRight()`（与链路 3 的判据同源）。
 *      这条同时是「为什么文档级不足」的实证：同一次注入下文档级 `scrollWidth` 读数**不变**。
 *   3. `tally.serverErrors` 为空：给同一个 `tallyResponses()` 喂一条**合成**的 500 记录，
 *      它必须落进 `serverErrors`。合成记录是刻意的——本机实测**找不到**任何由产品
 *      自然产生的 5xx（`tmp/T11/fuzz-5xx.cjs` 侦查 35 条畸形载荷，`HITS_5XX = []`），
 *      而 5xx 判据又必须能红。合成记录证明的是**分类器**能把它认出来。
 *      **边界（必须随报告读）**：它不证明「真后端真能返回 5xx 并被 Playwright 采集到」，
 *      那一环由链路 7 的真实运行环境承担（`watchConsole` 的 `response` 监听器对
 *      任何 ≥400 响应都记录，与状态码无关）。
 *   4. 链路 7 的**采集器活性**断言（T11-r2 的 P2-2）：主动发一个必然 404 的路径，
 *      它必须落进 `tally.clientErrors`。本文件用**差分**造出能红的形态——
 *      同一个 404、只变「采集器挂没挂」这一个自变量：未挂 ⇒ 命中 0 条（活性断言红）、
 *      已挂 ⇒ 命中 ≥1 条（活性断言绿）。它拦的是「零条 response 记录 ⇒ `serverErrors`
 *      空数组静默通过」。
 */

import { test, expect } from '@playwright/test';

import {
  BASE_URL,
  createLog,
  elementsPastViewportRight,
  saveLog,
  sheetFocusFacts,
  tallyResponses,
  waitMounted,
  watchConsole,
  type ConsoleRecord,
} from './support/real';

test.describe.configure({ mode: 'serial' });

/**
 * 建一个真实会话（真邀请码注册）。
 *
 * 为什么控制臂也需要它：确认单只在一级页面（走 RequireSession 守卫）上渲染，
 * 没有会话时页面会重定向到 `/login`——那里根本没有 `.confirm-sheet`，
 * 「单外可聚焦元素计数」会去量一个不存在的东西，证明就成了空转。
 *
 * ⚠ 判据是**响应体里的 `status`**，不是 HTTP 状态码：邀请码已被使用时，
 * supertokens 返回的是 **HTTP 200 + `{"status":"GENERAL_ERROR","message":"邀请码无效或已不可用"}`**。
 * 只断言 `status === 200` 是一条**恒真的检查**——它会在注册实际失败时放行，
 * 后续以「找不到退出登录按钮」的形式超时（T11 实测踩到：控制臂与消融臂抢同一批
 * 邀请码下标，消融先用掉，控制臂静默拿到了失败响应）。这是本项目「禁止永远不会
 * 失败的检查」在本文件内的实例，故在此显式钉住 body 判据。
 */
async function registerRealSession(
  page: import('@playwright/test').Page,
  invitePoolIndex: number,
  label: string,
): Promise<void> {
  const { inviteCodeFor, freshAccount, freshPassword } = await import('./support/real');
  const invite = inviteCodeFor(invitePoolIndex);
  expect(invite, `${label}需要真实邀请码（T10_INVITE_CODES）`).not.toBe('');
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
  // 两条判据都要：HTTP 200 只说明请求被处理了，`status === 'OK'` 才说明注册成功。
  expect(result.httpStatus, `${label}的注册请求没被处理（HTTP ${String(result.httpStatus)}）：${result.body}`).toBe(200);
  expect(
    result.status,
    `${label}的注册**没有成功**（body.status=${result.status}，下标 ${String(invitePoolIndex)} 的邀请码可能已被别的用例用掉）：${result.body}`,
  ).toBe('OK');
}

test('@control 判据1 非空洞性：单外无匹配元素时判据落到空洞分支，撤掉 inert 时必须 escaped=true', async ({ browser }) => {
  test.setTimeout(180_000);
  const log = createLog();
  const context = await browser.newContext({ baseURL: BASE_URL, viewport: { width: 1280, height: 1000 } });
  const page = await context.newPage();
  watchConsole(page, []);

  await registerRealSession(page, 3, '控制臂1');
  await page.goto(`${BASE_URL}/settings`);
  await waitMounted(page);
  await page.getByRole('button', { name: '退出登录' }).click();
  await expect(page.locator('.confirm-sheet')).toBeVisible({ timeout: 15_000 });

  // ── 臂 A（基线）：单外确有匹配元素，且 inert 生效 ⇒ 聚焦逃不出去 ──
  const baseline = await page.evaluate(sheetFocusFacts);

  // ── 臂 B（正对照）：撤掉背景的 inert，其余不变 ⇒ 聚焦**必须**逃出去 ──
  //
  // 这一臂证明的是「判据真的在度量 inert 的效力」，而不是一个恒为 false 的读数。
  // 没有它的话，`backgroundFocusEscaped === false` 有可能因为**任何**原因（候选
  // disabled、页面结构变化、选择器写错）而恒真，而本包无从分辨。
  const inertRemoved = await page.evaluate(() => {
    const marked = Array.from(document.querySelectorAll('[inert]'));
    for (const element of marked) element.removeAttribute('inert');
    // 焦点重新落回单内，避免上一臂的聚焦结果干扰本次判定。
    document.querySelector<HTMLElement>('.confirm-sheet')?.focus();
    return { removed: marked.length };
  });
  const withoutInert = await page.evaluate(sheetFocusFacts);

  // ── 臂 D（T11-r2 的 P2-1「能红」证明）：候选存在但**未被渲染** ⇒ candidateVisible=false ──
  //
  // 顺序刻意排在臂 C **之前**：臂 C 会把单外元素从 DOM 移除，之后就没有东西可供本臂隐藏了
  // （那会让本臂的 `hidden > 0` 前提落空、退化成空转）。
  //
  // 这是 P2-1 点名的残余空洞：给单外元素注入 `display:none` 后，
  //   - `outsideSelectorMatchCount` **仍然 > 0**（`querySelectorAll` 不看渲染）⇒ 臂 C 之外
  //     那条 `> 0` 前置会**放行**；
  //   - `candidateTag` **仍然非 null**（元素还在 DOM 里、选择器匹配得到）；
  //   - 但 `getClientRects().length === 0` ⇒ `candidateVisible === false`；
  //   - 于是 `focus()` 静默失败 ⇒ `backgroundFocusEscaped === false`（**恒真路径**又出现了）。
  // ⇒ 链路 4 新增的 `expect(facts.candidateVisible).toBe(true)` **在本臂必须红**。
  //
  // 本臂的额外强度：它跑在臂 B **撤掉 inert 之后**，因此 `backgroundFocusEscaped === false`
  // **不可能**归因于 inert —— 唯一的解释就是候选不可渲染。这同时证明那个读数并不总是
  // inert 的函数（与臂 B 的正对照互为补充）。
  const hidden = await page.evaluate(() => {
    const sheet = document.querySelector('.confirm-sheet');
    if (sheet === null) return { hidden: 0 };
    let count = 0;
    for (const element of Array.from(document.querySelectorAll('button, a[href], input, textarea, select'))) {
      if (sheet.contains(element)) continue;
      (element as HTMLElement).style.display = 'none';
      count += 1;
    }
    return { hidden: count };
  });
  const invisible = await page.evaluate(sheetFocusFacts);

  // ── 臂 C（负面控制）：把单外的匹配元素从 DOM 移除 ⇒ 计数落到 0 ──
  //
  // 这正是链路 4 那条 `outsideSelectorMatchCount > 0` 断言要拦的形态：「背景没有
  // 可聚焦元素」时 `backgroundFocusEscaped` **恒为 false**，于是「inert 真的阻断了
  // 背景聚焦」这个结论在该处从未被检验。本臂把那个空洞**造出来**，并断言两件事：
  //   ① 计数确实为 0（⇒ 那条前置断言会红）；
  //   ② 在这种情形下 `backgroundFocusEscaped === false` 且 `candidateTag === null`
  //      ⇒ 结论是「没得测」，不是「测过了、通过了」。
  const removed = await page.evaluate(() => {
    const sheet = document.querySelector('.confirm-sheet');
    if (sheet === null) return { removed: 0 };
    let count = 0;
    for (const element of Array.from(document.querySelectorAll('button, a[href], input, textarea, select'))) {
      if (sheet.contains(element)) continue;
      element.remove();
      count += 1;
    }
    return { removed: count };
  });
  const vacuous = await page.evaluate(sheetFocusFacts);

  log.record('control-focusable-count', {
    baseline,
    withoutInert,
    inertRemoved,
    hidden,
    invisible,
    vacuous,
    removed,
    arms: {
      A_baseline: '单外有匹配元素 + inert 生效 ⇒ backgroundFocusEscaped=false 且计数>0（判据有可测对象）',
      B_positive: '撤掉 inert ⇒ backgroundFocusEscaped 必须变 true（判据真的在度量 inert 的效力）',
      C_negative: '移除全部单外匹配元素 ⇒ outsideSelectorMatchCount=0 且 backgroundFocusEscaped=false 且 candidateTag=null' +
        '（⇒ 链路 4 的 `> 0` 前置断言会红；该处的 inert 结论是「没得测」而不是「测过了」）',
      D_invisible: '给全部单外匹配元素注入 display:none ⇒ outsideSelectorMatchCount 仍 >0、candidateTag 仍非 null、' +
        '但 candidateVisible=false 且 backgroundFocusEscaped=false' +
        '（⇒ 链路 4 的 `candidateVisible === true` 前置断言会红；本臂证明该新断言不是恒真的检查）',
    },
    boundary:
      '本臂证明「该断言的量能被压到 0」与「该读数会随 inert 的有无翻转」。它不证明链路 4 五处真实' +
      '流程的背景都丰富——那由链路 4 的实测值（outsideSelectorMatchCounts / candidateVisible）承担。' +
      '另有一条本臂未覆盖的残余（如实登记）：候选若恰好是 disabled 元素，聚焦会失败、' +
      'backgroundFocusEscaped 亦为 false，那条路径的结论强度弱于 inert 生效的情形。' +
      '**又一条残余（P2-1 的边界）**：`candidateVisible` 用 `getClientRects()` 判定，' +
      '`visibility:hidden` 的元素**仍会产出 rect**（本读数覆盖不到它），但那种元素 focus() 同样静默失败。',
  });
  await saveLog(log, 'control-focusable-count');

  // 臂 A：判据在正常路径上有可测对象，且 inert 确实挡住了聚焦。
  expect(baseline.sheetPresent, '基线臂：确认单不存在，本臂没有可测对象').toBe(true);
  expect(baseline.inertCount, '基线臂：背景没有被标记 inert ⇒ 本臂的前提不成立').toBeGreaterThan(0);
  expect(
    baseline.outsideSelectorMatchCount,
    '基线臂：单外本来就没有匹配元素 ⇒ 这条判据没有可证的东西',
  ).toBeGreaterThan(0);
  expect(baseline.backgroundFocusEscaped, '基线臂：inert 生效时背景仍可被聚焦').toBe(false);

  // 臂 B（正对照）：撤掉 inert 后判据必须翻转，否则它可能压根不是在量 inert。
  expect(inertRemoved.removed, '正对照臂：页面上本来就没有 [inert] ⇒ 撤不掉，本臂无效').toBeGreaterThan(0);
  expect(
    withoutInert.backgroundFocusEscaped,
    `正对照臂：撤掉背景的 inert 之后 backgroundFocusEscaped 仍为 ${String(withoutInert.backgroundFocusEscaped)} ` +
      `⇒ 这个读数不是 inert 的函数（它可能是恒 false，或候选压根聚焦不了：candidateTag=${String(withoutInert.candidateTag)}）`,
  ).toBe(true);

  // 臂 C（负面控制）：空洞被造出来时，前置断言会红，且结论是「没得测」。
  expect(removed.removed, '负面控制臂：单外本来就没有匹配元素可供移除，本臂无效').toBeGreaterThan(0);
  expect(
    vacuous.outsideSelectorMatchCount,
    `负面控制臂：移除全部单外匹配元素后计数仍为 ${String(vacuous.outsideSelectorMatchCount)} ` +
      `⇒ 链路 4 的「非空洞性前置」是恒真的检查`,
  ).toBe(0);
  expect(
    vacuous.candidateTag,
    '负面控制臂：无候选时 candidateTag 应为 null（这正是恒真路径的入口）',
  ).toBeNull();
  expect(
    vacuous.backgroundFocusEscaped,
    '负面控制臂：无候选时 backgroundFocusEscaped 应为 false —— 那正是「恒真路径」，判据在此**没有测到任何东西**',
  ).toBe(false);

  // 臂 D（P2-1 的「能红」证明）：候选存在但未被渲染 ⇒ `candidateVisible` 断言必须红。
  //
  // 这一臂与前三条的关系：臂 C 造的是「**没有**候选」的空洞，本臂造的是「**有**候选、
  // 但它不可渲染」的空洞——后者**能穿过臂 C 要拦的那条 `outsideSelectorMatchCount > 0`
  // 前置**（计数仍 > 0），因此是 P2-1 新增断言存在的全部理由。若本臂三项断言中的
  // `candidateVisible === false` 不成立，说明那条新断言是恒真的检查（本项目明令禁止）。
  expect(hidden.hidden, '臂 D：单外本来就没有匹配元素可供隐藏，本臂无效').toBeGreaterThan(0);
  expect(
    invisible.outsideSelectorMatchCount,
    `臂 D：隐藏（display:none）后 outsideSelectorMatchCount 落到 ${String(invisible.outsideSelectorMatchCount)} ` +
      `⇒ 本臂不再能证明「计数 > 0 也拦不住」这一点（querySelectorAll 不看渲染，本应仍 > 0）`,
  ).toBeGreaterThan(0);
  expect(
    invisible.candidateTag,
    '臂 D：candidateTag 仍应为非 null（元素还在 DOM 里，选择器匹配得到）——这是本空洞之所以隐蔽的原因',
  ).not.toBeNull();
  expect(
    invisible.candidateVisible,
    `臂 D：候选被 display:none 隐藏后 candidateVisible 仍为 ${String(invisible.candidateVisible)} ` +
      `⇒ 链路 4 新增的 \`candidateVisible === true\` 前置断言是**恒真的检查**（无论候选可不可聚焦都放行）`,
  ).toBe(false);
  expect(
    invisible.backgroundFocusEscaped,
    `臂 D：候选不可渲染时 backgroundFocusEscaped 仍为 ${String(invisible.backgroundFocusEscaped)} ` +
      `⇒ 该读数在本情形下**不是 inert 的函数**（臂 B 已撤掉 inert），即「inert 挡住了背景」这条结论在此处是空的`,
  ).toBe(false);

  await context.close();
});

test('@control 判据2 非空洞性：注入的元素越出视口右边界时 elementsPastViewportRight 非空', async ({ browser }) => {
  test.setTimeout(180_000);
  const log = createLog();
  const context = await browser.newContext({ baseURL: BASE_URL, viewport: { width: 1280, height: 1000 } });
  const page = await context.newPage();

  await registerRealSession(page, 4, '控制臂2');
  await page.goto(`${BASE_URL}/consult`);
  await waitMounted(page);
  await expect(page.getByRole('button', { name: /开始新的日常咨询/ })).toBeVisible({ timeout: 25_000 });
  await page.getByRole('button', { name: /开始新的日常咨询/ }).click();
  await expect(page).toHaveURL(/\/consult\/sessions\/[0-9a-f-]{32,36}/, { timeout: 40_000 });
  await expect(page.locator('#consult-composer')).toBeVisible({ timeout: 25_000 });

  /** 同一次测量里同时取元素级与文档级读数——这是「文档级不敏感」的实证所必需。 */
  const measure = async (): Promise<{ elements: string[]; documentScrollWidth: number; documentClientWidth: number }> => ({
    elements: await page.evaluate(elementsPastViewportRight),
    ...(await page.evaluate(() => ({
      documentScrollWidth: document.documentElement.scrollWidth,
      documentClientWidth: document.documentElement.clientWidth,
    }))),
  });

  // ── 基线臂：现状无溢出 ──
  const baseline = await measure();

  // ── 负面控制臂：注入一个宽度越出视口右边界的元素，其余一切不变 ──
  //
  // 注入位置放在 `.device` **内部**：那才是「外壳内部有横向溢出」的真实形态，
  // 也正是 `.device{overflow:hidden}` 会把它裁掉、从而让文档级读数看不见的那种形态。
  // 放在 body 直下则会撑开文档滚动宽度，测的就不是同一个现象了。
  await page.evaluate(() => {
    const host = document.querySelector('.device-screen') ?? document.body;
    const probe = document.createElement('div');
    probe.id = '__t11_overflow_probe__';
    probe.textContent = 'T11 溢出负面控制臂';
    // 定位到外壳之外：left 足够大 ⇒ 其 rect.right 必然远超视口宽度。
    probe.style.cssText =
      'position:absolute;left:2000px;top:0;width:300px;height:40px;background:#f00;color:#fff;z-index:9999;';
    host.append(probe);
  });
  await page.waitForTimeout(200);
  const ablated = await measure();

  // 收起注入（不留在页面上，避免影响后续臂的截图/几何）。
  await page.evaluate(() => document.querySelector('#__t11_overflow_probe__')?.remove());

  log.record('control-overflow', {
    baseline,
    ablated,
    documentLevelBlind: ablated.documentScrollWidth === baseline.documentScrollWidth,
    expectation:
      'baseline.elements === []（正常路径无溢出）且 ablated.elements 非空（注入越界元素后元素级信号捕捉到它）' +
      '⇒ 链路 3 的 noElementPastViewportRight* 断言不是恒真的。',
    documentLevelEvidence:
      'documentLevelBlind=true 是「(z17)：判据会被自己的布局裁掉」的实证——同一次注入下，' +
      '元素级信号从 0 条变成 1 条，而文档级 scrollWidth 读数**完全不变**（因为注入点在 .device 内部，' +
      '被 .device{overflow:hidden} 裁掉）。这就是为什么判据必须落在元素级。',
  });
  await saveLog(log, 'control-overflow');

  expect(baseline.elements, `基线臂：对话页本来就有元素越界 ⇒ 这条判据没有可证的东西（${JSON.stringify(baseline.elements)}）`).toHaveLength(0);
  expect(
    ablated.elements.length,
    '负面控制臂：注入越出视口右边界的元素后 elementsPastViewportRight 仍为空 ⇒ 链路 3 的元素级判据是恒真的检查',
  ).toBeGreaterThan(0);
  expect(
    ablated.documentScrollWidth,
    `文档级读数在注入后发生了变化（${String(baseline.documentScrollWidth)} → ${String(ablated.documentScrollWidth)}）` +
      `⇒ 本次注入没有落进被 overflow 裁掉的位置，因此它**不能**用来证明「文档级不敏感」。` +
      `须调整注入点（应在外壳内部）后重跑。`,
  ).toBe(baseline.documentScrollWidth);

  await context.close();
});

test('@control 判据3 非空洞性：喂一条合成 5xx 记录时 tally.serverErrors 捕获它且不删原始记录', async () => {
  // 本臂**不需要真实栈**（也因此不需要浏览器）：它直接喂给链路 7 用的同一个
  // `tallyResponses()`。这是有意的——分类器的正确性与「后端能不能产出 5xx」是两件事，
  // 混在一起会让本臂因无关原因失败。
  const log = createLog();
  const records: ConsoleRecord[] = [
    {
      kind: 'response-4xx-5xx',
      // 写入格式由 watchConsole 决定：`${status} ${method} ${url}`。
      text: '401 POST http://localhost:5173/api/auth/session/refresh',
      url: 'http://localhost:5173/login',
      at: new Date().toISOString(),
    },
    {
      kind: 'response-4xx-5xx',
      text: '422 GET http://localhost:5173/api/memory/episodes?cursor=zzz',
      url: 'http://localhost:5173/settings/memory',
      at: new Date().toISOString(),
    },
    {
      kind: 'response-4xx-5xx',
      // 合成的服务端错误：本机实测找不到自然产生的 5xx（见文件头与 fuzz-5xx 侦查）。
      text: '500 POST http://localhost:5173/api/consult/sessions',
      url: 'http://localhost:5173/consult',
      at: new Date().toISOString(),
    },
    {
      kind: 'response-4xx-5xx',
      // 畸形记录：用来证明解析失败**不会被静默丢弃**（否则 5xx 判据会退化成恒真）。
      text: 'this line does not match the采集格式',
      url: 'http://localhost:5173/consult',
      at: new Date().toISOString(),
    },
    {
      kind: 'console-error',
      text: '这不是响应记录，不该进任何 4xx/5xx 桶',
      url: 'http://localhost:5173/consult',
      at: new Date().toISOString(),
    },
  ];

  const tally = tallyResponses(records);

  log.record('control-tally-5xx', {
    tally,
    expectation:
      'serverErrors 恰好 1 条（合成的 500）、clientErrors 2 条（401 + 422）、' +
      'expectedAnonymousRefreshCount === 1、unexpectedClientErrorCount === 1、unparsedCount === 1。',
    boundary:
      '合成记录证明的是**分类器**能把 5xx 认出来；它不证明「真后端真能返回 5xx 并被 Playwright 采集到」。' +
      '后者的依据是 watchConsole 的 response 监听器对任何 status >= 400 都记录（与状态码无关），' +
      '以及链路 7 在真实运行里的 badResponses 实测。',
  });
  await saveLog(log, 'control-tally-5xx');

  expect(tally.serverErrors, `合成的 500 没有被归进 serverErrors：${JSON.stringify(tally.serverErrors)}`).toHaveLength(1);
  expect(tally.serverErrors[0]?.status, 'serverErrors 里那条的状态码不是 500').toBe(500);
  expect(tally.clientErrors, `4xx 桶条数不对：${JSON.stringify(tally.clientErrors)}`).toHaveLength(2);
  expect(
    tally.expectedAnonymousRefreshCount,
    '未登录 session/refresh 的 401 没有被认成预期口径 ⇒ 5xx 判据的排除说明与实际不符',
  ).toBe(1);
  expect(tally.unexpectedClientErrorCount, '预期 401 之外的 4xx 计数不对').toBe(1);
  expect(
    tally.unparsedCount,
    '畸形记录没有被计入 unparsedCount ⇒ 解析失败会被静默丢弃，5xx 判据会退化成恒真的检查',
  ).toBe(1);
  // 未静默过滤：原始记录**一条都不能少**（本函数只分类计数，不删除）。
  expect(records, 'tallyResponses 修改了传入的记录数组 ⇒ 那是过滤而不是分类').toHaveLength(5);
});

/**
 * 判据4（T11-r2 的 P2-2「能红」证明）：链路 7 的**采集器活性**断言不是恒真的检查。
 *
 * 链路 7 新增的断言是「必然 404 的探针必须出现在 `tally.clientErrors` 里」。
 * 它要拦的形态是：**采集器一条 response 都没记** ⇒ `serverErrors` 是空数组 ⇒
 * 5xx 判据**以空数组静默通过**（判据读不到任何东西，却报绿）。
 *
 * 本臂用**差分**（只变一个自变量：采集器挂没挂）把这个形态造出来：
 *   - 臂 M（mutant，采集器未挂）：同一个 404 请求发出的，但那个 sink 上没有任何监听器
 *     ⇒ `clientErrors` 不含该 URL ⇒ **链路 7 的新断言在此必须红**；
 *   - 臂 L（live，采集器已挂）：同一个 URL、同一个请求，采集器挂上 ⇒ 落进 `clientErrors`
 *     ⇒ 断言通过。
 *
 * 两臂之间**唯一**的差别是 `watchConsole` 是否被调用；其余（页面、URL、requests）逐字相同。
 * 这证明该断言度量的正是「采集器活着」这件事，而不是碰巧成立的别的条件。
 *
 * 为什么不需要真实会话：本臂的被测对象是**采集器**，不是鉴权。探针路径在真实后端上
 * 不存在，无论登录与否都是 404；用匿名页可以少消耗一枚一次性邀请码，且不改变结论。
 */
test('@control 判据4 非空洞性：采集器未挂时 404 不落进 clientErrors（⇒ 链路7 的活性断言能红）', async ({ browser }) => {
  test.setTimeout(120_000);
  const log = createLog();
  const probePath = '/api/__t11_collector_liveness_probe__';
  const context = await browser.newContext({ baseURL: BASE_URL, viewport: { width: 1280, height: 1000 } });

  const fetchProbe = async (page: import('@playwright/test').Page): Promise<{ status: number; url: string }> => {
    await page.goto(`${BASE_URL}/login`, { waitUntil: 'domcontentloaded' });
    await waitMounted(page);
    return page.evaluate(async (path: string) => {
      const response = await fetch(path);
      return { status: response.status, url: response.url };
    }, probePath);
  };

  // ── 臂 M（mutant）：采集器**未挂** ⇒ sink 永远为空 ⇒ 活性断言必然红 ──
  const mutantPage = await context.newPage();
  const deadSink: ConsoleRecord[] = [];
  const mutantProbe = await fetchProbe(mutantPage);
  // 给异步投递留出窗口：即便等这么久，未挂监听的 sink 也不该有任何记录。
  await mutantPage.waitForTimeout(3_000);
  const deadTally = tallyResponses(deadSink);

  // ── 臂 L（live）：同一个请求，采集器**已挂** ⇒ 落进 clientErrors ──
  const livePage = await context.newPage();
  const liveSink: ConsoleRecord[] = [];
  watchConsole(livePage, liveSink);
  const liveProbe = await fetchProbe(livePage);
  await expect
    .poll(() => liveSink.filter((record) => record.kind === 'response-4xx-5xx').length, {
      message: '臂 L：采集器已挂，但发出的 404 没有落进 sink ⇒ 本臂的前提不成立（活性断言将永远无法通过）',
      timeout: 10_000,
    })
    .toBeGreaterThan(0);
  const liveTally = tallyResponses(liveSink);

  const deadHits = deadTally.clientErrors.filter((reading) => reading.url.endsWith(probePath));
  const liveHits = liveTally.clientErrors.filter((reading) => reading.url.endsWith(probePath));

  log.record('control-collector-liveness', {
    probePath,
    mutantProbe,
    liveProbe,
    mutantTally: deadTally,
    liveTally,
    deadSinkSize: deadSink.length,
    liveSinkSize: liveSink.length,
    arms: {
      M_collector_absent: `采集器未挂 ⇒ clientErrors 命中探针 ${String(deadHits.length)} 条、serverErrors 为空数组` +
        `——这正是「零条 response 记录时 5xx 判据静默通过」的形态 ⇒ 链路 7 的活性断言在此会红`,
      L_collector_present: `同一个请求、采集器已挂 ⇒ clientErrors 命中探针 ${String(liveHits.length)} 条 ⇒ 活性断言通过`,
    },
    boundary:
      '本臂证明「活性断言度量的确实是采集器是否在记录」，自变量只有 watchConsole 挂没挂。' +
      '它不证明链路 7 那一轮里探针 404 一定发生——那由链路 7 自身对 livenessProbe.status === 404 的断言承担。',
  });
  await saveLog(log, 'control-collector-liveness');

  await context.close();

  // 前提：两臂打的是同一个必然 404 的路径。
  expect(mutantProbe.status, `臂 M：探针路径未返回 404（实际 ${String(mutantProbe.status)}）⇒ 本臂前提不成立`).toBe(404);
  expect(liveProbe.status, `臂 L：探针路径未返回 404（实际 ${String(liveProbe.status)}）⇒ 本臂前提不成立`).toBe(404);

  // 臂 M：采集器未挂 ⇒ 探针**没有**落进 clientErrors。
  // 这一条就是「能红」：链路 7 的断言 `livenessInTally.length > 0` 在此形态下不成立。
  expect(
    deadSink,
    `臂 M：未挂采集器却收到了 ${String(deadSink.length)} 条记录 ⇒ 本臂无效（有别的监听器在写同一个数组）`,
  ).toHaveLength(0);
  expect(
    deadHits,
    `臂 M：采集器未挂，clientErrors 却命中了探针 ${String(deadHits.length)} 条 ` +
      `⇒ 链路 7 的活性断言在本形态下**仍然通过**，即它是一条恒真的检查（本项目明令禁止）`,
  ).toHaveLength(0);
  expect(
    deadTally.serverErrors,
    '臂 M：采集器未挂时 serverErrors 应为空数组——那正是 5xx 判据「静默通过」的入口（本断言固化该形态）',
  ).toHaveLength(0);

  // 臂 L：采集器挂上后，探针**必须**落进 clientErrors ⇒ 活性断言通过。
  expect(
    liveHits,
    `臂 L：采集器已挂，但 clientErrors 未命中探针（全量：${JSON.stringify(liveTally.clientErrors)}）` +
      `⇒ 链路 7 的活性断言在正确形态下也无法通过，那是一条假红`,
  ).not.toHaveLength(0);
  expect(liveHits[0]?.status, '臂 L：命中的那条状态码不是 404').toBe(404);
});
