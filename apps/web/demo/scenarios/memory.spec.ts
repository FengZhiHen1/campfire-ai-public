/**
 * 模块: demo/scenarios/memory.spec
 * 职责: 真栈走一遍「咨询里说一件关于自己的事 → 模型写记忆 → 时间线读到 → 展开/纠正/删除确认」，按声明顺序截图
 * 数据来源:
 *   - ./memory.schema.ts: MUST — 步骤顺序与讲解词
 *   - ../support/stack.ts: MUST — 开户四层判据、日常咨询入口、首字与终态等待（`waitRoundOutcome` 会识别错误卡片）
 *   - ../support/shots.ts: MUST — 一键截图 + sidecar（本文件不自己写 PNG 与哈希）
 *   - apps/web/src/features/memory/view/MemoryPage.tsx: MUST — 选择器与文案（`.sp-title`、`article.list-row`、
 *     `details.tile.group-collapse`、`h2#memory-correction-title`、`.confirm-sheet` 的标题与正文）
 *   - apps/web/src/features/memory/viewModel/useMemoryPage.ts: MUST — 纠正成功后重取第一页、删除是本地移除（不整页刷新）
 *   - apps/web/src/features/memory/domain/failures.ts: MUST — 纠正成功/中间态两条前端文案（断言逐字引用）
 *   - apps/api/src/campfire/modules/memory/routes.py: 纠正同步等一次模型抽取（**可能几十秒**），故提交后上界给到 120 秒
 * 边界:
 *   - 依赖: @playwright/test、./memory.schema、../support/{paths,shots,stack}
 *   - 被依赖: playwright.demo.config.ts（project `demo`）
 * 禁止行为:
 *   - 禁止 page.route / route.fulfill（真栈材料一旦伪造响应就不再证明链路可用）
 *   - 禁止用 e2e-real 的 `seedMemoryEpisode()` 当「写入路径可用」的证据：它直连 FalkorDB 种一条 episode，
 *     是**另一套装置的夹具**，来源不是产品写路径（`apps/web/e2e-real/README.md` 第 7 节明确写了这条边界）
 *   - 禁止在确认单上点「删除」：删掉之后这一轮材料就没有可看的记录，且删除是不可逆的真实数据操作
 *   - 禁止在缺环境、模型没写记忆或写入没落地时 skip / 降级成夹具：一律失败并给出可读原因
 */

import { expect, test, type Page } from '@playwright/test';

import { MEMORY } from './memory.schema';
import { BASE_URL } from '../support/paths';
import { captureStep } from '../support/shots';
import {
  inviteCodeForScenario,
  registerNewAccount,
  startDailyConsult,
  waitFirstToken,
  waitMounted,
  sendFollowUp,
  waitRunSettled,
} from '../support/stack';

/**
 * 这一轮咨询里要说的「关于我自己」的低风险陈述。
 *
 * 只讲使用者本人的日常处境（睡不好、要不要换工作），**不编造医疗事实**——不写诊断、
 * 不写用药、不写自伤；记忆面记的是「你自己说过的事」，不需要任何医学内容也能演清楚。
 * 末句如实交代「这些是关于我自己的事」：它提高模型调用「记录记忆」的概率，
 * 但不改变链路真实性（写不写仍由模型决定，本场景不作弊）。
 */
const SELF_STATEMENT =
  '我最近睡不好，晚上总在想要不要换工作。我在物流公司做调度，排班老是反的。这些是关于我自己的事，你可以记下来。';

/**
 * 补说一句的原文（模型这一轮没写记忆时用）。
 *
 * 这是真人会说的话，走产品自己的输入框；不用直连库或种库夹具——那样「写入路径可用」就不再是证据。
 */
const REMEMBER_REQUEST = '刚才说的这些，麻烦你帮我记下来，以后咨询时用得上。';

/** 写记忆的尝试次数上界：首发一次 + 补说一次。两次都不写就是真的没写。 */
const MEMORY_WRITE_ATTEMPTS = 2;

