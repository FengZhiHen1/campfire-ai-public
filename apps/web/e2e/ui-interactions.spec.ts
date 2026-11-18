/** 全页面重构的关键状态：真实浏览器交互与截图，使用现有隔离夹具。 */
import { mkdir, readFile } from 'node:fs/promises';
import { expect, test, type Page, type TestInfo } from '@playwright/test';

import { actionCardEvent, runFinished, runStarted, textDelta } from '../src/features/consult/test/fixtures';
import type { RunEvent } from '../src/shared/types/sse';
import { PAGE_SHOTS, type PageShot } from './support/fixtures';
import { readPngSize, sha256Of } from './support/manifest';
import { expectNoUnmatchedApi } from './support/network';
import { expandForFullPage, measureOverflow } from './support/neutralise';
import { openPage } from './support/page-open';
import {
  STATE_SHOTS_DIR,
  isStateShotName,
  isViewportName,
  stateShotPath,
  toRepoRelative,
  type StateShotName,
} from './support/paths';
import { readRunId } from './support/runid';
import { writeStateSidecar } from './support/state-shots';

function shotFor(name: string): PageShot {
  const shot = PAGE_SHOTS.find((candidate) => candidate.name === name);
  if (shot === undefined) throw new Error(`没有页面夹具：${name}`);
  return shot;
}

test('资料库入口、分区和返回来源一致，说明页可直接进入功能', async ({ page }, info) => {
  const home = shotFor('home');
  const { ledger } = await openPage(page, { ...home, fixtures: [{ method: 'GET', path: '/api/library/items', body: { library: 'knowledge', items: [], next_cursor: null } }] }, info);
  const link = page.getByRole('link', { name: /^资料库/ });
  await expect(link.locator('strong')).toHaveText('资料库');
  await expect(page.getByText('资料库说明', { exact: true })).toHaveCount(0);
  await link.click();
  await expect(page.locator('.sp-title')).toHaveText('资料库');
  const search = page.getByRole('searchbox', { name: '搜索资料' });
  await expect(search).toBeVisible();
  await expect(search).toHaveCSS('border-top-width', '0px');
  await search.focus();
  await expect(search).toHaveCSS('box-shadow', 'none');
  await expect(search.locator('..')).not.toHaveCSS('box-shadow', 'none');
  await expect(page.getByText('资料库还在准备中')).toBeVisible();
  await page.getByRole('link', { name: '← 返回' }).click();
  await expect(page.getByLabel('想聊的事情')).toBeVisible();
  await page.getByRole('link', { name: '使用说明' }).click();
  await expect(page.getByRole('link', { name: '开始应急咨询 →' })).toHaveAttribute('href', '/consult/emergency');
  await page.getByRole('link', { name: '← 返回' }).click();
  await expect(page.getByLabel('想聊的事情')).toBeVisible();
  expectNoUnmatchedApi(ledger);
});

/**
 * 截一张关键状态图，并写下它的 sidecar。
 *
 * 状态名只接受 `STATE_SHOTS` 里声明过的值：写错名字、或顺手加一张没声明的图会**当场失败**，
 * 而不是留下一张没有清单、也没人核对的 PNG。另一半判据（每个声明的状态都真的产出了、
 * 且都是本轮产物）由 `states.spec.ts` 在两条视口 project 都跑完后统一核对——
 * 两份合起来才是「声明 ⇔ 产物」。
 *
 * 落盘即复算：sidecar 里的 sha256/字节数来自对刚落盘 PNG 的实读，不留「我以为写成了」的值。
 */
