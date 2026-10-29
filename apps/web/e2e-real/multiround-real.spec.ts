/**
 * 模块: e2e-real/multiround-real
 * 职责: GAP-04（追问 → 补答）与 GAP-05（刷新后水合续上）的真实依赖用例
 *
 * ⚠ **需要真实栈**（后端 8000、Vite 5173、真实邀请码池与真模型）。
 * 与 `t10-real.spec.ts` 同一套纪律：**不注册任何 `page.route`**，每个 `/api/**` 请求都由
 * 浏览器真发出去；证据是真实 id 与真实状态码，而不是「页面上出现了某个字符串」。
 *
 * 为什么单独一个文件而不是加进 `t10-real`：那条文件是「一次性跑完七条验收链路」的顺序装置，
 * 其中链路 1 会**用掉一枚邀请码并登出**。本用例要的是一次干净注册 + 连续两轮真实问答 +
 * 刷新，混进去会让两条装置的失败互相掩盖（一条失败带走另一条的证据）。
 *
 * 这两条覆盖为什么值得单列（`docs/TODO.md` 的 GAP-04 / GAP-05）：产品在「第二轮」与
 * 「刷新后续传」上有真实分支——`not-resumable` / `stream-exhausted` / 历史水合——而此前
 * 它们只在前端单测（`runStore.test.ts`）里出现过，没有真栈验证。单测能证明判据逻辑，
 * 不能证明**真后端**在第二轮、刷新后确实给出可续的状态。
 *
 * ⚠ 真实模型会**提问**：日常咨询里模型可以用提问卡先澄清再作答（`ask_question` 是产品能力）。
 * 因此这里不假设「发一条消息 → 必然得到一段正文」，而是每轮都先处理「有待作答的提问卡」
 * 这一形态（见 `ensureComposer`）。假设成「一定直接回答」会得到一个看起来像产品卡住的
 * 假失败——2026-10-28 实测过：第 1 轮成功后输入区被提问卡收起，装置白等 25 秒说
 * 「找不到输入框」。
 */

import { test, expect, type BrowserContext, type Page } from '@playwright/test';

import {
  BASE_URL,
  createLog,
  freshAccount,
  freshPassword,
  installSseTap,
  inviteCodeFor,
  readSseTap,
  saveLog,
  waitMounted,
  watchApi,
  watchConsole,
  type ApiTrace,
  type ConsoleRecord,
} from './support/real';

const log = createLog();
const apiTrace: ApiTrace[] = [];
const records: ConsoleRecord[] = [];

const STAMP = Date.now();
const ACCOUNT = freshAccount(STAMP + 1);
const PASSWORD = freshPassword(STAMP + 1);
/** 下标 1：下标 0 归 `t10-real` 的链路 1（邀请码一次性，抢码会让两边都红）。 */
const INVITE = inviteCodeFor(1);

/** 单轮真实运行的上界：与产品单轮上限（300 秒）一致，再加 30 秒渲染/落库余量。 */
const ROUND_TIMEOUT_MS = 330_000;

let context: BrowserContext;

async function openPage(): Promise<Page> {
  const page = await context.newPage();
  watchConsole(page, records);
  watchApi(page, apiTrace);
  await installSseTap(page);
  return page;
}

/** 发消息触发运行的端点（契约 3.3）：`POST /api/consult/sessions/<id>/messages`，响应带 `run_id`。 */
function runRequests(): ApiTrace[] {
  return apiTrace.filter((entry) => entry.method === 'POST' && entry.url.endsWith('/messages'));
}

/**
 * 等「刚刚这一轮」跑到终态。
 *
 * 判据是 SSE 的终态事件（`run_finished` / `run_failed`），不是「等 N 秒」也不是「正文变长了」：
 * 前者是时序猜测，后者在模型分两段流式输出时会把中间态当成结束。
 * `installSseTap` 每遇到一条新流就重置观察表，因此它只能回答「最后一条流里有什么」——
 * 这正好是逐轮判定要的语义。
 */
