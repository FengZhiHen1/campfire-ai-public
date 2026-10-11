/** 全页面重构的关键状态：真实浏览器交互与截图，使用现有隔离夹具。 */
import { mkdir, readFile } from 'node:fs/promises';
import { expect, test, type Page, type TestInfo } from '@playwright/test';

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
