/**
 * 模块: demo/support/stack
 * 职责: 真实栈上的开户与走查动作——注册、登录、提问、等回答完成
 * 数据来源:
 *   - apps/web/e2e-real/t10-real.spec.ts:137-149（注册四层判据）、:865-944（日常咨询入口）、
 *     :947-978（首字与完成的两段轮询）、:206-208（登录）
 *   - apps/web/e2e-real/ui-redesign.spec.ts:75-85（注册的 body status 判据）、:255-276（首页入口 + SSE 判据）
 *   - apps/web/e2e-real/README.md:285-289（复用失效邀请码会得到 HTTP 200 + GENERAL_ERROR 的假绿）
 * 边界:
 *   - 依赖: @playwright/test、../e2e-real/support/real（SSE tap 与采集器，同一套真实栈装置）
 *   - 被依赖: scenarios/*.spec.ts
 * 禁止行为:
 *   - 禁止只断言 HTTP 200 就认为注册成功（SuperTokens 会用 200 + GENERAL_ERROR 表达失败）
 *   - 禁止用 `.chat-progress` 的有无判断回答完成（它多来源，会把「待作答」误判成超时）
 *   - 禁止在本装置内使用 page.route / route.fulfill（真栈材料一旦伪造响应就不再证明链路可用）
 */

import { expect, type Page } from '@playwright/test';

import { BASE_URL, SCENARIO_SLUGS, type ScenarioSlug } from './paths';
import { SettleTracker, type RoundSignals } from './roundState';

/**
 * 等正文/收尾的上界：**必须不小于产品的单轮上限**，否则装置会在产品还在正常跑的时候
 * 判「正文始终没出现」（2026-10-28 就是这么红的：产品上限已上调到 300 秒，装置还按 200 秒等）。
 *
 * 取值 = 产品上限（`AGENT_RUN_TIMEOUT_SECONDS`，300 秒）+ 20 秒落库与渲染余量。
 * ⚠ 产品上限变了这里要跟着变：这条注释就是提醒，别让它再次落后于产品。
 */
const ANSWER_TIMEOUT_MS = 320_000;

/** 邀请码池（逗号分隔）；空池返回空数组，由调用方显式判失败。 */
export function invitePool(): string[] {
  return (process.env.DEMO_INVITE_CODES ?? process.env.DEMO_INVITE_CODE ?? '')
    .split(',')
    .map((code) => code.trim())
    .filter((code) => code !== '');
}

/**
 * 按**场景短名**取这一场景专用的邀请码。
 *
 * 为什么不用「模块级计数器顺序消费」（第一版就是这么写的，2026-10-27 实测整轮全红）：
 * Playwright 即使 `workers: 1`，**每个测试文件也在各自独立的 worker 进程里跑**，
 * 模块级计数每个文件都从 0 开始 ⇒ 每个场景都拿到第一枚码，第二个场景起一律
 * `200 {"status":"GENERAL_ERROR","message":"邀请码无效或已不可用"}`
 * （`modules/accounts/registration.py:623` 的既有语义）。看起来像产品坏了，实为夹具。
 *
 * **重试要另取一枚码**：一枚码只能开一个新账号，配置里允许重试一次
 * （`playwright.demo.config.ts` 的 `retries: 1`），重试会重新开户——若仍取同一枚码，
 * 重试必然撞在「已使用」上，把一次真实重试变成假失败。故调用方把 `attempt`（= `testInfo.retry`）
 * 传进来，下标按「第几次尝试 × 场景数 + 场景位置」算，重试取码因此是确定的。
 *
 * 前置: `DEMO_INVITE_CODES` 至少「场景数 × 尝试次数」枚（默认最多 2 次 → 12 枚）
 * 后置: 返回一枚**本进程内没用过**的码
 * 异常: 池为空、或下标越界（码不够）时抛错——不取模回绕，回绕会造出「邀请码无效」的假象
 */
