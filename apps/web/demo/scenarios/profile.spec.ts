/**
 * 模块: demo/scenarios/profile.spec
 * 职责: 真栈走一遍「新建对象 → 手动补一条记录 → 建第二个对象 → 草稿保护 → 刷新后仍在」，按声明顺序截图
 * 数据来源:
 *   - ./profile.schema.ts: MUST — 步骤顺序与讲解词
 *   - ../support/stack.ts: MUST — 开户（registerNewAccount 的四层判据）、waitProfileLoaded（骨架消失判据）
 *   - apps/web/src/features/profile/view/ProfilePage.tsx:150-181（切换器 role=group aria-label=支持对象、
 *     对象是 button.tag + aria-pressed、「+ 新建对象」；185-189 分区导航只在选中对象后渲染）、
 *     :337-359（#profile-records 与 details.group-collapse）、:639-705（补充表单的领域 select、
 *     主题 input、描述 textarea、保存按钮）、:412-438（「放弃当前编辑？」与「切换支持对象？」两张单）
 *   - apps/web/src/features/profile/viewModel/useProfileEntryActions.ts:191-224（补充成功提示「已补充一条记录」）
 *   - apps/web/src/features/profile/domain/formValidation.ts:57-70（草稿判据：领域被选过也算改动）
 *   - apps/web/src/infrastructure/http/profilePort.ts:52-95（端点：POST /api/profile/objects、
 *     POST /api/profile/objects/<id>/items）
 * 边界:
 *   - 依赖: @playwright/test、./profile.schema、../support/{paths,shots,stack}
 *   - 被依赖: playwright.demo.config.ts（project `demo` 按 /scenarios\/.*\.spec\.ts$/ 收集）
 * 禁止行为:
 *   - 禁止把「保存成功」降级成「页面出现了一句提示」（写库判据是刷新后仍在，见第 ⑧ 帧）
 *   - 禁止用 page.route / route.fulfill 伪造任何响应（真栈材料一旦伪造就不再证明链路可用）
 *   - 禁止只等按钮出现就认为保存完成（保存类判据一律等 201/200 + 页面提示）
 */

import { expect, test, type Locator, type Page } from '@playwright/test';

import { PROFILE } from './profile.schema';
import { BASE_URL } from '../support/paths';
import { captureStep } from '../support/shots';
import { inviteCodeForScenario, registerNewAccount, waitProfileLoaded } from '../support/stack';

/** 第一个对象：本场景自己新建，用来演示「使用者自己建档」。 */
const FIRST_OBJECT = '小满';

/** 第二个对象：没有它就没有「切到另一个对象」，草稿保护那一帧也就无从触发。 */
const SECOND_OBJECT = '阿禾';

/**
 * 手动补充的那条记录。
 *
 * 领域刻意选「感觉处理」而不是兜底「其他」：领域下拉的一次显式选择本身就是草稿判据的一部分
 * （`formValidation.ts` 的 `itemDraftChanged`），也让第 ⑤ 帧的分组标题能对上「领域真的生效了」。
 * 描述是具体、日常的事实，不编造诊断、用药与剂量。
 */
const ENTRY = {
  domain: 'sensory_processing',
  domainLabel: '感觉处理',
  topic: '超市里的音乐',
  description: '超市里一放音乐就捂住耳朵、站在原地不动',
} as const;

/** 草稿保护那一帧手填的草稿（**不保存**：它必须被丢弃，否则「保护」无从展示）。 */
const DRAFT = {
  topic: '睡前流程',
  description: '睡前要先按顺序把三件事说完才肯进房间',
} as const;

/** 对象切换器分组（对象 chip 与「+ 新建对象」都在里面）。 */
function switcher(page: Page): Locator {
  return page.getByRole('group', { name: '支持对象' });
}

/** 某个支持对象的 chip（按显示名精确匹配，避免与「+ 新建对象」混淆）。 */
function objectChip(page: Page, name: string): Locator {
  return switcher(page).getByRole('button', { name, exact: true });
}

/**
 * 等档案页停稳——**还没有任何支持对象**时的第一帧专用。
 *
 * 为什么不用 `waitProfileLoaded`：那个判据要求 `nav[aria-label="档案分区"]` 出现，而分区导航只在
 * 「已选中一个对象」时渲染（`ProfilePage.tsx:183-189`）。全新账号一个对象都没有，用它会一路等到超时。
 * 这里只等加载态面板（`.panel[aria-busy="true"]`）消失；空态文案由调用处另断言。
 *
 * 写成局部函数而不是改 `support/stack.ts`：本次只授权新增两个场景文件（缺 helper 在报告里说明）。
 */
