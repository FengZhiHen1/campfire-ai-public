/**
 * 模块: demo/scenarios/emergency.spec
 * 职责: 真栈走一遍「应急入口 → 八维采集（全部可跳过）→ 提交 → 行动卡」，按声明顺序截图
 * 数据来源:
 *   - ./emergency.schema.ts: MUST — 步骤顺序与讲解词
 *   - ../support/stack.ts:195-208、:164-171: MUST — 开户四层判据与首字等待（waitFirstToken）
 *   - apps/web/src/features/consult/view/EmergencyFormPage.tsx:64-179: MUST — 表单选择器与固定文案
 *   - apps/web/src/features/consult/domain/emergency.ts:49-153、:166: MUST — 八维 key、题干顺序、跳过语义
 *   - apps/web/src/features/consult/view/MessageParts/ActionCard.tsx:68-102: MUST — 行动卡结构与徽章
 *   - apps/api/src/campfire/surfaces/consult/injections.py:63-111: MUST — 首条采集消息的表头与两种标记
 *   - apps/api/src/campfire/tools/emergency_card.py:51-56: 七节 key 的封闭清单（卡片必有「当前状态」节）
 * 边界:
 *   - 依赖: @playwright/test、./emergency.schema、../support/{shots,stack,paths}
 *   - 被依赖: playwright.demo.config.ts（project `demo`）
 * 禁止行为:
 *   - 禁止使用 page.route / route.fulfill 伪造任何响应（真栈材料一旦伪造就不再证明链路可用）
 *   - 禁止提交虚构医疗事实：前五题一律点「跳过这题」（跳过 = 未排除），第六题只写一句真实但
 *     无害的观察；不写诊断、不写用药、不写自伤/伤人细节
 *   - 禁止把「行动卡渲染了分节」降级成「提交成功」（那样这张图什么也没有证明）
 */

import { expect, test, type Locator, type Page } from '@playwright/test';

import { EMERGENCY } from './emergency.schema';
import { BASE_URL } from '../support/paths';
import { captureStep } from '../support/shots';
import { inviteCodeForScenario, invitePool, registerNewAccount, waitFirstToken } from '../support/stack';

/**
 * 本场景自开户所用的邀请码池下标。
 *
 * 应急入口要求已登录（app/routes.tsx:101 的 `requiresSession`），而演示装置里没有现成账号
 * 的口令，因此本场景自己开一个号。下标必须与 onboarding 场景的 0 错开：一枚邀请码只能开
 * 一个号，复用会拿到 HTTP 200 + GENERAL_ERROR 的假绿（stack.ts:36-49）。
 */
const INVITE_INDEX = 1;

/**
 * 等行动卡的上界。
 *
 * 应急 skill 的时延目标是「出卡 ≤150 秒」（emergency-consulting.md 第 3 节实测修订后的上限），
 * 这里留余量；整条用例的上界另见 `test.setTimeout`。
 */
// 必须不小于产品的单轮上限（300 秒）+ 渲染余量：装置等短了会把「产品还在正常跑」判成「行动卡没出现」。
const ACTION_CARD_TIMEOUT_MS = 320_000;

/**
 * 第六题「刚刚发生了什么」填的那句话。
 *
 * 真栈纪律：这是**可观察的事实**，不含任何判断。不写诊断、不写用药、不写自伤或伤人细节——
 * 演示材料一旦写下虚构的医疗事实，观众照着做就是真实伤害。
 */
const OBSERVATION = '在超市里，音乐一响就捂住耳朵、站在原地不动';

/** 进度条：`aria-valuemin=1 / aria-valuemax=8` 的「采集题目位置」（EmergencyFormPage.tsx:83-92）。 */
function progressBar(page: Page): Locator {
  return page.getByRole('progressbar', { name: '采集题目位置' });
}

/** 题干：`h2#emergency-step-title`（同时是选项组的 `aria-labelledby`，EmergencyFormPage.tsx:96-101）。 */
function stepTitle(page: Page): Locator {
  return page.locator('h2#emergency-step-title');
}

/**
 * 页脚的「已处理 N / 8 题」行（EmergencyFormPage.tsx:147-150）。
 *
 * 用 `^已处理 ` 锚定：它的类名是 CSS module 的哈希名，取不到；而纯 `getByText('已处理 …')`
 * 会连带匹配到祖先元素拼接出来的文本，触发 strict mode 冲突。
 */
function handledNote(page: Page): Locator {
  return page.getByText(/^已处理 /);
}