/**
 * 纠正时在原内容后追加的标记。
 *
 * 为什么必须改内容：`features/memory/domain/formValidation.ts` 把「内容与原记录逐字相同」
 * 判成「没有需要更正的地方」（与服务端的 422 同义），照抄提交不会发起请求。
 * 追加的只是这句演示用的更正说明，不是关于使用者本人的新事实。
 */
const CORRECTION_MARKER = '（更正：这种情况从上个月就开始了）';

/**
 * 等记忆时间线出现记录的上界。
 *
 * 为什么要轮询：写路径是异步两段的——模型调 `write_memory` 只产生一条 `pending_write`，
 * 真正的 `add_episode` 由 Worker 完成，读路径只认 `write_state = 'done'`。
 * 150 秒落在「真实模型抽取 + Worker 轮询」的常见尾部之内；超时按失败处理（不静默通过）。
 */
const TIMELINE_TIMEOUT_MS = 150_000;

/** 轮询间隔：每次轮询都是**整页加载**（见 `openMemoryPage` 的理由），别把它压太密。 */
const POLL_INTERVAL_MS = 3_000;

/** 纠正提交后等结果提示的上界：该端点同步等一次模型抽取，比读路径慢一个量级。 */
const CORRECTION_TIMEOUT_MS = 120_000;

/** 记忆页的三种**结论形态**；骨架态不在其中——它是「还没有结论」，不能当结果用。 */
type MemoryPageState = 'records' | 'empty' | 'error';

/** 把多行文本压成一行，用于把页面文案塞进断言消息。 */
function oneLine(text: string): string {
  return text.replace(/\s+/g, ' ').trim();
}

/**
 * 打开记忆页（整页加载）并判定它落在哪种结论形态。
 *
 * 为什么每次都整页加载而不是「等页面自己刷新」：记忆面没有推送、也没有轮询，
 * 读路径只有挂载时那一次 `GET /api/memory/episodes`。想再看一眼库里有什么，
 * 唯一如实的做法就是重新挂载页面；就地等待只会等到一个永远不会变的空态。
 *
 * 前置: 已登录（否则会被路由守卫送到 `/login`，下面的页头断言会带着原因失败）
 * 后置: 无副作用地读一次页面
 * 返回: 结论形态；`error` 时附带失败卡文案（503 时是「暂时无法读取记录」）
 * 异常: 骨架消失后既没有记录、也不是空态/失败态——页面形态与预期不符，直接抛（不猜）
 */
async function openMemoryPage(page: Page): Promise<{ state: MemoryPageState; failureText: string }> {
  await page.goto(`${BASE_URL}/settings/memory`);
  await waitMounted(page);
  await expect(page.locator('.sp-title'), '记忆页页头').toHaveText('我提过的事');
  // 骨架是「还没有结论」：等它消失，三种结论形态才是可判的。
  await expect
    .poll(async () => page.locator('.skeleton').count(), { timeout: 20_000, message: '记忆页一直停在骨架态' })
    .toBe(0);
  if ((await page.locator('.error-card').count()) > 0) {
    const card = page.locator('.error-card').first();
    return { state: 'error', failureText: oneLine(await card.innerText().catch(() => '')) };
  }
  if ((await page.locator('article.list-row').count()) > 0) return { state: 'records', failureText: '' };
  if ((await page.locator('.empty-state').count()) > 0) return { state: 'empty', failureText: '' };
  const body = oneLine(await page.locator('body').innerText()).slice(0, 200);
  throw new Error(`记忆页既没有记录、也不在空态或失败态：页面形态与预期不符（正文开头：${body}）`);
}