export function inviteCodeForScenario(slug: ScenarioSlug, attempt = 0): string {
  const pool = invitePool();
  if (pool.length === 0) {
    throw new Error('没有邀请码：先 `uv run python -m campfire.cli invite issue` 现签，再传 DEMO_INVITE_CODES');
  }
  const base = SCENARIO_SLUGS.indexOf(slug);
  if (base < 0) throw new Error(`场景 ${slug} 未在 SCENARIO_SLUGS 登记，取不到邀请码下标`);
  // 下标 = 第几次尝试 × 场景数 + 场景位置。**不靠进程内状态**：Playwright 在用例失败后会换
  // 新 worker 进程跑重试，任何模块级计数都会归零（2026-10-27 实测：重试因此拿到已用过的码，
  // 报成「邀请码无效」）。把尝试次数作为参数传进来，重试的取码才是确定的。
  const index = attempt * SCENARIO_SLUGS.length + base;
  if (index >= pool.length) {
    throw new Error(
      `邀请码不够：本次要用第 ${String(index + 1)} 枚（场景 ${slug}${attempt === 0 ? '' : ` 的第 ${String(attempt + 1)} 次尝试`}），` +
        `池里只有 ${String(pool.length)} 枚。按「场景数 × 2」签（推荐 ${String(SCENARIO_SLUGS.length * 2)} 枚）：` +
        '一枚码只能开一个新账号，重试要另开一个。',
    );
  }
  return pool[index] ?? '';
}

/** 本轮时间戳（进账号名，保证每轮是全新账号，残余不滚进下一轮）。 */
export function freshStamp(): number {
  return Date.now();
}

/** 全新账号名：演示每轮开户，避免历史数据把「首次引导」演成「已有档案」。 */
export function freshAccount(stamp: number): string {
  return `demo-${String(stamp)}@example.test`;
}

/** 全新口令：≥8 位、含小写字母与数字（注册表单的校验要求）。 */
export function freshPassword(stamp: number): string {
  return `demo${String(stamp)}pass`;
}

/** 等应用壳挂载（登录页与主界面都有 .tab-bar 之外的稳定锚点时用它兜底）。 */
export async function waitMounted(page: Page): Promise<void> {
  await page.waitForLoadState('domcontentloaded');
  await expect(page.locator('#root')).toBeVisible({ timeout: 15_000 });
}

/** 打开登录页并等它挂载；断言注册入口在场（一期没有自助注册）。 */
export async function openLoginPage(page: Page): Promise<void> {
  await page.goto(`${BASE_URL}/login`);
  await waitMounted(page);
  await expect(page.getByRole('button', { name: '已有邀请码？注册账号' })).toBeVisible();
}

/** 切到注册表单。 */
export async function openRegisterForm(page: Page): Promise<void> {
  await page.getByRole('button', { name: '已有邀请码？注册账号' }).click();
  await expect(page.locator('#auth-invite')).toBeVisible();
}

/**
 * 填表并提交注册，断言**四层**成功判据。
 *
 * 前置: 已 `openRegisterForm`
 * 后置: 已登录并停在首页（`.tab-bar` 可见）；返回账号与口令供后续步骤复用
 * 异常: 任一层判据不满足即失败并抛出可读原因（不降级、不跳过）
 *
 * 判据（缺一不可，理由见 ui-redesign.spec.ts:75-85 与 README:285-289）:
 *   ① HTTP 200；② 响应体 `status === 'OK'`；③ 跳到首页；④ 底部标签栏可见。
 * 只看 ① 会在「码已失效」时恒真通过——supertokens 返回 200 + GENERAL_ERROR。
 */
export async function submitRegistration(
  page: Page,
  options: { inviteCode: string; account?: string; password?: string },
): Promise<{ account: string; password: string }> {
  if (options.inviteCode.trim() === '') {
    throw new Error('没有可用邀请码：先 `uv run python -m campfire.cli invite issue` 现签，再传 DEMO_INVITE_CODE');
  }
  const stamp = freshStamp();
  const account = options.account ?? freshAccount(stamp);
  const password = options.password ?? freshPassword(stamp);

  await page.fill('#auth-account', account);
  await page.fill('#auth-password', password);
  await page.fill('#auth-invite', options.inviteCode);

  const signup = page.waitForResponse((response) => response.url().endsWith('/api/auth/signup'));
  await page.locator('button[type="submit"]').click();
  const response = await signup;
  expect(response.status(), '注册请求的 HTTP 状态').toBe(200);
  expect(((await response.json()) as { status: string }).status, '注册响应体 status').toBe('OK');

  await expect(page).toHaveURL(`${BASE_URL}/`, { timeout: 20_000 });
  await expect(page.locator('.tab-bar')).toBeVisible();
  return { account, password };
}