async function capture(page: Page, info: TestInfo, name: StateShotName, full = false): Promise<void> {
  if (!isStateShotName(name)) throw new Error(`未声明的关键状态图：${String(name)}`);
  // project 名形如 content-mobile / content-desktop；用 isViewportName 收窄而不裸用 as。
  const viewport = info.project.name.replace(/^content-/, '');
  if (!isViewportName(viewport)) throw new Error(`没有视口夹具：${info.project.name}`);
  const filePath = stateShotPath(name, viewport);
  await mkdir(STATE_SHOTS_DIR, { recursive: true });

  let contentHeightPx: number | null = null;
  if (full) {
    const expanded = await expandForFullPage(page, await measureOverflow(page));
    try {
      await expanded.assertExpanded();
      await page.screenshot({ path: filePath, animations: 'disabled', fullPage: true });
      // 用与截图基建同一口径的内容高（`expandForFullPage` 的实测值），不另算一个数。
      contentHeightPx = expanded.result.contentHeightPx;
    } finally {
      await expanded.restore();
      await expanded.assertRestored();
    }
  } else {
    await page.screenshot({ path: filePath, animations: 'disabled' });
  }

  const bytes = await readFile(filePath);
  const size = readPngSize(bytes);
  await writeStateSidecar({
    state: name,
    viewport,
    file: toRepoRelative(filePath),
    absolutePath: filePath,
    runId: await readRunId(),
    sha256: sha256Of(bytes),
    bytes: bytes.byteLength,
    width: size.width,
    height: size.height,
    fullPage: full,
    contentHeightPx,
  });
}

test('案例正文与完整来源各自展开，保留真实阅读内容和虚构标识', async ({ page }, info) => {
  const { ledger, pageProblems } = await openPage(page, shotFor('cases'), info);
  const row = page.locator('article.list-row').first();
  const control = row.getByRole('button', { name: /超市里坐下不走/ });
  await expect(control).toHaveAttribute('aria-expanded', 'false');
  await control.click();
  await expect(control).toHaveAttribute('aria-expanded', 'true');
  await expect(row.getByRole('heading', { name: '当时的情境' })).toBeVisible();
  await expect(row.getByText('记录中的做法')).toBeVisible();
  await row.getByText('来源与适用范围', { exact: true }).click();
  await expect(row.getByText(/项目所有者核准/)).toBeVisible();
  await expect(row.locator('dd').filter({ hasText: /学龄前/ })).toBeVisible();
  await expect(page.getByText('虚构样例', { exact: true })).toBeVisible();
  await capture(page, info, 'case-expanded', true);
  await control.click();
  await expect(control).toHaveAttribute('aria-expanded', 'false');
  await expect(row.getByRole('heading', { name: '当时的情境' })).toBeHidden();
  expectNoUnmatchedApi(ledger);
  expect(pageProblems).toEqual([]);
});

test('档案纠正定位到表单，删除确认可取消，候选不被自动确认', async ({ page }, info) => {
  const { ledger, pageProblems } = await openPage(page, shotFor('profile'), info);
  await page.getByRole('button', { name: /^纠正：/ }).first().click();
  const heading = page.getByRole('heading', { name: '新增一条更正' });
  await expect(heading).toBeFocused();
  await expect(page.getByRole('textbox', { name: '主题' })).toHaveValue('需要留出回应的空档');
  await expect(page.getByRole('combobox', { name: '领域' })).toBeDisabled();
  await capture(page, info, 'profile-correction');
  const form = heading.locator('..');
  await form.getByRole('button', { name: '取消', exact: true }).click();
  await page.getByRole('button', { name: '删除', exact: true }).first().click();
  const dialog = page.getByRole('dialog', { name: '删除这条记录？' });
  await expect(dialog).toBeVisible();
  await capture(page, info, 'profile-confirm');
  await dialog.getByRole('button', { name: '取消' }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText('待确认 · AI 归纳', { exact: true })).toBeVisible();
  expect(ledger.records.filter((record) => ['POST', 'PATCH', 'DELETE'].includes(record.method))).toEqual([]);
  expectNoUnmatchedApi(ledger);
  expect(pageProblems).toEqual([]);
});

test('设置帮助入口可达，退出确认遮住背景且支持 Escape 关闭', async ({ page }, info) => {
  const { ledger, pageProblems } = await openPage(page, shotFor('settings'), info);
  await expect(page.getByRole('link', { name: /使用说明/ })).toHaveAttribute('href', '/guide');
  const trigger = page.getByRole('button', { name: '退出登录' });
  await trigger.click();
  const dialog = page.getByRole('dialog', { name: '退出登录？' });
  await expect(dialog).toBeVisible();
  const button = dialog.getByRole('button', { name: '退出', exact: true });
  // 确认单有有限进入动画；检查稳定后真实点击命中，不能只凭 visible 判可操作。
  await expect.poll(() => button.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return element.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2));
  })).toBe(true);
  await capture(page, info, 'settings-confirm');
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
  expectNoUnmatchedApi(ledger);
  expect(pageProblems).toEqual([]);
});