async function waitProfileFirstPaint(page: Page): Promise<void> {
  await expect(page.locator('.panel[aria-busy="true"]')).toHaveCount(0, { timeout: 20_000 });
}

/** 打开「给 TA 起个称呼」单并填好称呼；返回单本身（提交与断言都用它）。 */
async function openCreateSheet(page: Page, name: string): Promise<Locator> {
  await switcher(page).getByRole('button', { name: '+ 新建对象' }).click();
  const sheet = page.getByRole('dialog', { name: '给 TA 起个称呼' });
  await expect(sheet).toBeVisible();
  await sheet.getByRole('textbox', { name: '称呼' }).fill(name);
  return sheet;
}

/**
 * 点「创建」，并按 HTTP 判据收口。
 *
 * 为什么等响应而不是等文案：创建成功后单会关掉、整页重新加载，中间没有任何可等的提示；
 * 201 才是「后端真建了对象」的证据（而不是「单关掉了」）。
 */
async function submitCreateSheet(page: Page, sheet: Locator): Promise<void> {
  const created = page.waitForResponse(
    (response) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/profile/objects',
  );
  await sheet.getByRole('button', { name: '创建' }).click();
  expect((await created).status(), '新建对象的 HTTP 状态').toBe(201);
  await expect(sheet).toBeHidden();
}

/**
 * 打开「补充一条记录」表单。
 *
 * 「补充一条」按设计**多处同名**（空态主按钮、区块按钮都叫这个名字），因此取 `.last()`
 * ——即记录区下方那个常驻的区块按钮，它在两种空态下都存在。
 */
async function openAddForm(page: Page): Promise<Locator> {
  await page.getByRole('button', { name: '补充一条', exact: true }).last().click();
  const form = page.getByRole('heading', { name: '补充一条记录' }).locator('..');
  await expect(form).toBeVisible();
  return form;
}

/** 在补充表单里手填主题与描述（领域按需用 selectOption，见调用处）。 */
async function fillDraft(form: Locator, draft: { topic: string; description: string }): Promise<void> {
  await form.getByRole('textbox', { name: '主题' }).fill(draft.topic);
  await form.getByRole('textbox', { name: '描述' }).fill(draft.description);
}