/**
 * 轮询记忆页直到时间线出现记录；超时**失败**并说明是哪一段没走通。
 *
 * 两条失败原因必须分开报，否则排查方向会错：
 *   ① 工具行不在场 → 模型这一轮没调用「记录记忆」，empty 态是「确实没有生成」；
 *   ② 工具行在场却一直 empty → 写入在待写队列/Worker 那一段没有落成 `write_state='done'`。
 * 失败态（`.error-card`）**绝不**被当成空态放过：它是「读不出来」，与「没有记录」是两件事。
 *
 * 前置: 已登录且至少跑完一轮咨询
 * 后置: 页面停在「有记录」的记忆页上
 * 异常: 上界内没读到记录（含一直失败态）——抛出可读原因
 */
async function waitTimelineWithRecords(page: Page, options: { toolCalled: boolean }): Promise<void> {
  const deadline = Date.now() + TIMELINE_TIMEOUT_MS;
  let attempts = 0;
  let lastFailure = '';
  for (;;) {
    attempts += 1;
    const { state, failureText } = await openMemoryPage(page);
    if (state === 'records') return;
    if (state === 'error') lastFailure = failureText;
    if (Date.now() >= deadline) break;
    await page.waitForTimeout(POLL_INTERVAL_MS);
  }
  const cause =
    lastFailure !== ''
      ? `最后一次读到的是失败态「${lastFailure}」——这类失败表示记忆读不出来，不等于没有记录`
      : options.toolCalled
        ? '一直是空态「还没有记录」——这一轮确实调用了「记录记忆」，但写入没有在 Worker 侧落成 done'
        : '一直是空态「还没有记录」——模型这一轮没有写记忆（没有调用「记录记忆」）';
  throw new Error(
    `轮询记忆页 ${String(TIMELINE_TIMEOUT_MS / 1000)} 秒（${String(attempts)} 次整页加载）后仍读不到记录：${cause}`,
  );
}

