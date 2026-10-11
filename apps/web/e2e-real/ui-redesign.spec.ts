/** UI 重构真栈验证：浏览器请求不被拦截，数据经实际业务入口写入与读取。
 *
 * ⚠ 两条**运行前提**（都是本文件的实测形态，不是理论顾虑）——它们决定了「不能只跑其中一条用例」：
 *
 *   1. **用例之间有顺序依赖**：第 2 条（档案创建对象 + 补充 + 纠正）先建出对象与记录，
 *      第 4 条（分页）与第 5 条（删除）都依赖它——分页那条直接取 `objects.items[0]`，
 *      删除那条最后一行还断言「第 2 条写下的更正仍在」。`beforeEach` 只补登同一账号的会话，
 *      **不补对象**。因此按 `--grep` 单跑第 4/5 条会以「找不到对象/找不到更正记录」变红，
 *      那**不是产品缺陷**，是本前提未满足。
 *   2. **每轮写入的残余**：一轮完整 @ui-live 会在本次运行新建的账号下留下 1 个对象、
 *      1 条更正记录与 21 条分页验证条目（第 4 条刻意造到超过首批上限）。用例只删自己
 *      新建的那条临时条目（第 5 条），**其余刻意保留**——它们是「更正后仍可读取」这条
 *      断言的证据。因为账号按 `UI_REAL_ACCOUNT` 或时间戳生成，残余不会滚进下一轮。
 *
 * 结论：把它当**一整组**跑（`--grep "@ui-live"`），不要按用例名挑着跑；产物与账号隔离都按这一点设计。
 */
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { expect, test, type BrowserContext, type Page } from '@playwright/test';

import { BASE_URL, OUT_DIR, installSseTap, readSseTap, waitMounted, watchConsole, type ConsoleRecord } from './support/real';

const stamp = Date.now();
const account = process.env.UI_REAL_ACCOUNT ?? `ui-real-${String(stamp)}`;
const password = process.env.UI_REAL_PASSWORD ?? '';
const invite = process.env.UI_REAL_INVITE_CODE ?? '';
const objectName = 'UI 验证对象';
const records: ConsoleRecord[] = [];
let context: BrowserContext;
let authenticated = false;

async function open(path: string, width = 390): Promise<Page> {
  expect(authenticated, '真实注册与会话必须先建立').toBe(true);
  const page = await context.newPage();
  await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
  watchConsole(page, records);
  await page.goto(BASE_URL + path);
  await waitMounted(page);
  return page;
}

async function screenshot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: resolve(OUT_DIR, 'shots', `ui-${name}.png`), animations: 'disabled' });
}

test.beforeAll(async ({ browser }) => {
  await mkdir(resolve(OUT_DIR, 'shots'), { recursive: true });
  context = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: 'zh-CN' });
});
test.afterAll(async () => { await context.close(); });
// Playwright 要求首参为解构模式；本钩子只读取第二参的用例名。
// oxlint-disable-next-line eslint/no-empty-pattern
test.beforeEach(async ({}, info) => {
  // 某条用例失败后 Playwright 会重建 worker；后续检查重新登录同一测试账号。
  if (authenticated || info.title === '真实邀请码注册、httpOnly 会话与首页初始状态') return;
  const page = await context.newPage();
  try {
    await page.goto(BASE_URL + '/login');
    await page.getByLabel('账号名', { exact: true }).fill(account);
    await page.getByLabel('密码', { exact: true }).fill(password);
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await expect(page).toHaveURL(BASE_URL + '/');
    authenticated = true;
  } finally { await page.close(); }
});