test(PROFILE.title, async ({ page }, testInfo) => {
  // 全套只有三次保存（建对象 ×2 + 补条目 ×1）、不需要模型；开户本身还要走一遍 reg + 首页水合。
  test.setTimeout(240_000);
  const shot = (index: number) => captureStep(page, PROFILE, index);

  // ① 开户：全新账号 ⇒ 档案页必然是「还没有支持对象」，这正是本场景的起点。
  //    邀请码下标用 1 而不是 0：邀请码是一次性的，同一轮里 onboarding 场景已占用下标 0，
  //    共用下标会撞上已用掉的码（得到 HTTP 200 + GENERAL_ERROR 的假绿，见 `stack.ts` 的注释）。
  await registerNewAccount(page, inviteCodeForScenario(PROFILE.slug, testInfo.retry));
  await page.goto(`${BASE_URL}/profile`);
  await expect(page.locator('.tab-bar')).toBeVisible();
  await expect(page.getByRole('heading', { name: '档案', exact: true })).toBeVisible();
  await waitProfileFirstPaint(page);
  // 非空洞性：这一帧必须是「空档案」，不是一张加载中的骨架图。
  await expect(
    page.getByText('先给 TA 起个称呼，之后咨询中说的相关事情会记在这里。', { exact: true }),
  ).toBeVisible();
  await shot(0);

  // ② 新建对象：填好称呼、**提交前**拍一帧（观众要看见「起个称呼」这条入口长什么样）。
  const createSheet = await openCreateSheet(page, FIRST_OBJECT);
  await shot(1);

  // ③ 提交：201 才是「真建了对象」；成功后切换器出现第一个 chip，摘要区仍是空的。
  await submitCreateSheet(page, createSheet);
  await waitProfileLoaded(page);
  await expect(objectChip(page, FIRST_OBJECT)).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText('摘要中还没有记录，确认或补充后会出现。', { exact: true })).toBeVisible();
  await shot(2);

  // ④ 补充一条：领域、主题、描述三项填好，提交前拍（这一帧是「字段补充」本身）。
  const addForm = await openAddForm(page);
  await addForm.getByRole('combobox').selectOption(ENTRY.domain);
  await fillDraft(addForm, ENTRY);
  await shot(3);

  // ⑤ 保存：等 201 + 页面提示，再把条目在分组里核对一遍——两条判据缺一不可。
  const saved = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      /^\/api\/profile\/objects\/[^/]+\/items$/.test(new URL(response.url()).pathname),
  );
  await addForm.getByRole('button', { name: '保存' }).click();
  expect((await saved).status(), '补充条目的 HTTP 状态').toBe(201);
  await expect(page.locator('p[role="status"]')).toContainText('已补充一条记录');
  const records = page.locator('#profile-records');
  await expect(records).toBeVisible({ timeout: 20_000 });
  await expect(records).toContainText(ENTRY.topic);
  await expect(records, '条目应落在所选的「感觉处理」分组下，而不是兜底「其他」').toContainText(ENTRY.domainLabel);
  await shot(4);

  // ⑥ 第二个对象：没有它就演示不了「切到另一个对象」，草稿保护那一帧也就触发不了。
  const secondSheet = await openCreateSheet(page, SECOND_OBJECT);
  await submitCreateSheet(page, secondSheet);
  await waitProfileLoaded(page);
  await expect(objectChip(page, FIRST_OBJECT)).toBeVisible();
  await expect(objectChip(page, SECOND_OBJECT)).toBeVisible();
  // 新建对象后选中项不变（列表按 created_at 升序、`pickObjectId` 保留原选择），
  // 因此这一帧同时拍得到两个 chip 与已有记录——「切换是平级单选」看得见。
  await expect(objectChip(page, FIRST_OBJECT)).toHaveAttribute('aria-pressed', 'true');
  await shot(5);

  // ⑦ 草稿保护：手填主题与描述（**不保存**），再点另一个对象。
  //    领域留默认值也够触发：草稿判据含主题/描述非空；这一帧证明的是「有草稿就会被拦」，
  //    不是「哪些字段算草稿」（那一条由 `formValidation.ts` 的判据保证）。
  const guardedForm = await openAddForm(page);
  await fillDraft(guardedForm, DRAFT);
  await objectChip(page, SECOND_OBJECT).click();
  const switchGuard = page.getByRole('dialog', { name: '切换支持对象？' });
  await expect(switchGuard).toBeVisible();
  await expect(switchGuard).toContainText('当前编辑尚未保存');
  await expect(switchGuard.getByRole('button', { name: '切换并丢弃' })).toBeVisible();
  await shot(6);

  // ⑧ 切换并丢弃 → 回到有记录的那个对象 → 刷新 → 记录仍在。
  await switchGuard.getByRole('button', { name: '切换并丢弃' }).click();
  await expect(switchGuard).toBeHidden();
  // 草稿真的被丢掉了：补充表单已收起（若没丢，它会跟着新对象一起留在页面上）。
  await expect(page.getByRole('heading', { name: '补充一条记录' })).toHaveCount(0);
  await waitProfileLoaded(page);
  // 切回有记录的那个对象；若刷新后本来就选中它，这次点击是 no-op（选中项不进 URL、不落库）。
  await objectChip(page, FIRST_OBJECT).click();
  await waitProfileLoaded(page);
  await expect(page.locator('#profile-records')).toContainText(ENTRY.topic);

  // 真正的判据：`page.reload()` 之后那条记录还在。
  // 提示语「已补充一条记录」只活在内存里、刷新即消失——所以先断言它没了，再断言记录还在：
  // 两句话合起来才说清「留下的是服务端数据，不是那句提示」。
  await page.reload();
  await waitProfileLoaded(page);
  await expect(page.locator('p[role="status"]')).toHaveCount(0);
  const afterReload = page.locator('#profile-records');
  await expect(afterReload).toContainText(ENTRY.topic, { timeout: 20_000 });
  await expect(afterReload).toContainText(ENTRY.description);
  await expect(afterReload).toContainText(ENTRY.domainLabel);
  await shot(7);
});
