/** 全页面重构的关键状态：真实浏览器交互与截图，使用现有隔离夹具。 */
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { expect, test, type Page, type TestInfo } from '@playwright/test';

import { PAGE_SHOTS, type PageShot } from './support/fixtures';
import { expectNoUnmatchedApi } from './support/network';
import { expandForFullPage, measureOverflow } from './support/neutralise';
import { openPage } from './support/page-open';
import { SHOTS_OUT_DIR } from './support/paths';

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
  await expect(page.getByRole('searchbox', { name: '搜索资料' })).toBeVisible();
  await expect(page.getByText('资料库还在准备中')).toBeVisible();
  await page.getByRole('link', { name: '← 返回' }).click();
  await expect(page.getByLabel('想聊的事情')).toBeVisible();
  await page.getByRole('link', { name: '使用说明' }).click();
  await expect(page.getByRole('link', { name: '开始应急咨询 →' })).toHaveAttribute('href', '/consult/emergency');
  await page.getByRole('link', { name: '← 返回' }).click();
  await expect(page.getByLabel('想聊的事情')).toBeVisible();
  expectNoUnmatchedApi(ledger);
});

async function capture(page: Page, info: TestInfo, name: string, full = false): Promise<void> {
  const dir = resolve(SHOTS_OUT_DIR, 'states');
  await mkdir(dir, { recursive: true });
  const path = resolve(dir, `${name}-${info.project.name}.png`);
  if (!full) {
    await page.screenshot({ path, animations: 'disabled' });
    return;
  }
  const expanded = await expandForFullPage(page, await measureOverflow(page));
  try {
    await expanded.assertExpanded();
    await page.screenshot({ path, fullPage: true, animations: 'disabled' });
  } finally {
    await expanded.restore();
    await expanded.assertRestored();
  }
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
  await capture(page, info, 'emergency-selected');
  await page.getByRole('button', { name: '← 退出应急' }).click();
  const dialog = page.getByRole('dialog', { name: '退出现场采集？' });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: '继续填写' }).click();
  await expect(page.locator(`input[value="${selectedValue}"]`)).toBeChecked();
  expectNoUnmatchedApi(ledger);
  expect(pageProblems).toEqual([]);
});

test('对话过程与依据独立展开，正文和常驻输入器保留', async ({ page }, info) => {
  const { ledger, pageProblems } = await openPage(page, shotFor('chat'), info);
  await page.locator('.reasoning-row > summary').click();
  await page.locator('.citation-block > summary').click();
  await expect(page.getByLabel('发送消息')).toBeVisible();
  await expect(page.locator('.msg-doc')).toContainText('先不劝');
  await capture(page, info, 'chat-sources', true);
  expectNoUnmatchedApi(ledger);
  expect(pageProblems).toEqual([]);
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