/**
 * 一步开户：打开登录页 → 切注册 → 提交。
 *
 * 供「不需要单独展示登录/注册两屏」的场景直接用；需要分屏截图的场景用上面三个函数拆开。
 */
export async function registerNewAccount(page: Page, inviteCode: string): Promise<{ account: string; password: string }> {
  await openLoginPage(page);
  await openRegisterForm(page);
  return submitRegistration(page, { inviteCode });
}

/**
 * 进「日常咨询」并发出第一条消息。
 *
 * 前置: 已登录
 * 后置: 会话已创建（URL 含 `/consult/sessions/<id>`）、消息已提交
 * 返回: 会话 URL（供后续步骤断言与刷新型演示使用）
 */
export async function startDailyConsult(page: Page, message: string): Promise<string> {
  await page.goto(`${BASE_URL}/consult`);
  await waitMounted(page);
  const created = page.waitForResponse(
    (response) => response.url().endsWith('/api/consult/sessions') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: /开始新的日常咨询/ }).click();
  const response = await created;
  expect(response.status(), '建会话的 HTTP 状态').toBe(201);
  await expect(page).toHaveURL(/\/consult\/sessions\/[0-9a-z-]+/);

  const composer = page.locator('#consult-composer');
  await expect(composer).toBeVisible({ timeout: 20_000 });
  await composer.fill(message);
  await page.getByRole('button', { name: '发送' }).click();
  return page.url();
}

/**
 * 在**当前会话**里再发一条消息（不新建会话）。
 *
 * 前置: 页面停在会话页且输入区可用
 * 后置: 消息已发出；返回发出 `POST …/messages` 的响应状态
 */
export async function sendFollowUp(page: Page, message: string): Promise<number> {
  const composer = page.locator('#consult-composer');
  await expect(composer).toBeVisible({ timeout: 20_000 });
  const send = page.getByRole('button', { name: '发送' });
  // 发送按钮在「本轮仍在跑」时是 disabled 的（输入区被收起），直接点会一直等到超时
  // （2026-10-27 实测：`element is not enabled` → `element was detached`）。先等它可用。
  await expect(send).toBeEnabled({ timeout: 60_000 });
  const sent = page.waitForResponse(
    (response) =>
      /\/api\/consult\/sessions\/[0-9a-z-]+\/messages$/.test(response.url()) &&
      response.request().method() === 'POST',
  );
  await composer.fill(message);
  await expect(send).toBeEnabled({ timeout: 20_000 });
  await send.click();
  return (await sent).status();
}

/**
 * 等回答开始出字。
 *
 * 为什么不用「发送成功」当判据：202 只表示服务端收下了，界面可能还在 `onboarding`。
 * 这里等正文第一段有内容（`.msg-doc` 是模型正文的容器）。
 *
 * 超时给到 200 秒而不是 45 秒：模型是**推理模型**，长提示下首字前可能有几十秒的思考，
 * 服务端单次请求超时就是 45 秒（`MODEL_REQUEST_TIMEOUT_SECONDS`）、还带 2 次重试，
 * 45 秒的客户端等待会先于服务端失败，把「模型在想」误报成「夹具卡住」
 * （2026-10-27 实测：三场景同时卡在这条 45 秒上，而后端日志随后才报 `APITimeoutError`）。
 * 真正的失败由 `waitRoundOutcome` / `waitRunSettled` 认 `.error-card` 兜住。
 */
export async function waitFirstToken(page: Page): Promise<void> {
  await expect
    .poll(async () => (await page.locator('.msg-doc').first().innerText().catch(() => '')).trim().length, {
      timeout: ANSWER_TIMEOUT_MS,
      message: '等待模型正文首字（200 秒内没有出字：看页面是否挂出错误卡片，或后端日志有无 APITimeoutError）',
    })
    .toBeGreaterThan(0);
}

/** 一轮跑完之后页面可能落到的两种终态。 */
export type RoundOutcome = 'question' | 'done';