/**
 * 点一次「跳过这题」，并断言进度停在该题的序号上。
 *
 * 这是本场景的**主要答法**：跳过是「未排除」的显式表达（domain/emergency.ts:166），
 * 比随手勾一个「无」更诚实——后者等于替使用者虚构了一个阴性发现。
 * 非末题时按钮会顺带前进一题（EmergencyFormPage.tsx:168 的 `form.skip(); if (!form.isLast) form.next()`），
 * 末题则停在原地并挂出「本题已跳过（按未排除处理）」。
 */
async function skipQuestion(page: Page, expectedNow: number): Promise<void> {
  await page.getByRole('button', { name: '跳过这题' }).click();
  await expect(progressBar(page)).toHaveAttribute('aria-valuenow', String(expectedNow));
}

/**
 * 等行动卡真的渲染出分节；运行失败或卡片被拒渲染时立刻报错。
 *
 * 为什么不用 stack.ts 的 `waitRoundOutcome`：它的两个终态判据是「待作答提问卡」与
 * 「完成引导」工具行（stack.ts:191-210），后者是引导场景的产物；应急这一轮以行动卡收尾，
 * 追问是可选的，用那条判据只会一直等到超时——那是夹具错判，不是产品故障。
 * 这里改用与产品同一份判据：卡片落在助手正文 `.msg-doc` 内，且 `.ac-section` 数量 > 0。
 */
async function waitActionCardSections(page: Page): Promise<Locator> {
  const card = page.locator('.msg-doc article.action-card').last();
  await expect
    .poll(
      async () => {
        // 失败态优先：运行失败、或卡片因取值越界被拒渲染时，页面挂的是 `.error-card`
        // （MessageParts/ActionCard.tsx:55-61）。不认它就会把「模型超时」误报成「夹具卡住」。
        const error = page.locator('.error-card');
        if ((await error.count()) > 0) {
          const text = (await error.first().innerText().catch(() => '')).replace(/\s+/g, ' ').trim();
          throw new Error(`这一轮没有产出可渲染的行动卡，页面报错：${text === '' ? '（读不到错误卡片文案）' : text}`);
        }
        return card.locator('.ac-section').count();
      },
      { timeout: ACTION_CARD_TIMEOUT_MS, message: '等待行动卡渲染出分节' },
    )
    .toBeGreaterThan(0);
  return card;
}