test.describe('@ui-live UI 重构真实依赖', () => {
  test('真实邀请码注册、httpOnly 会话与首页初始状态', async () => {
    expect(invite).not.toBe('');
    expect(password).not.toBe('');
    expect(account, '真实回归必须使用不含 @ 的账号名，防止重新引入邮箱格式要求').not.toContain('@');
    const page = await context.newPage();
    watchConsole(page, records);
    try {
      await page.goto(BASE_URL + '/login');
      await page.getByRole('button', { name: '已有邀请码？注册账号' }).click();
      await page.getByLabel('账号名', { exact: true }).fill(account);
      await page.getByLabel('密码', { exact: true }).fill(password);
      await page.getByLabel('邀请码', { exact: true }).fill(invite);
      const response = page.waitForResponse((item) => item.url().endsWith('/api/auth/signup'));
      await page.getByRole('button', { name: '注册', exact: true }).click();
      const signup = await response;
      expect(signup.status()).toBe(200);
      expect((await signup.json() as { status: string }).status).toBe('OK');
      await expect(page).toHaveURL(BASE_URL + '/');
      const cookies = await context.cookies();
      expect(cookies.some((cookie) => cookie.name === 'sAccessToken' && cookie.httpOnly)).toBe(true);
      authenticated = true;
      await expect(page.getByLabel('想聊的事情')).toBeVisible();
      await expect(page.getByRole('button', { name: '进入对话' })).toBeDisabled();
      await page.getByRole('link', { name: /^资料库/ }).click();
      await expect(page).toHaveURL(BASE_URL + '/cases?section=knowledge');
      await expect(page.locator('.sp-title')).toHaveText('资料库');
      await expect(page.getByRole('searchbox', { name: '搜索资料' })).toBeVisible();
      await page.getByRole('link', { name: '← 返回' }).click();
      await expect(page).toHaveURL(BASE_URL + '/');
      await page.getByRole('link', { name: '使用说明' }).click();
      await page.getByRole('link', { name: '← 返回' }).click();
      await expect(page).toHaveURL(BASE_URL + '/');
      await screenshot(page, 'home-mobile');
    } finally { await page.close(); }
  });

  test('档案经 UI 创建对象、补充与纠正，刷新后数据库记录仍可读取', async () => {
    const page = await open('/profile');
    try {
      await page.getByRole('button', { name: '+ 新建对象', exact: true }).click();
      const sheet = page.getByRole('dialog', { name: '给 TA 起个称呼' });
      await sheet.getByRole('textbox', { name: '称呼' }).fill(objectName);
      const created = page.waitForResponse((response) => response.url().endsWith('/api/profile/objects') && response.request().method() === 'POST');
      await sheet.getByRole('button', { name: '创建', exact: true }).click();
      expect((await created).status()).toBe(201);
      await expect(sheet).toBeHidden();
      await page.getByRole('button', { name: '补充一条', exact: true }).last().click();
      let form = page.getByRole('heading', { name: '补充一条记录' }).locator('..');
      await form.getByRole('combobox', { name: '领域' }).selectOption('communication');
      await form.getByRole('textbox', { name: '主题' }).fill('沟通节奏');
      await form.getByRole('textbox', { name: '描述' }).fill('UI 验证记录：先等三秒，再继续说下一句。');
      const saved = page.waitForResponse((response) => /\/api\/profile\/objects\/[^/]+\/items$/.test(response.url()) && response.request().method() === 'POST');
      await form.getByRole('button', { name: '保存', exact: true }).click();
      expect((await saved).status()).toBe(201);
      await page.reload();
      await expect(page.getByText('UI 验证记录：先等三秒，再继续说下一句。').first()).toBeVisible();
      await screenshot(page, 'profile-mobile');
      await page.getByRole('button', { name: /^纠正：/ }).first().click();
      const heading = page.getByRole('heading', { name: '新增一条更正' });
      await expect(heading).toBeFocused();
      form = heading.locator('..');
      await expect(form.getByRole('combobox', { name: '领域' })).toBeDisabled();
      await form.getByRole('textbox', { name: '描述' }).fill('UI 验证更正：先等五秒，再继续说下一句。');
      const corrected = page.waitForResponse((response) => response.url().endsWith('/correct') && response.request().method() === 'POST');
      await form.getByRole('button', { name: '纠正', exact: true }).click();
      expect((await corrected).status()).toBe(201);
      await page.reload();
      await expect(page.getByText('UI 验证更正：先等五秒，再继续说下一句。').first()).toBeVisible();
      await expect(page.getByText('已更正', { exact: true })).toBeVisible();
      await page.setViewportSize({ width: 1280, height: 1000 });
      await screenshot(page, 'profile-desktop');
    } finally { await page.close(); }
  });

  test('真实摄取案例正文与来源展开，关键词检索和深链可读取', async () => {
    const page = await open('/cases');
    try {
      const title = '从强迫到尊重：ASD儿童家庭干预中的节奏调整与规则建立';
      const row = page.locator('article.list-row').filter({ hasText: title });
      await expect(row).toBeVisible();
      await expect(row.locator('.lr-sub')).not.toContainText(/title[:：]|scenario[:：]/);
      const control = row.getByRole('button', { name: new RegExp(title) });
      const expanded = page.waitForResponse((response) => response.url().includes('/api/library/items?') && response.url().includes('expand='));
      await control.click();
      const expansionResponse = await expanded;
      expect(expansionResponse.status()).toBe(200);
      const expansion = await expansionResponse.json() as { items: { item_id: string; title: string }[] };
      const itemId = expansion.items.find((item) => item.title === title)?.item_id ?? '';
      expect(itemId).not.toBe('');
      await expect(control).toHaveAttribute('aria-expanded', 'true');
      await expect(row.locator('h3').first()).toBeVisible();
      await row.getByText('来源与适用范围', { exact: true }).click();
      await expect(row.getByText(/项目所有者核准/)).toBeVisible();
      await screenshot(page, 'case-expanded-mobile');
      const searched = page.waitForResponse((response) => response.url().includes('/api/library/items?') && new URL(response.url()).searchParams.get('query') === '节奏');
      await page.getByPlaceholder('搜索案例').fill('节奏');
      const searchResponse = await searched;
      expect(searchResponse.status()).toBe(200);
      const searchResult = await searchResponse.json() as { items: { item_id: string }[] };
      expect(searchResult.items.some((item) => item.item_id === itemId)).toBe(true);
      await expect(page.locator('article.list-row').filter({ hasText: title })).toBeVisible();
      const located = page.waitForResponse((response) => response.url().endsWith('/api/library/items/' + itemId));
      await page.goto(BASE_URL + '/cases?item=' + encodeURIComponent(itemId));
      expect((await located).status()).toBe(200);
      await expect(page.locator('article').filter({ hasText: title }).first()).toBeVisible();
      await page.setViewportSize({ width: 1280, height: 1000 });
      await screenshot(page, 'cases-desktop');
    } finally { await page.close(); }
  });

  test('档案删除确认执行真实删除，只删除本用例新建的临时条目', async () => {
    const page = await open('/profile');
    try {
      await page.getByRole('button', { name: '补充一条', exact: true }).last().click();
      const form = page.getByRole('heading', { name: '补充一条记录' }).locator('..');
      await form.getByRole('textbox', { name: '主题' }).fill('可删除的 UI 验证条目');
      await form.getByRole('textbox', { name: '描述' }).fill('本条仅用于确认真实删除链路。');
      const created = page.waitForResponse((response) => /\/api\/profile\/objects\/[^/]+\/items$/.test(response.url()) && response.request().method() === 'POST');
      await form.getByRole('button', { name: '保存', exact: true }).click();
      const response = await created;
      expect(response.status()).toBe(201);
      const saved = await response.json() as { item_id: string };
      const row = page.locator('article.list-row').filter({ hasText: '可删除的 UI 验证条目' });
      await row.getByRole('button', { name: '删除', exact: true }).click();
      const dialog = page.getByRole('dialog', { name: '删除这条记录？' });
      await expect(dialog).toBeVisible();
      const removed = page.waitForResponse((item) => item.url().endsWith('/api/profile/items/' + saved.item_id) && item.request().method() === 'DELETE');
      await dialog.getByRole('button', { name: '删除', exact: true }).click();
      expect((await removed).status()).toBe(200);
      await expect(row).toHaveCount(0);
      await page.reload();
      await expect(page.getByText('可删除的 UI 验证条目', { exact: true })).toHaveCount(0);
      await expect(page.getByText('UI 验证更正：先等五秒，再继续说下一句。').first()).toBeVisible();
    } finally { await page.close(); }
  });

  test('应急表单答案保留与常驻提交实际可点击，不提交虚构医疗事实', async () => {
    const page = await open('/consult/emergency');
    try {
      await page.getByRole('button', { name: '跳过这题', exact: true }).click();
      await page.getByRole('button', { name: '上一题', exact: true }).click();
      await expect(page.getByText(/本题已跳过（按未排除处理）/)).toBeVisible();
      await page.getByRole('button', { name: '← 退出应急' }).click();
      const dialog = page.getByRole('dialog', { name: '退出现场采集？' });
      await expect(dialog).toBeVisible();
      await dialog.getByRole('button', { name: '继续填写' }).click();
      const button = page.getByRole('button', { name: '提交，开始分析' });
      await expect.poll(() => button.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        return element.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2));
      })).toBe(true);
      await screenshot(page, 'emergency-mobile');
    } finally { await page.close(); }
  });

  test('档案超过首批上限后仍能读取后续真实记录', async () => {
    const page = await open('/profile');
    try {
      const seeded = await page.evaluate(async () => {
        const objects = await fetch('/api/profile/objects').then((response) => response.json()) as { items: { id: string }[] };
        const id = objects.items[0]?.id;
        if (!id) return { statuses: [], count: 0, loaded: 0 };
        const statuses: number[] = [];
        for (let index = 0; index < 21; index += 1) {
          const response = await fetch('/api/profile/objects/' + id + '/items', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ domain: 'other', topic: '分页验证条目 ' + index, description: '仅用于本地分页验证 ' + index }),
          });
          statuses.push(response.status);
        }
        return { statuses, count: statuses.length };
      });
      expect(seeded.count).toBe(21);
      expect(seeded.statuses.every((status) => status === 201)).toBe(true);
      await page.reload();
      await expect(page.getByRole('button', { name: '加载更多记录' })).toBeVisible();
      const before = await page.locator('article.list-row').count();
      const loaded = page.waitForResponse((response) => response.url().includes('/api/profile/objects/') && new URL(response.url()).searchParams.has('cursor'));
      await page.getByRole('button', { name: '加载更多记录' }).click();
      expect((await loaded).status()).toBe(200);
      await expect.poll(() => page.locator('article.list-row').count()).toBeGreaterThan(before);
      await expect(page.getByRole('button', { name: '加载更多记录' })).toHaveCount(0);
    } finally { await page.close(); }
  });

  test('首页草稿创建真实会话，发送产生真实模型 SSE，历史刷新可恢复', async () => {
    test.setTimeout(300_000);
    const page = await open('/', 1280);
    try {
      await installSseTap(page);
      // addInitScript 在下一次文档加载才生效，必须先重载，再经 SPA 入口进入会话。
      await page.reload();
      const message = '你好，请用一句话说明你能帮我做什么。';
      await page.getByLabel('想聊的事情').fill(message);
      const created = page.waitForResponse((response) => response.url().endsWith('/api/consult/sessions') && response.request().method() === 'POST');
      await page.getByRole('button', { name: '进入对话' }).click();
      expect((await created).status()).toBe(201);
      await expect(page).toHaveURL(/\/consult\/sessions\/[0-9a-f-]+$/);
      const composer = page.getByLabel('发送消息');
      await expect(composer).toHaveValue(message);
      const sent = page.waitForResponse((response) => response.url().endsWith('/messages') && response.request().method() === 'POST');
      await page.getByRole('button', { name: '发送', exact: true }).click();
      expect((await sent).status()).toBe(202);
      await expect.poll(async () => (await readSseTap(page)).events.some((event) => event.event === 'text_delta'), { timeout: 90_000 }).toBe(true);
      await expect.poll(async () => (await readSseTap(page)).events.some((event) => event.event === 'run_finished'), { timeout: 180_000 }).toBe(true);
      const tap = await readSseTap(page);
      expect(tap.status).toBe(200);
      expect(tap.contentType).toContain('text/event-stream');
      expect(tap.events.some((event) => event.event === 'run_failed')).toBe(false);
      await expect(page.locator('.msg-doc')).not.toHaveText('');
      await screenshot(page, 'chat-desktop');
      await page.reload();
      await expect(page.locator('.bubble-user:not(.skeleton)').first()).toContainText(message);
      await expect(page.locator('.msg-doc').first()).not.toHaveText('');
      await page.setViewportSize({ width: 390, height: 844 });
      await screenshot(page, 'chat-mobile');
      const width = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
      expect(width.scroll).toBeLessThanOrEqual(width.client);
    } finally { await page.close(); }
  });

  test('真实记忆读取、设置退出与重新登录，未登录接口恢复 401', async () => {
    const page = await open('/settings/memory');
    try {
      await expect(page.getByText('还没有记录', { exact: true })).toBeVisible();
      await screenshot(page, 'memory-mobile');
      await page.goto(BASE_URL + '/settings');
      await expect(page.getByRole('heading', { name: account, exact: true })).toBeVisible();
      await page.reload();
      await expect(page.getByRole('heading', { name: account, exact: true })).toBeVisible();
      await expect(page.getByRole('link', { name: /使用说明/ })).toBeVisible();
      await screenshot(page, 'settings-mobile');
      await page.getByRole('button', { name: '退出登录' }).click();
      const dialog = page.getByRole('dialog', { name: '退出登录？' });
      await expect(dialog).toBeVisible();
      await dialog.getByRole('button', { name: '退出', exact: true }).click();
      await expect(page).toHaveURL(BASE_URL + '/login');
      expect((await context.cookies()).some((cookie) => cookie.name === 'sAccessToken')).toBe(false);
      const boundary = await context.request.get(BASE_URL + '/api/consult/sessions');
      expect(boundary.status()).toBe(401);
      await page.getByLabel('账号名', { exact: true }).fill(account);
      await page.getByLabel('密码', { exact: true }).fill(password);
      await page.getByRole('button', { name: '登录', exact: true }).click();
      await expect(page).toHaveURL(BASE_URL + '/');
      expect(records.filter((record) => record.kind === 'pageerror' || record.kind === 'response-4xx-5xx' && record.text.startsWith('5'))).toEqual([]);
    } finally { await page.close(); }
  });
});