/**
 * 等这一轮跑出一个**确定终态**：又有待作答的提问，或者引导已宣布完成。
 *
 * 为什么不用 SSE 的 `run_finished` 计数：`e2e-real/support/real.ts` 的观察口**每遇到一条
 * 新的 SSE 流就重置事件表**（`installSseTap` 里的 `target.t10SseTap = {...}`），
 * 因此它只能回答「最后一条流里有什么」，不能跨轮累计。2026-10-27 实测：第二轮跑完了，
 * 计数仍是 1，一直等到 180 秒超时——那是夹具的错，不是产品的错。
 *
 * 为什么也不用「停止按钮消失」：那是**瞬时**状态，在「刚提交、新一轮还没起来」的窗口里
 * 天然为假，会立刻判成「已结束」（与上一条同源的假红）。
 *
 * DOM 终态不存在这两个问题：提交后旧卡立刻变 `已提交`（不再算待作答），
 * 新一轮结束后要么出现新的待作答卡，要么出现 `完成引导` 工具行——两者都不会回退。
 */
export async function waitRoundOutcome(page: Page): Promise<RoundOutcome> {
  await expect
    .poll(
      async () => {
        // 失败态优先：模型超时/不可用时页面会挂出 `.error-card`（`本次回答没有完成。稍后可以重试。`）。
        // 不认它就会一直等到超时，然后把「模型超时」误报成「夹具卡住」——2026-10-27 实测过一次。
        const error = page.locator('.error-card');
        if ((await error.count()) > 0) {
          const text = (await error.first().innerText().catch(() => '')).replace(/\s+/g, ' ').trim();
          throw new Error(`这一轮运行失败，页面报错：${text === '' ? '（读不到错误卡片文案）' : text}`);
        }
        if (await hasPendingQuestionBatch(page)) return 'question';
        // 精确到「已结束」：`hasText: '完成引导'` 会连「完成引导 · 未完成」一起命中，
        // 那等于把工具失败当成流程成功（独立复查 FAIL-2）。
        if ((await page.locator('.tool-row', { hasText: '完成引导 · 已结束' }).count()) > 0) return 'done';
        return 'waiting';
      },
      { timeout: ANSWER_TIMEOUT_MS, message: '等待这一轮跑出终态（新提问卡 或 完成引导）' },
    )
    .not.toBe('waiting');
  return (await page.locator('.tool-row', { hasText: '完成引导 · 已结束' }).count()) > 0 ? 'done' : 'question';
}

/** 页面上是否存在**待作答**的提问卡（`下一步` 角标；`已提交`/`提问记录` 都不算）。 */
export async function hasPendingQuestionBatch(page: Page): Promise<boolean> {
  const cards = page.locator('.question-card');
  const count = await cards.count();
  for (let index = 0; index < count; index += 1) {
    const head = cards.nth(index).locator('.question-head .meta');
    if ((await head.innerText().catch(() => '')) === '下一步') return true;
  }
  return false;
}

/**
 * 把当前这组提问答完并提交（每题的答法由 `freeAnswers` 的下标决定）。
 *
 * 前置: 页面上有一张**待作答**的提问卡
 * 后置: 已提交（触发新一次运行）；返回实际处理的题数
 * 规则: 有 `freeAnswers[i]` 就用自己的话回答；否则点第一个选项；连选项都没有就点「跳过」
 *      （`跳过` 只标记、不自动前进，所以每题之后都要显式点「下一题」）。
 * 异常: 题目数量超出 `MAX_QUESTIONS` 视为页面异常（防死循环）
 */
export async function answerQuestionBatch(page: Page, freeAnswers: readonly (string | undefined)[] = []): Promise<number> {
  const MAX_QUESTIONS = 16;
  const card = page.locator('.question-card').last();
  await expect(card.locator('.question-head .meta')).toHaveText('下一步', { timeout: 20_000 });

  for (let index = 0; index < MAX_QUESTIONS; index += 1) {
    const isLast = (await card.locator('[data-question-submit]').count()) > 0;
    const free = freeAnswers[index];

    if (free !== undefined) {
      const toggle = card.getByRole('button', { name: '用自己的话回答' });
      if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click();
      await card.getByLabel('你的回答').fill(free);
    } else if ((await card.locator('.question-option').count()) > 0) {
      await card.locator('.question-option').first().click();
    } else {
      await card.getByRole('button', { name: '跳过', exact: true }).click();
    }

    if (isLast) {
      await card.locator('[data-question-submit]').click();
      return index + 1;
    }
    await card.locator('[data-question-next]').click();
  }
  throw new Error(`一组提问超过 ${String(MAX_QUESTIONS)} 题仍未提交：页面形态与预期不符，拒绝继续`);
}

