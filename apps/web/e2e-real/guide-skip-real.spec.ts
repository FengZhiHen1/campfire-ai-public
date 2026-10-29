/**
 * 模块: e2e-real/guide-skip-real
 * 职责: 「跳过引导」入口的真栈回归（BUG-03 的修复点）
 *
 * 为什么单独一条、且**不调模型**：跳过入口的价值恰恰在于「使用者不想再答引导」——
 * 它在引导刚开始、一条消息都还没发的时候就必须可用。等模型答一轮再验，既慢（数分钟）
 * 又把「入口好不好用」与「模型可不可用」混在一起。这条用例全程只做注册 + 建会话 + 点一下，
 * 实测 4 秒。
 *
 * 判据四条（每条都能红）：
 *   ① 引导待注入时页头**有**「跳过引导」（服务端 `onboarding_pending: true` ⇒ 路由 state ⇒ 入口）；
 *   ② 点击之后入口消失（失败时入口会留着，因此这条不是恒真）；
 *   ③ 浏览器确实向真后端发了 `POST …/onboarding/skip` 并拿到 200（经 Vite 代理，非 mock）；
 *   ④ 刷新后入口**不**因「刚才点过」又冒出来（跳过成功已清掉会话级记忆）。
 */

import { test, expect } from '@playwright/test';

import {
  BASE_URL,
  freshAccount,
  freshPassword,
  inviteCodeFor,
  waitMounted,
  watchApi,
  type ApiTrace,
} from './support/real';

const trace: ApiTrace[] = [];

test('@real 跳过引导入口：出现 → 点击 → 200 → 消失 → 刷新不再出现', async ({ page }) => {
  test.setTimeout(180_000);
  watchApi(page, trace);

  const invite = inviteCodeFor(2);
  expect(invite, '必须提供真实邀请码（T10_INVITE_CODES 的第 3 枚）').not.toBe('');
  const stamp = Date.now();

  await page.goto(`${BASE_URL}/login`);
  await waitMounted(page);
  await page.getByRole('button', { name: '已有邀请码？注册账号' }).click();
  await page.fill('#auth-account', freshAccount(stamp + 7));
  await page.fill('#auth-password', freshPassword(stamp + 7));
  await page.fill('#auth-invite', invite);
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(`${BASE_URL}/`, { timeout: 45_000 });

  // 新账号的首次日常会话 ⇒ 服务端返回 `onboarding_pending: true` ⇒ 页头应给入口。
  await page.goto(`${BASE_URL}/consult`);
  await waitMounted(page);
  await page.getByRole('button', { name: /开始新的日常咨询/ }).click();
  await expect(page).toHaveURL(/\/consult\/sessions\/[0-9a-f-]{32,36}/, { timeout: 40_000 });

  const skip = page.getByRole('button', { name: '跳过引导' });
  await expect(skip, '引导待注入时页头应有「跳过引导」入口').toBeVisible({ timeout: 25_000 });
  await skip.click();
  await expect(skip, '跳过成功后入口应消失（失败时它会留着）').toHaveCount(0, { timeout: 20_000 });

  // 采样器异步读正文，必须等它落表再断言状态码。
  await expect
    .poll(() => trace.filter((entry) => entry.url.endsWith('/onboarding/skip')).length, { timeout: 15_000 })
    .toBeGreaterThan(0);
  const hit = trace.find((entry) => entry.url.endsWith('/onboarding/skip'));
  expect(hit?.status, `跳过引导的状态码：${JSON.stringify(hit)}`).toBe(200);
  expect(hit?.viaProxy, '请求必须打在 5173（经 Vite 代理到真后端），而不是被打桩').toBe(true);

  await page.reload();
  await waitMounted(page);
  await expect(skip, '刷新后入口不该因为「刚才点过」又冒出来').toHaveCount(0, { timeout: 20_000 });
});