async function waitRunFinished(
  page: Page,
  expectedRuns: number,
  label: string,
  options: { differentStreamFrom?: string } = {},
): Promise<string> {
  await expect
    .poll(
      async () => {
        if (runRequests().length < expectedRuns) return 'no-request';
        const tap = await readSseTap(page);
        // 重试走的是「同一条消息再跑一次」，不一定新增 `POST …/messages`；那时改用
        // 「流地址变了」判定新的一轮已经开始（否则会立刻把上一轮的终态当成结果）。
        const previous = options.differentStreamFrom;
        if (previous !== undefined && tap.url === previous) return 'running';
        const failed = tap.events.find((event) => event.event === 'run_failed');
        if (failed !== undefined) throw new Error(`这一轮运行失败（真后端报的）：${failed.data}`);
        return tap.events.some((event) => event.event === 'run_finished') ? 'finished' : 'running';
      },
      { timeout: ROUND_TIMEOUT_MS, message: `等这一轮跑到 run_finished：${label}` },
    )
    .toBe('finished');

  const runs = runRequests();
  const last = runs[runs.length - 1];
  expect(last?.status, `建运行状态码不是 202：${JSON.stringify(last)}`).toBe(202);
  const runId = last?.bodyKeyIds.find((pair) => pair.startsWith('run_id='))?.slice('run_id='.length) ?? '';
  expect(runId, `运行响应里没有真实 run_id：${JSON.stringify(last?.bodyKeyIds)}`).not.toBe('');
  return runId;
}

/** 页面上是否存在**待作答**的提问卡（`下一步` 角标；`已提交` / 提问记录都不算）。 */
async function hasPendingQuestion(page: Page): Promise<boolean> {
  const cards = page.locator('.question-card');
  const count = await cards.count();
  for (let index = 0; index < count; index += 1) {
    const meta = await cards.nth(index).locator('.question-head .meta').innerText().catch(() => '');
    if (meta.trim() === '下一步') return true;
  }
  return false;
}

/**
 * 把当前这组提问答完并提交（每题取第一个选项；没有选项的题就点「跳过」）。
 *
 * 为什么装置要会这一步：产品允许模型先提问再作答，而提问卡会把输入区收起。
 * 不处理这一形态，装置就只能报告「找不到输入框」——那是在怪产品做对了的事。
 */
async function answerPendingQuestion(page: Page): Promise<void> {
  const card = page.locator('.question-card').last();
  await expect(card.locator('.question-head .meta')).toHaveText('下一步', { timeout: 20_000 });
  for (let index = 0; index < 16; index += 1) {
    const isLast = (await card.locator('[data-question-submit]').count()) > 0;
    if ((await card.locator('.question-option').count()) > 0) {
      await card.locator('.question-option').first().click();
    } else {
      await card.getByRole('button', { name: '跳过', exact: true }).click();
    }
    if (isLast) {
      await card.locator('[data-question-submit]').click();
      return;
    }
    await card.locator('[data-question-next]').click();
  }
  throw new Error('一组提问超过 16 题仍未提交：页面形态与预期不符，拒绝继续');
}

/** 让输入框可用：若模型先提了问，就把这组问答答完（作答本身会起新一轮），直到输入框回到页面。 */
async function ensureComposer(page: Page): Promise<void> {
  const composer = page.locator('#consult-composer');
  for (let attempt = 0; attempt < 3; attempt += 1) {
    if (await composer.isVisible()) return;
    if (!(await hasPendingQuestion(page))) {
      // 既没有输入框也没有待作答卡：可能正在跑（等一会儿再看），也可能是真形态异常。
      await page.waitForTimeout(5_000);
      if (await composer.isVisible()) return;
      throw new Error('输入框与提问卡都不在：页面处于既不能发也不能答的状态');
    }
    const expected = runRequests().length + 1;
    await answerPendingQuestion(page);
    await waitRunFinished(page, expected, '答完一组提问后的那一轮');
  }
  await expect(composer).toBeVisible({ timeout: 20_000 });
}

/**
 * 发一条消息并等它那一轮结束，返回 run_id。
 *
 * 遇到 `model_unavailable` 时**点产品自己的「重试」**再等一轮，最多两次。
 * 这条不是给装置开后门：`APIConnectionError` 今晚实测发生 6 次（模型端点连接被重置），
 * 产品对它的正确处置就是「给出可重试的失败卡 + 重试按钮」，使用者会点它。装置照着点，
 * 顺带覆盖了这条恢复路径；不点的话整条用例会因为外部抖动变红，掩盖它真正要验的东西。
 */