test('应急长题滚动后提交仍可触达，勾选和回退保留答案', async ({ page }, info) => {
  const { ledger, pageProblems } = await openPage(page, shotFor('emergency'), info);
  await page.getByRole('checkbox').first().check();
  const selectedValue = await page.getByRole('checkbox').first().getAttribute('value');
  await page.getByRole('button', { name: '下一题', exact: true }).click();
  await page.getByRole('button', { name: '上一题', exact: true }).click();
  await expect(page.locator(`input[value="${selectedValue}"]`)).toBeChecked();
  const submit = page.getByRole('button', { name: '提交，开始分析' });
  const hit = await submit.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return element.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2));
  });
  expect(hit).toBe(true);
  // 屏底控制区里「跳过这题 / 下一题」必须同处一行：换行会让两个按钮各占一行，
  // 拇指区的单手可达性随之变差（本页的目标是「10 秒内能提交」）。
  // 判据取两个按钮的 y 相等，而不是按钮高度——换行时 y 会明显错开，单行内的行高差异不会。
  // 容差 2px 与 CSS_LAYOUT_TOLERANCE_PX 同量级（吸收子像素布局的取整差）。
  const skipBox = await page.getByRole('button', { name: '跳过这题', exact: true }).boundingBox();
  const nextBox = await page.getByRole('button', { name: '下一题', exact: true }).boundingBox();
  expect(skipBox, '跳过按钮没有布局盒').not.toBeNull();
  expect(nextBox, '下一题按钮没有布局盒').not.toBeNull();
  expect(
    Math.abs((skipBox?.y ?? 0) - (nextBox?.y ?? 0)),
    '跳过与下一题不在同一行：屏底控制区换行了，拇指区单手可达性变差',
  ).toBeLessThanOrEqual(2);
  await capture(page, info, 'emergency-selected');
  await page.getByRole('button', { name: '← 退出应急' }).click();
  const dialog = page.getByRole('dialog', { name: '退出现场采集？' });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: '继续填写' }).click();
  await expect(page.locator(`input[value="${selectedValue}"]`)).toBeChecked();
  expectNoUnmatchedApi(ledger);
  expect(pageProblems).toEqual([]);
});

test('首页草稿进入空会话，使用者主动发送前不启动咨询', async ({ page }, info) => {
  const sessionId = 'sess-new-preview';
  const { ledger } = await openPage(page, {
    ...shotFor('home'),
    fixtures: [{
      method: 'POST', path: '/api/consult/sessions', status: 201,
      body: { session_id: sessionId, support_object_id: null, onboarding_pending: false },
    }, {
      method: 'GET', path: `/api/consult/sessions/${sessionId}/messages`,
      body: { session_id: sessionId, messages: [] },
    }],
  }, info);
  const draft = '我想准备下一次外出。';
  await page.getByRole('textbox', { name: '想聊的事情' }).fill(draft);
  await page.getByRole('button', { name: '进入对话' }).click();
  await expect(page.getByRole('textbox', { name: '发送消息' })).toHaveValue(draft);
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeEnabled();
  expect(ledger.records.filter((record) => record.method === 'POST').map((record) => record.pathname)).toEqual(['/api/consult/sessions']);
  await capture(page, info, 'chat-empty');
  expectNoUnmatchedApi(ledger);
});

test('对话过程与依据独立展开，正文和常驻输入器保留', async ({ page }, info) => {
  const { ledger, pageProblems } = await openPage(page, shotFor('chat'), info);
  const process = page.locator('.reasoning-row');
  await expect(process).toHaveCount(1);
  await expect(process.getByText('查阅案例 · 已结束')).toBeHidden();
  await process.locator('summary').press('Enter');
  await expect(process.getByText('查阅案例 · 已结束')).toBeVisible();
  await page.locator('.citation-block > summary').click();
  await expect(page.getByLabel('发送消息')).toBeVisible();
  await expect(page.locator('.msg-doc')).toContainText('先不劝');
  await capture(page, info, 'chat-sources', true);
  expectNoUnmatchedApi(ledger);
  expect(pageProblems).toEqual([]);
});

if (process.env.RECORD_CONSULT_DISCLOSURE === '1') test.use({ video: 'on' });