/** 「静定」取样间隔与所需连续不变次数（普通咨询一轮实测 30–120 秒）。 */
const SETTLE_POLL_MS = 3_000;
const SETTLE_STABLE_SAMPLES = 4;

/**
 * 等**普通咨询的一轮**跑完（不是引导轮）。
 *
 * 为什么需要它：`waitRoundOutcome` 的两个终态（待作答提问卡 / `完成引导 · 已结束`）都是**引导**的
 * 形状。跳过引导之后的一轮日常咨询通常既不提问、也不调 `finish_onboarding`，用它必然等到
 * 180 秒超时，把「产品正常答完」误报成夹具卡住（2026-10-27 实测：记忆场景就是这么红的）。
 *
 * 判据（三条都不会回退，刻意不用「停止按钮消失」那种瞬时状态）：
 *   ① 无 `.error-card`（有就立刻抛：模型超时/不可用，与「还在跑」是两件事）；
 *   ② 无 `data-state="running"` 的工具行（工具没结束，正文必然还会变）；
 *   ③ 最后一条助手正文（`.msg-doc`）长度连续 4 次取样（间隔 3 秒）不变。
 *
 * 前置: `baselineDocs` = 本轮**开始前**的 `.msg-doc` 数量；没有新增助手消息时一律返回 waiting，
 *      否则「正文不变」只是模型还没开口
 * 后置: 不改动页面
 */
export async function waitRunSettled(page: Page, baselineDocs = 0): Promise<RoundOutcome> {
  // 判据本体在 `./roundState`（纯函数 + 稳定闸门，另有单测）；这里只负责把 DOM 读成信号。
  const tracker = new SettleTracker(SETTLE_STABLE_SAMPLES);
  await expect
    .poll(
      async () => {
        const verdict = tracker.next(await readRoundSignals(page, baselineDocs));
        if (verdict.kind === 'error') throw new Error(`这一轮运行失败，页面报错：${verdict.message}`);
        return verdict.kind;
      },
      {
        intervals: [SETTLE_POLL_MS],
        timeout: ANSWER_TIMEOUT_MS,
        message: '等待这一轮静定（工具行全部结束且正文不再增长）超时：模型可能仍在长时间思考',
      },
    )
    .not.toBe('waiting');
  return (await hasPendingQuestionBatch(page)) ? 'question' : 'done';
}

/** 把页面读成一次采样信号（各条的含义见 `RoundSignals` 的注释）。 */
async function readRoundSignals(page: Page, baselineDocs: number): Promise<RoundSignals> {
  const error = page.locator('.error-card');
  const errorText =
    (await error.count()) === 0
      ? null
      : (await error.first().innerText().catch(() => '')).replace(/\s+/g, ' ').trim() || '（读不到错误卡片文案）';
  const stopButton = page.getByRole('button', { name: '停止' });
  return {
    errorText,
    docCount: await page.locator('.msg-doc').count(),
    baselineDocs,
    runningTools: await page.locator('.tool-row[data-state="running"]').count(),
    pendingQuestion: await hasPendingQuestionBatch(page),
    stopVisible: (await stopButton.count()) > 0,
    lastDocLength: (await page.locator('.msg-doc').last().innerText().catch(() => '')).trim().length,
  };
}

/**
 * 等档案页**加载完成**（骨架态不算材料）。
 *
 * 2026-10-27 实测踩到：`归档分区` 的 `role=group` 在数据未到时就已渲染，于是「可见」为真，
 * 截下来的是三块空白骨架——讲解词写着「出现支持对象」，图里却什么也没有。
 * 判据改成两条：骨架面板消失（`.panel[aria-busy="true"]` 计数为 0）且分区导航出现。
 */
export async function waitProfileLoaded(page: Page): Promise<void> {
  await expect(page.locator('nav[aria-label="档案分区"]')).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('.panel[aria-busy="true"]')).toHaveCount(0, { timeout: 20_000 });
}