async function sendRound(page: Page, text: string): Promise<string> {
  await ensureComposer(page);
  const composer = page.locator('#consult-composer');
  await expect(composer).toBeVisible({ timeout: 25_000 });

  let expected = runRequests().length + 1;
  await composer.fill(text);
  await page.getByRole('button', { name: '发送' }).click();

  for (let attempt = 0; ; attempt += 1) {
    try {
      const runId = await waitRunFinished(page, expected, text);
      // 终态事件说完了，界面得跟上：本轮助手正文必须落在页面上。
      await expect(page.locator('.msg-doc').last()).not.toBeEmpty({ timeout: 30_000 });
      return runId;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const recoverable = message.includes('model_unavailable');
      if (!recoverable || attempt >= 2) throw error;
      // 产品在失败时给的是 `.error-card` + 「重试」（`ChatWorkspace.retryLastRun`）。
      const retry = page.locator('.error-card').getByRole('button', { name: '重试' });
      await expect(retry, '运行失败后应给出重试入口').toBeVisible({ timeout: 20_000 });
      const streamBefore = (await readSseTap(page)).url;
      await retry.click();
      await expect(page.locator('.error-card')).toHaveCount(0, { timeout: 20_000 });
      // 重试后的那一轮：以「SSE 流换了地址」为开始标志（不假设它会新增一条 messages 请求）。
      const recoverExpected = (await readSseTap(page)).url === streamBefore ? runRequests().length + 1 : runRequests().length;
      try {
        return await waitRunFinished(page, recoverExpected, `${text}（重试第 ${String(attempt + 1)} 次）`, {
          differentStreamFrom: streamBefore,
        });
      } catch (retried) {
        if (attempt + 1 >= 2) throw retried;
        continue;
      }
    }
  }
}