test.describe('对话过程交互', () => {
  test('过程从生成到完成，展开和收起维持阅读位置', async ({ page }, info) => {
    const chat = shotFor('chat');
    const sessionId = 'process-preview';
    const runId = 'process-run';
    const messagesPath = `/api/consult/sessions/${sessionId}/messages`;
    await page.addInitScript((streamPath) => {
      const realFetch = window.fetch.bind(window);
      window.fetch = (input, init) => {
        const url = input instanceof Request ? input.url : String(input);
        if (new URL(url, location.origin).pathname !== streamPath) return realFetch(input, init);
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            const encoder = new TextEncoder();
            let sequence = 0;
            window.addEventListener('fixture-consult-frame', (event) => {
              const frame = (event as CustomEvent<{ type: string }>).detail;
              sequence += 1;
              controller.enqueue(encoder.encode(`id: ${sequence}\nevent: ${frame.type}\ndata: ${JSON.stringify(frame)}\n\n`));
              if (frame.type === 'run_finished') controller.close();
            });
            document.documentElement.dataset.fixtureStream = 'ready';
          },
        });
        return Promise.resolve(new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }));
      };
    }, `/api/consult/runs/${runId}/stream`);
    const { ledger, pageProblems } = await openPage(page, {
      ...chat,
      path: `/consult/sessions/${sessionId}`,
      fixtures: [
        { method: 'GET', path: messagesPath, body: { session_id: sessionId, messages: [] } },
      ],
    }, info);
    await page.route((url) => url.pathname === messagesPath, async (route) => {
      if (route.request().method() !== 'POST') return route.fallback();
      await route.fulfill({ status: 202, json: { session_id: sessionId, run_id: runId } });
    });
    const emit = (frames: RunEvent[]) => page.evaluate((values) => {
      for (const detail of values) window.dispatchEvent(new CustomEvent('fixture-consult-frame', { detail }));
    }, frames);
    const previewPause = () => process.env.RECORD_CONSULT_DISCLOSURE === '1'
      ? page.waitForTimeout(950) : Promise.resolve();
    const composer = page.getByRole('textbox', { name: '发送消息' });
    await composer.fill('带孩子去图书馆之前，可以做哪些准备？');
    await previewPause();
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await expect(page.locator('html')).toHaveAttribute('data-fixture-stream', 'ready');
    await emit([
      { ...runStarted([], runId), session_id: sessionId },
      { type: 'reasoning_delta', delta: '先区分出门前能准备的事，以及到现场后可以调整的安排。' },
      { type: 'tool_call_started', tool_name: 'search_cases', call_id: 'case-lookup' },
    ]);
    const processRow = page.locator('.reasoning-row');
    const toggle = processRow.locator('summary');
    await expect(toggle).toHaveText('正在查阅案例…');
    await expect(processRow).not.toHaveAttribute('open');
    await previewPause();
    await emit([
      { type: 'tool_call_finished', tool_name: 'search_cases', call_id: 'case-lookup', ok: true, error_code: null, summary: '查到一条关于熟悉陌生环境的记录。' },
      textDelta('可以先一起看张图书馆的照片，从孩子熟悉的事物聊起。'),
      textDelta('\n\n到馆后，先在入口停一下，再一起找安静的座位。'),
      runFinished(),
    ]);
    await expect(toggle).toHaveText('思考过程');
    const initialY = (await toggle.boundingBox())?.y ?? -1000;
    await previewPause();
    await toggle.click();
    await expect(processRow.getByText('查到一条关于熟悉陌生环境的记录。')).toBeVisible();
    await expect.poll(async () => Math.abs(((await toggle.boundingBox())?.y ?? 0) - initialY)).toBeLessThanOrEqual(2);
    await previewPause();
    await toggle.click();
    await expect(processRow.getByText('查到一条关于熟悉陌生环境的记录。')).toBeHidden();
    await expect(composer).toBeVisible();
    await previewPause();
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await toggle.press('Enter');
    await expect(processRow).toHaveAttribute('open', '');
    expect(await processRow.evaluate((node) => getComputedStyle(node, '::details-content').transitionDuration)).toBe('0s');
    expectNoUnmatchedApi(ledger);
    expect(pageProblems).toEqual([]);
  });
});

