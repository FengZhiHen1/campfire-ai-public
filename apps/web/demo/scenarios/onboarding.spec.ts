/**
 * 模块: demo/scenarios/onboarding.spec
 * 职责: 真栈走一遍「注册 → 首次咨询 → 多轮引导 → 建档落地」，按声明顺序截图
 * 数据来源:
 *   - ./onboarding.schema.ts: MUST — 步骤顺序与讲解词
 *   - ../support/stack.ts: MUST — 注册四层判据、咨询入口、提问卡作答、SSE 运行完成判定
 *   - apps/api/skills/onboarding/SKILL.md: 引导为多轮逐题推进，建档发生在答完之后
 *   - apps/web/src/features/profile/view/ProfilePage.tsx:33-53: MUST — 空态与分区文案（非空洞性断言用）
 * 边界:
 *   - 依赖: @playwright/test、./onboarding.schema、../support/{shots,stack,paths}
 *   - 被依赖: playwright.demo.config.ts（project `demo`）
 * 禁止行为:
 *   - 禁止把「建档是否真的发生」降级成「页面能打开」（否则截出来的是一张空档案页，讲解词就成了假话）
 *   - 禁止用 page.route 伪造任何响应（真栈材料一旦伪造就不再证明链路可用）
 */

import { expect, test } from '@playwright/test';

import { ONBOARDING } from './onboarding.schema';
import { BASE_URL } from '../support/paths';
import { captureStep } from '../support/shots';
import {
  answerQuestionBatch,
  freshAccount,
  freshPassword,
  freshStamp,
  inviteCodeForScenario,
  openLoginPage,
  openRegisterForm,
  startDailyConsult,
  submitRegistration,
  waitFirstToken,
  waitProfileLoaded,
  waitRoundOutcome,
} from '../support/stack';

/**
 * 本场景演示几轮问答。
 *
 * 引导按 skill 是 8 个档案种子问题 + 2–3 个使用者认知问题、**一问一轮**（`SKILL.md` §3/§4），
 * 跑满就是十来分钟。材料要证明的是「引导会推进、回答会落成档案」，两三已经能证明，
 * 剩下的轮次不会带来新形态，只会把一次材料生成拖成十几分钟。
 *
 * 为什么是 3 而不是 2：2026-10-27 实测出现过「第 2 轮问的还是称呼/年龄，记录区仍是空的」——
 * 引导的题序由模型决定，两轮不一定问到能落成条目的具体观察。第 3 轮给一句具体观察作为兜底。
 */
const DEMO_ROUNDS = 3;

/**
 * 各轮的「用自己的话回答」。
 *
 * 每一轮都给一句**可直接落成档案条目**的观察：只说感受（「他好像很敏感」）模型无处可写，
 * 这一轮就会空手而过（2026-10-27 实测出现过「对象建好了、记录区是空的」）。
 * 内容全部是**已核实过的日常观察**，不编造医疗事实（诊断、用药、自伤/伤人细节一律不填）。
 * 超出这三轮的题目一律点第一个选项。
 */
const FREE_ANSWERS: readonly (readonly (string | undefined)[])[] = [
  ['小满', '五岁'],
  ['在超市里，广播音乐一响，他就捂住耳朵、站在原地不动'],
  ['在家能说完整的句子；情绪上来就不说话，改成拉我的手'],
];

test(ONBOARDING.title, async ({ page }, testInfo) => {
  // 多轮真实模型调用：每轮 30–120 秒，3 轮 + 档案页两跳，给到 15 分钟。
  test.setTimeout(900_000);
  const shot = (index: number) => captureStep(page, ONBOARDING, index);

  // ① 登录页：注册入口在这儿，先让观众看见「一期不发自助注册」。
  await openLoginPage(page);
  await shot(0);

  // ② 注册表单填好（提交前拍）：一次性邀请码是这一步的看点。
  //    账号与口令先生成、再填、再用同一份提交——否则截图上的值与真正提交的不是一回事。
  const inviteCode = inviteCodeForScenario(ONBOARDING.slug, testInfo.retry);
  const stamp = freshStamp();
  const account = freshAccount(stamp);
  const password = freshPassword(stamp);
  await openRegisterForm(page);
  await page.fill('#auth-account', account);
  await page.fill('#auth-password', password);
  await page.fill('#auth-invite', inviteCode);
  await shot(1);

  // ③ 提交注册：四层判据在 submitRegistration 里（HTTP 200 + body OK + 跳首页 + 标签栏可见）。
  await submitRegistration(page, { inviteCode, account, password });
  await shot(2);

  // ④ 首次咨询：真模型 + 真检索。这一轮结束时应当抛出一组引导提问。
  await startDailyConsult(page, '孩子五岁，最近超市里一放音乐就捂耳朵、原地不动，我该怎么做？');
  await waitFirstToken(page);
  const firstOutcome = await waitRoundOutcome(page);
  // 非空洞性：这一轮必须真的调用过工具（工具行默认收起，但节点存在）。
  expect(await page.locator('.tool-row').count(), '首次咨询应至少有一次工具调用').toBeGreaterThan(0);
  await shot(3);

  // ⑤ 引导提问卡：引导必须真的开始提问，否则后面「建档」没有来源。
  expect(firstOutcome, '首次咨询后应出现待作答的引导提问').toBe('question');
  await page.locator('.question-card').last().scrollIntoViewIfNeeded();
  await shot(4);

  // ⑥ 逐轮作答：每答完一组都会触发新一轮。这里是**有界**演示（见 DEMO_ROUNDS 的理由）。
  for (let round = 0; round < DEMO_ROUNDS; round += 1) {
    await answerQuestionBatch(page, FREE_ANSWERS[round] ?? []);
    const outcome = await waitRoundOutcome(page);
    if (outcome === 'done') break;
    if (round === 0) {
      // 第二轮之后的画面：这一帧用来证明「答过的内容被继续往下带」。
      await page.locator('.question-card, .msg-doc').last().scrollIntoViewIfNeeded();
      await shot(5);
    }
  }

  // 非空洞性：建档动作必须真的发生过（这一轮的工具行是「建立支持对象」）。
  expect(
    await page.locator('.tool-row', { hasText: '建立支持对象 · 已结束' }).count(),
    '引导应已成功调用「建立支持对象」（「未完成」不算：那说明工具失败，档案页仍是空态）',
  ).toBeGreaterThan(0);

  // ⑦ 档案页：引导的工具应已落库（空态文案不该出现）。
  await page.goto(`${BASE_URL}/profile`);
  await expect(page.locator('.tab-bar')).toBeVisible();
  await waitProfileLoaded(page);
  await expect(page.getByRole('group', { name: '支持对象' })).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('body'), '档案页不该是「还没有对象」的空态').not.toContainText('先给 TA 起个称呼');
  await shot(6);

  // ⑧ 档案条目分组：条目按领域展开，证明「说的话变成了结构化记录」。
  const records = page.locator('#profile-records');
  await expect(records, '引导完成后档案应有记录区（空态说明引导没落库）').toBeVisible({ timeout: 20_000 });
  expect(await records.locator('.group-collapse').count(), '档案应有条目分组').toBeGreaterThan(0);
  // 必须滚动到记录区再截：`toBeVisible` 不滚动，第 7、8 步会拍成同一屏（复查实测同哈希）。
  await records.scrollIntoViewIfNeeded();
  await shot(7);
});