test(MEMORY.title, async ({ page }, testInfo) => {
  // 真实模型 + 轮询：一轮咨询 30–120 秒（可能要补说一次），纠正还要再等一次模型抽取，
  // 再叠加最多 150 秒的记忆页轮询，故给到 12 分钟。
  test.setTimeout(720_000);
  const shot = (index: number) => captureStep(page, MEMORY, index);

  // ① 开户。邀请码各场景各占一个下标（冒烟场景占 0），复用已用过的码只会得到
  //    HTTP 200 + GENERAL_ERROR 的假绿；池子不够时这里会带着原因失败。
  const inviteCode = inviteCodeForScenario(MEMORY.slug, testInfo.retry);
  expect(inviteCode, '没有可用邀请码：先 `uv run python -m campfire.cli invite issue` 现签，再传 DEMO_INVITE_CODES').not.toBe('');
  await registerNewAccount(page, inviteCode);

  // ② 走真实写路径：发一条关于使用者本人的低风险陈述。
  //    记忆面没有创建端点，这条路是**唯一**能产出 episode 的方式。
  // 先记下本轮之前的助手消息数：`waitRunSettled` 要求「真的多了一条助手消息」。
  await page.goto(`${BASE_URL}/consult`);
  await waitMounted(page);
  const docsBefore = await page.locator('.msg-doc').count();
  await startDailyConsult(page, SELF_STATEMENT);
  await waitFirstToken(page);
  // `waitRunSettled` 会先认 `.error-card`（模型超时/不可用），再用「正文静定」判一轮结束。
  // 不能用 `waitRoundOutcome`：它的两个终态都是**引导**的形状，普通咨询一轮两个都不会出现。
  await waitRunSettled(page, docsBefore);

  // 写路径的第一段证据：模型必须真的调过「记录记忆」（`.tool-row` 的名称取自 toolLabels.ts）。
  //
  // 为什么要给一次补说：模型是否写记忆不由脚本决定，实测有「这一轮只回答、没记」的时候。
  // 补说的内容是**真人会说的话**（「刚才说的帮我记一下」），走的是产品自己的输入框，
  // 不是直连库、也不是夹具；两次都不写就是真的没写，判失败。
  const memoryToolRows = page.locator('.tool-row', { hasText: '记录记忆' });
  for (let attempt = 0; attempt < MEMORY_WRITE_ATTEMPTS; attempt += 1) {
    if ((await memoryToolRows.count()) > 0) break;
    if (attempt === MEMORY_WRITE_ATTEMPTS - 1) break;
    const docsBeforeRetry = await page.locator('.msg-doc').count();
    expect(await sendFollowUp(page, REMEMBER_REQUEST), '补说一句「帮我记一下」的消息投递').toBe(202);
    await waitFirstToken(page);
    await waitRunSettled(page, docsBeforeRetry);
  }
  expect(
    await memoryToolRows.count(),
    '这一轮咨询没有调用「记录记忆」：记忆面没有别的创建入口，本轮不可能产生新记录（已补说一次仍没有）',
  ).toBeGreaterThan(0);

  // ③ 设置页里的「我提过的事」入口（记忆页是次级页，本身不渲染 tab 栏）。
  await page.goto(`${BASE_URL}/settings`);
  await expect(page.locator('.tab-bar')).toBeVisible();
  const memoryEntry = page.getByRole('link', { name: /我提过的事/ });
  await expect(memoryEntry, '设置页应有「我提过的事」入口').toBeVisible({ timeout: 20_000 });
  await memoryEntry.scrollIntoViewIfNeeded();
  await shot(0);

  // 入口要真的是这一页的入口：点它得落到 `/settings/memory` 且页头对得上。
  await memoryEntry.click();
  await expect(page).toHaveURL(`${BASE_URL}/settings/memory`);
  await expect(page.locator('.sp-title')).toHaveText('我提过的事');

  // ④ 轮询到时间线出现记录（写入是异步的：模型调用 → 待写队列 → Worker → 图库）。
  await waitTimelineWithRecords(page, { toolCalled: true });

  // 非空洞性判据（缺一条就说明截到的是空壳，而不是「有记录的时间线」）：
  //   ① 至少一个日期分组、至少一条条目，且条目内容非空；
  //   ② 分组头与 meta 是这一页真实的措辞（「M月D日（N）」「发生时间 MM-DD HH:mm · 来自一次咨询」）；
  //   ③ 空态与失败卡**都不在场**（空态说明这条记录不存在，失败态说明根本没有读到）。
  const groups = page.locator('details.tile.group-collapse');
  expect(await groups.count(), '时间线应至少有一个日期分组').toBeGreaterThan(0);
  const firstRow = page.locator('article.list-row').first();
  const firstContent = ((await firstRow.locator('strong.lr-title').textContent()) ?? '').trim();
  expect(firstContent.length, '时间线条目的内容不能为空（空内容等于没记录）').toBeGreaterThan(0);
  await expect(groups.first().locator('summary')).toHaveText(/\d{1,2}月\d{1,2}日（\d+）/);
  await expect(firstRow.locator('p.lr-meta')).toHaveText(/发生时间 \d{2}-\d{2} \d{2}:\d{2}/);
  await expect(firstRow.locator('p.lr-meta')).toHaveText(/来自一次咨询/);
  await expect(page.locator('.empty-state'), '有记录时不该同时出现空态').toHaveCount(0);
  await expect(page.locator('.error-card'), '有记录时不该同时出现失败卡').toHaveCount(0);
  await groups.first().scrollIntoViewIfNeeded();
  await shot(1);

  // ⑤ 展开完整原文：默认两行截断，展开后按钮变成「收起」。
  await firstRow.getByRole('button', { name: '看完整内容', exact: true }).click();
  await expect(firstRow.getByRole('button', { name: '收起', exact: true })).toBeVisible();
  await firstRow.scrollIntoViewIfNeeded();
  await shot(2);

  // ⑥ 纠正表单：预填原文与发生时间——「纠正是在原文上改」这件事在图上要看得见。
  await firstRow.getByRole('button', { name: '纠正', exact: true }).click();
  const correctionHeading = page.locator('#memory-correction-title');
  await expect(correctionHeading).toHaveText('新增一条更正');
  const occurredAtInput = page.getByLabel('发生时间');
  const contentArea = page.getByLabel('内容');
  await expect(occurredAtInput, '纠正表单应预填原记录的发生时间').toHaveValue(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
  // 内容按「压掉空白后逐字相等」比对：原文里的换行与首尾空白在 `<textarea>` 与行内 `<strong>`
  // 里都是同一份字符，但排版用的空白不属于「预填与否」这件事。
  expect(oneLine(await contentArea.inputValue()), '纠正表单应预填原记录的内容').toBe(oneLine(firstContent));
  // 逐字相同会被前端判成「没有需要更正的地方」，所以改一处说法再提交。
  await contentArea.fill(`${firstContent}${CORRECTION_MARKER}`);
  await correctionHeading.scrollIntoViewIfNeeded();
  await shot(3);

  // ⑦ 提交纠正：先撤下旧记录、再写新记录（两步，后端同步等一次模型抽取）。
  const correctionResponse = page.waitForResponse(
    (response) => response.url().includes('/api/memory/episodes/') && response.url().endsWith('/correct'),
  );
  await page.getByRole('button', { name: '更正', exact: true }).click();
  const response = await correctionResponse;
  // 201 = 新记录写成；200 = 中间态（旧记录已撤下、新记录没写成）。两种都收下，
  // 「写没写成」由页面提示判定——判据是结构化事实在界面上的落点，不是状态码。
  expect([200, 201], `纠正的 HTTP 状态（响应体：${oneLine(await response.text()).slice(0, 200)}）`).toContain(
    response.status(),
  );

  // 结果提示是页面级状态（记录被移除后仍在），文案逐字来自 domain/failures.ts。
  const notice = page.locator('p[role="status"]');
  await expect(notice, '纠正提交后应出现结果提示').toBeVisible({ timeout: CORRECTION_TIMEOUT_MS });
  const noticeText = oneLine(await notice.innerText());
  // 中间态不当作成功：它意味着旧记录已不再作为依据、但新记录没写成，这条链没走完。
  expect(noticeText, '纠正没有写成新记录（中间态：原记录已撤下、新记录没写成）').toContain(
    '已新增一条更正，原记录不再作为依据',
  );

  // 原记录撤下、新记录进入时间线（纠正成功后页面重取第一页；重取是异步的，故轮询等它落定）。
  const correctedRow = page.locator('article.list-row').filter({ hasText: CORRECTION_MARKER });
  await expect
    .poll(async () => correctedRow.count(), { timeout: 20_000, message: '纠正后时间线应出现更正后的新记录' })
    .toBe(1);
  // 用「条目原文逐字相等」判原记录已不在，而不是子串匹配：新内容以原文开头，子串匹配恒真。
  const leftoverOriginal = await page.locator('article.list-row').evaluateAll(
    (nodes, content) =>
      nodes.filter((node) => (node.querySelector('strong.lr-title')?.textContent ?? '').trim() === content).length,
    firstContent,
  );
  expect(leftoverOriginal, '纠正后原记录应从时间线撤下（撤下是纠正的第一步）').toBe(0);
  await notice.scrollIntoViewIfNeeded();
  await shot(4);

  // ⑧ 删除确认单：只到「确认单出现」为止。
  //    真的点删除会不可逆地删掉这条真实记录，而且删掉之后这一轮材料就没有可看的条目了。
  await correctedRow.getByRole('button', { name: '删除', exact: true }).click();
  const sheet = page.getByRole('dialog');
  await expect(sheet, '删除前必须先出现确认单（不可逆操作不做二次确认是不允许的）').toBeVisible();
  await expect(sheet.getByRole('heading')).toHaveText('删除这条记录？');
  await expect(sheet).toContainText('删除后咨询和历史都不会再用到它');
  await shot(5);

  // 收起确认单（「取消」不是删除），并确认它真的关掉了、记录还在。
  await sheet.getByRole('button', { name: '取消', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(await correctedRow.count(), '取消删除后记录必须还在（本场景不删任何真实数据）').toBe(1);
});