test('应急历史中最新行动卡可读，旧卡明确标记过期', async ({ page }, info) => {
  const chat = shotFor('chat');
  const sessionId = chat.path.split('/').at(-1);
  const { ledger, pageProblems } = await openPage(page, {
    ...chat,
    fixtures: [{
      method: 'GET',
      path: `/api/consult/sessions/${sessionId}/messages`,
      body: {
        session_id: sessionId,
        messages: [{ id: 'prior-plan', role: 'assistant', parts: [actionCardEvent()] }, {
          id: 'current-plan',
          role: 'assistant',
          parts: [actionCardEvent({ card_id: 'card-2', title: '现场行动卡 · 最新评估' })],
        }],
      },
    }],
  }, info);
  const cards = page.locator('.action-card');
  await expect(cards).toHaveCount(2);
  await expect(cards.first()).toContainText('已过期');
  const current = cards.last();
  const cardText = await current.innerText();
  expect(cardText).toContain('未排除');
  expect(cardText).toContain('立即做');
  expect(cardText).toContain('来源');
  expect(cardText.indexOf('医疗风险')).toBeGreaterThanOrEqual(0);
  expect(cardText.indexOf('医疗风险')).toBeLessThan(cardText.indexOf('立即做'));
  await capture(page, info, 'chat-action-card', true);
  expectNoUnmatchedApi(ledger);
  expect(pageProblems).toEqual([]);
});

for (const width of [320, 430]) {
  test(`首页在 ${width}px 宽的首屏可开始应急，且不横向滚动`, async ({ page }, info) => {
    test.skip(info.project.name !== 'content-mobile', '此场景检查窄视口');
    await page.setViewportSize({ width, height: 640 });
    await openPage(page, shotFor('home'), info);
    const entry = page.getByRole('link', { name: /开始应急咨询/ });
    await expect(entry).toHaveAttribute('href', '/consult/emergency');
    await expect(entry).toBeInViewport({ ratio: 1 });
    const reachable = await entry.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return element.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2));
    });
    expect(reachable).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
  });
}

test('咨询输入在缩短后的窄视口仍可编辑和触达发送', async ({ page }, info) => {
  test.skip(info.project.name !== 'content-mobile', '此场景模拟键盘占用后的布局高度');
  await page.setViewportSize({ width: 320, height: 680 });
  await openPage(page, shotFor('chat'), info);
  const composer = page.getByRole('textbox', { name: '发送消息' });
  await composer.focus();
  await page.setViewportSize({ width: 320, height: 365 });
  await composer.fill('我想补充一个细节。');
  const send = page.getByRole('button', { name: '发送', exact: true });
  await expect(composer).toBeInViewport({ ratio: 1 });
  await expect(send).toBeInViewport({ ratio: 1 });
  await expect(send).toBeEnabled();
  await send.click({ trial: true });
});

test('注册状态、密码显示与输入错误有明确反馈', async ({ page }, info) => {
  const { pageProblems } = await openPage(page, shotFor('login'), info);
  await page.getByRole('button', { name: '已有邀请码？注册账号' }).click();
  await page.getByLabel('密码', { exact: true }).fill('local-test-value');
  await page.getByRole('button', { name: '显示密码' }).click();
  await expect(page.getByLabel('密码', { exact: true })).toHaveAttribute('type', 'text');
  await page.getByRole('button', { name: '注册', exact: true }).click();
  await expect(page.locator('[aria-invalid="true"]').first()).toBeVisible();
  await capture(page, info, 'registration-validation');
  expect(pageProblems).toEqual([]);
});

test('记忆展开显示完整原文，纠正表单获得焦点并保留原记录内容', async ({ page }, info) => {
  const { ledger, pageProblems } = await openPage(page, shotFor('memory'), info);
  const row = page.locator('article.list-row').first();
  const original = await row.locator('.lr-title').textContent();
  await row.getByRole('button', { name: '看完整内容', exact: true }).click();
  await expect(row.getByRole('button', { name: '收起', exact: true })).toHaveAttribute('aria-expanded', 'true');
  await expect(row.locator('.lr-title')).toHaveText(original ?? '');
  await capture(page, info, 'memory-expanded', true);
  await row.getByRole('button', { name: '纠正', exact: true }).click();
  await expect(page.getByRole('heading', { name: '新增一条更正' })).toBeFocused();
  await expect(page.getByRole('textbox', { name: '内容' })).toHaveValue(original ?? '');
  await capture(page, info, 'memory-correction');
  expectNoUnmatchedApi(ledger);
  expect(pageProblems).toEqual([]);
});