test('@real 追问补答与刷新续传：两轮真实运行 + 刷新后水合', async () => {
  test.setTimeout(900_000);
  expect(INVITE, '必须提供真实邀请码（T10_INVITE_CODES 的第 2 枚）：没有它就不是真实注册').not.toBe('');

  const page = await openPage();
  try {
    /* ── 前置：真实注册 + 登录 ─────────────────────────────────────── */
    await page.goto(`${BASE_URL}/login`);
    await waitMounted(page);
    await page.getByRole('button', { name: '已有邀请码？注册账号' }).click();
    await expect(page.locator('#auth-invite')).toBeVisible({ timeout: 20_000 });
    await page.fill('#auth-account', ACCOUNT);
    await page.fill('#auth-password', PASSWORD);
    await page.fill('#auth-invite', INVITE);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(`${BASE_URL}/`, { timeout: 45_000 });
    await expect(page.locator('.tab-bar')).toBeVisible({ timeout: 20_000 });

    /* ── 建会话（真 201 + 真 session id）────────────────────────────── */
    const created = page.waitForResponse(
      (response) => response.url().endsWith('/api/consult/sessions') && response.request().method() === 'POST',
    );
    await page.goto(`${BASE_URL}/consult`);
    await waitMounted(page);
    await page.getByRole('button', { name: /开始新的日常咨询/ }).click();
    expect((await created).status(), '建会话的 HTTP 状态').toBe(201);
    await expect(page).toHaveURL(/\/consult\/sessions\/[0-9a-f-]{32,36}/, { timeout: 40_000 });
    const sessionId = page.url().split('/').pop() ?? '';
    expect(sessionId, 'URL 里没有真实 session id').toMatch(/^[0-9a-f-]{32,36}$/);

    /**
     * 先**跳过一次性引导**，再做多轮。
     *
     * 新账号的首次日常会话会注入引导 skill（契约第 6 节、决策记录 `一次性引导对话`），
     * 而引导是「一次一问」：模型每轮抛一组提问卡、把输入区收起，答完再问下一组——
     * 其间**发不了自由消息**。本条用例要验的是「多轮追问 → 补答」与「刷新水合」，
     * 不是引导本身（那有专门的演示场景与 `onboarding` 用例）。不跳过的话，装置会在引导的
     * 题轮里绕圈，最后以总超时失败——2026-10-28 实测过一次，看起来像产品卡死，其实是
     * 装置跑错了场景。
     *
     * 走的是**页头那个真入口**（`BUG-03` 的修复点）：点按钮 → `POST …/onboarding/skip` →
     * 入口消失。这条既让用例能进多轮，也顺带端到端验证了那个入口本身。
     */
    const skipButton = page.getByRole('button', { name: '跳过引导' });
    await expect(skipButton, '引导待注入时页头应给「跳过引导」入口').toBeVisible({ timeout: 20_000 });
    await skipButton.click();
    // 入口消失 = 端口调用成功（失败时入口会留着并给原因，这条因此不是恒真）
    await expect(skipButton).toHaveCount(0, { timeout: 20_000 });
    // 采样器在 `page.on('response')` 的回调里异步读正文，因此这里要**等**它落表，
    // 不能点完立刻取（2026-10-28 实测：立刻取拿到 undefined，看着像「端点没被调用」）。
    await expect
      .poll(() => apiTrace.filter((entry) => entry.url.endsWith('/onboarding/skip')).length, {
        timeout: 15_000,
        message: '跳过引导的请求没有出现在浏览器侧记录里',
      })
      .toBeGreaterThan(0);
    const skipTrace = apiTrace.filter((entry) => entry.url.endsWith('/onboarding/skip'));
    expect(skipTrace[0]?.status, `跳过引导的状态码：${JSON.stringify(skipTrace[0])}`).toBe(200);

    /* ── 第 1 轮：提问 ─────────────────────────────────────────────── */
    const firstRun = await sendRound(page, '孩子出门总爱乱跑，我该怎么提前防着点？');
    expect(await page.locator('.msg-doc').count(), '第 1 轮应有助手正文').toBeGreaterThan(0);

    /* ── 第 2 轮：追问（GAP-04 的核心）─────────────────────────────── */
    const followUp = '刚才说的第一条，具体到商场里我该怎么做？';
    const secondRun = await sendRound(page, followUp);
    expect(secondRun, '第 2 轮必须是一次**新的**运行（复用同一个 run 说明没真的追问）').not.toBe(firstRun);

    // 追问是**追加**而不是覆盖：至少两条使用者消息，且最后一条是追问原话。
    const userBubbles = page.locator('.bubble-user');
    expect(await userBubbles.count(), '两轮之后应至少有两条使用者消息').toBeGreaterThanOrEqual(2);
    await expect(userBubbles.last()).toContainText(followUp);
    // 两轮各有助手正文：第 2 轮的补答必须落到页面上（这就是「追问 → 补答」的可见证据）。
    expect(await page.locator('.msg-doc').count(), '两轮问答后应有两段以上助手正文').toBeGreaterThanOrEqual(2);

    /* ── 刷新：历史水合（GAP-05 的核心）────────────────────────────── */
    const bubblesBeforeReload = await userBubbles.count();
    // **不拿 `.msg-doc` 的元素个数当判据**（2026-10-29 实测）：跑完一轮后、刷新之前，
    // 页面上可能还挂着一个正在收尾的正文节点，个数会比服务端真源多一个；刷新后它自然消失。
    // 于是「刷新前 3 / 刷新后 2」会被读成「丢了历史」，而实际丢失的是那个瞬时节点。
    // 真正要守的是**内容**：刷新前每一段助手正文的开头，刷新后仍然在。
    const docTextsBeforeReload = (await page.locator('.msg-doc').allInnerTexts())
      .map((text) => text.replace(/\s+/g, ' ').trim())
      .filter((text) => text.length >= 20);
    expect(docTextsBeforeReload.length, '刷新前应已有可读的助手正文').toBeGreaterThanOrEqual(2);

    await page.reload();
    await waitMounted(page);
    await expect(page).toHaveURL(new RegExp(sessionId), { timeout: 30_000 });
    // 使用者消息条数与刷新前一致：多出来是重复渲染，少了是丢历史。
    await expect(page.locator('.bubble-user')).toHaveCount(bubblesBeforeReload, { timeout: 40_000 });

    const docTextsAfterReload = (await page.locator('.msg-doc').allInnerTexts()).map((text) =>
      text.replace(/\s+/g, ' ').trim(),
    );
    for (const [index, before] of docTextsBeforeReload.entries()) {
      // 取开头 30 字比对而不是全等：水合走的是服务端保存的文本，与流式拼出来的
      // 段间空白可能有一两处差异——那是渲染差异，不是丢内容。
      const head = before.slice(0, 30);
      expect(
        docTextsAfterReload.some((after) => after.includes(head)),
        `刷新后第 ${String(index + 1)} 段助手正文的开头（${head}）不见了：这是丢历史`,
      ).toBe(true);
    }
    await expect(page.locator('body')).not.toContainText('本次回答没有完成');
    // 刷新**不能**是「不可续传」死路：拿不到运行元数据时产品应改走历史水合并给出说明，
    // 而不是把页面留在一张错误卡上。
    await expect(page.locator('.error-card')).toHaveCount(0);

    const historyTrace = apiTrace.filter(
      (entry) =>
        entry.method === 'GET' &&
        entry.url.includes(`/api/consult/sessions/${sessionId}/messages`) &&
        entry.status === 200,
    );
    expect(historyTrace.length, '刷新后没有读到历史（水合请求没发出或没成功）').toBeGreaterThan(1);

    /* ── 刷新后再发一轮：会话仍然可用（续传不是只读快照）─────────── */
    const thirdRun = await sendRound(page, '那我回家先做哪一件事？');
    expect(thirdRun).not.toBe(secondRun);

    log.record('multiround', {
      sessionId,
      runs: { firstRun, secondRun, thirdRun },
      bubblesBeforeReload,
      docTextsBeforeReload: docTextsBeforeReload.length,
      historyStatuses: historyTrace.map((entry) => entry.status),
      console: records,
    });
    await saveLog(log, 'multiround-real-log');
  } finally {
    await page.close();
  }
});

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({
    baseURL: BASE_URL,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    viewport: { width: 390, height: 844 },
  });
});

test.afterAll(async () => {
  await context.close();
});