test(EMERGENCY.title, async ({ page }, testInfo) => {
  // 一次真实运行 + 一张卡：实测出卡 p50 约 82 秒、上限 150 秒，故给到 6 分钟。
  test.setTimeout(720_000);
  const shot = (index: number) => captureStep(page, EMERGENCY, index);

  // 应急入口要求已登录。池里必须至少两枚码：本场景占下标 1，onboarding 占下标 0。
  if (invitePool().length < INVITE_INDEX + 1) {
    throw new Error(
      `本场景需要至少 ${String(INVITE_INDEX + 1)} 枚邀请码（onboarding 用下标 0，本场景用下标 ` +
        `${String(INVITE_INDEX)}）。先 \`uv run python -m campfire.cli invite issue\` 现签，` +
        '再以逗号分隔传入 DEMO_INVITE_CODES。',
    );
  }
  await registerNewAccount(page, inviteCodeForScenario(EMERGENCY.slug, testInfo.retry));

  // ① 首页入口：应急不是二级菜单里的功能，首页就有一块「现在需要帮助」。
  const emergencyEntry = page.getByRole('link', { name: /开始应急咨询/ });
  await expect(emergencyEntry, '首页应有「开始应急咨询」入口').toBeVisible({ timeout: 20_000 });
  await shot(0);
  await emergencyEntry.click();

  // ② 第 1 题：页头、退出、进度条、题干与选项组一次全部核对（选择器出处见文件头数据来源）。
  await expect(page.locator('.sp-title'), '表单页头').toHaveText('现在的情况');
  await expect(page.getByRole('button', { name: '← 退出应急' })).toBeVisible();
  await expect(page.getByText('跳过 = 未排除，不会当作正常', { exact: true }), '跳过语义的固定文案').toBeVisible();
  await expect(progressBar(page)).toHaveAttribute('aria-valuemin', '1');
  await expect(progressBar(page)).toHaveAttribute('aria-valuemax', '8');
  await expect(progressBar(page)).toHaveAttribute('aria-valuenow', '1');
  await expect(page.getByText('第 1 / 8 题', { exact: true })).toBeVisible();
  await expect(stepTitle(page)).toHaveText('现在有没有以下医疗危险表现？');
  // 选项组按题干标注；第一项是多选，9 个勾选项都在组内（值来自 domain/emergency.ts:56-66）。
  const redFlags = page.getByRole('group', { name: '现在有没有以下医疗危险表现？' });
  await expect(redFlags).toBeVisible();
  await expect(redFlags.locator('input[type="checkbox"][name="medical_red_flags"]')).toHaveCount(9);
  await shot(1);

  // ③ 连跳两题：证明「跳过 = 未排除」是真的在推进流程，而不是把未答项当成正常值。
  await skipQuestion(page, 2);
  await skipQuestion(page, 3);
  await expect(stepTitle(page)).toHaveText('他现在还能怎样沟通？');
  await expect(handledNote(page), '跳过的题算「已处理」').toContainText('已处理 2 / 8 题');
  await shot(2);

  // ④ 跳到第 6 题（八维里的 what_happened）并写一句真实无害的观察。
  //    中间三题（沟通、痛苦程度、感觉环境）同样跳过：它们都是现场判断，编造一个取值比留空更危险。
  await skipQuestion(page, 4);
  await skipQuestion(page, 5);
  await skipQuestion(page, 6);
  await expect(stepTitle(page)).toHaveText('刚刚发生了什么？');
  const note = page.locator('#emergency-note');
  await expect(note).toBeVisible();
  await note.fill(OBSERVATION);
  await expect(note).toHaveValue(OBSERVATION);
  await expect(handledNote(page)).toContainText('已处理 6 / 8 题');
  await shot(3);

  // ⑤ 最后两题（最大风险、是否疼痛）同样跳过；末题跳过后停在本页并挂出跳过标记。
  await page.getByRole('button', { name: '下一题' }).click();
  await expect(progressBar(page)).toHaveAttribute('aria-valuenow', '7');
  await skipQuestion(page, 8);
  await expect(stepTitle(page)).toHaveText('有没有可能正在疼痛？');
  await skipQuestion(page, 8);
  await expect(page.getByText(/本题已跳过（按未排除处理）/), '末题跳过后应有「按未排除处理」标注').toBeVisible();
  await expect(page.getByText('已处理 8 / 8 题')).toBeVisible();
  await expect(page.getByRole('button', { name: '下一题' }), '末题没有下一题').toBeDisabled();
  await expect(page.getByRole('button', { name: '提交，开始分析' })).toBeEnabled();
  await expect(page.getByText('随时提交，无需答完八题。')).toBeVisible();
  await shot(4);

  // ⑥ 提交：202 + `{session_id, run_id}`，随后跳对话页并订阅这次运行（HTTP/SSE 契约第 5 节）。
  const started = page.waitForResponse(
    (response) => response.url().endsWith('/api/consult/emergency') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: '提交，开始分析' }).click();
  const response = await started;
  expect(response.status(), '应急提交的 HTTP 状态').toBe(202);
  const body = (await response.json()) as { session_id: string; run_id: string };
  expect(body.session_id, '响应体应带 session_id').not.toBe('');
  expect(body.run_id, '响应体应带 run_id（订阅靠它）').not.toBe('');
  await expect(page).toHaveURL(`${BASE_URL}/consult/sessions/${body.session_id}`, { timeout: 20_000 });

  // 非空洞性：首条消息必须是**这次采集**本身，而不是一个空会话。
  // 标记出处 injections.py:63-111（表头 + 跳过标记 + 取值原样渲染）。
  await waitFirstToken(page);
  const intake = page.locator('.bubble-user').first();
  await expect(intake, '首条使用者消息应是八维采集').toContainText('【应急现场采集】');
  await expect(intake, '跳过的项必须写明「已跳过（未排除）」').toContainText('已跳过（未排除）');
  await expect(intake, '第六题的原话应原样进会话').toContainText('捂住耳朵');
  await shot(5);

  // ⑦ 行动卡：必须真的渲染出分节，否则这张图只是「提交成功」。
  const card = await waitActionCardSections(page);
  await expect(card).toBeVisible();
  await expect(card, '最新的卡片不应是失效态').not.toHaveClass(/expired/);
  await expect(card.locator('.tag').first(), '卡片标题').not.toBeEmpty();
  const sections = card.locator('.ac-section');
  expect(await sections.count(), '行动卡必须真的渲染出分节（.ac-section 数量 > 0）').toBeGreaterThan(0);
  // 分节序号由 domain/actionCard.ts:232-238 生成（01 起），第一节能与「编号」对上才算真的分了节。
  await expect(sections.first().locator('h3.ac-head')).toContainText('01');
  // 医疗风险走三值语义徽章（stable / unruled / high，domain/actionCard.ts:74-79），不用裸色块。
  await expect(card.locator('.status').first(), '医疗风险徽章').toHaveClass(/(stable|unruled|high)/);
  await card.scrollIntoViewIfNeeded();
  await shot(6);
});
