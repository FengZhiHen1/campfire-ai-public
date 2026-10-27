/**
 * 模块: demo/scenarios/library.spec
 * 职责: 在真栈上纯浏览一遍「案例库 / 资料库」，按声明顺序逐帧截图
 * 数据来源:
 *   - ./library.schema.ts: MUST — 步骤顺序与讲解词
 *   - apps/web/src/features/library/view/LibraryPage.tsx:76-114,226-318: MUST — `.sp-title`、检索框、
 *     检索范围 `role=group`、结果行 `article.list-row`、`aria-controls="library-body-<id>"` 正文容器
 *   - apps/web/src/shared/ui/ReadableText.tsx:22-46: MUST — `.readable-*` 四类读物排版
 *   - apps/web/src/features/library/domain/reading.ts: `readingSection` 去掉同名小节定位标记
 *   - data/cases/2026-05-25_1448_respecting-pace-asd/manifest.json: 案例标题与检索词「节奏调整」的词面依据
 *   - apps/api/src/campfire/modules/library/routes.py:552-650: 展开内容随列表返回（`expand=<item_id>`）
 *   - apps/api/src/campfire/modules/library/retrieval.py:50,296-350: trigram 字面路需 ≥3 连续汉字
 * 边界:
 *   - 依赖: @playwright/test、./library.schema、../support/{shots,paths,stack}
 *   - 被依赖: playwright.demo.config.ts（project `demo`）
 * 禁止行为:
 *   - 禁止用 page.route / route.fulfill 伪造任何响应（伪造过的材料不再证明链路可用）
 *   - 禁止用 `article.list-row` 的 `.first()` 盲取（该行全站共用，盲取会拍到别的条目）
 *   - 禁止把「展开后有正文」降级成「元素存在」（空正文的展开态与没展开在截图上分不出）
 *   - 禁止把缺数据的情况 skip 掉（缺库就红，不安静留下一个空洞的镜头）
 */

import { expect, test, type Locator, type Page, type Response } from '@playwright/test';

import { LIBRARY } from './library.schema';
import { BASE_URL } from '../support/paths';
import { captureStep } from '../support/shots';
import { inviteCodeForScenario, invitePool, registerNewAccount } from '../support/stack';

/**
 * 本场景选用的案例：标题见 `data/cases/2026-05-25_1448_respecting-pace-asd/manifest.json`。
 *
 * 只取标题前半句做过滤（全角冒号与长标题的逐字匹配比子串更脆），
 * 而 `article.list-row` 是全站共用的类，因此每处取行都必须带 `hasText`。
 */
const CASE_TITLE_HINT = '从强迫到尊重';

/**
 * 检索词：取自案例标题「…的节奏调整与规则建立」（`data/cases/…/manifest.json`）。
 *
 * 为什么不用更短的「节奏」：`retrieval.literal_path_is_usable`（`retrieval.py:164-188`）要求
 * ≥3 连续汉字才走 trigram 字面路，2 个汉字只剩向量路——命中与否取决于向量排名，
 * 材料就会时红时绿。四个汉字让字面路（`title ILIKE`）也参与，判据落在真检索链上且确定。
 */
const KEYWORD = '节奏调整';

/** 展开正文的最小实质文本长度：短于此说明拍到的是空壳，「读物排版」就成了假话。 */
const MIN_BODY_CHARS = 100;

/** 列表与展开内容都是网络取数，给足但有限的上界（本机栈实测远小于此）。 */
const LOAD_TIMEOUT_MS = 20_000;

/** 取「标题含给定片段」的那一行；`article.list-row` 全站共用，必须带文本过滤。 */
function rowByTitle(page: Page, hint: string): Locator {
  return page.locator('article.list-row', { hasText: hint });
}

/** 取检索范围（案例 / 资料）这一组切换按钮，避免与页面其他 `button.tag` 混淆。 */
function scopeGroup(page: Page): Locator {
  return page.getByRole('group', { name: '检索范围' });
}

/** 这一次响应是不是资料库列表取数（再按某个查询参数收窄，避免等到别的请求）。 */
function isListResponse(response: Response, param: string, expected: string): boolean {
  return (
    response.url().includes('/api/library/items') && new URL(response.url()).searchParams.get(param) === expected
  );
}

/** 这一次响应是不是**带** `expand=` 的列表取数（展开内容随列表一并返回，契约第 4 节）。 */
function hasExpandParam(response: Response): boolean {
  return response.url().includes('/api/library/items') && new URL(response.url()).searchParams.has('expand');
}

/**
 * 备好一个已登录会话（本场景不展示注册屏，只借它过 `/cases` 的会话守卫）。
 *
 * 为什么需要：`/cases` 是 `requiresSession` 路由（`app/routes.tsx`），未登录会被转去 `/login`，
 * 于是「纯浏览」也先要有会话。池里的第 1 枚码归 onboarding，本场景用第 2 枚。
 *
 * 异常: 池不足两枚即显式失败——按下标取模回绕会拿到已经被消费过的码，
 *      那样会得到 HTTP 200 + `GENERAL_ERROR` 的假绿（见 `../support/stack.ts` 的说明）。
 */
async function ensureSession(page: Page, attempt: number): Promise<void> {
  if (invitePool().length < 2) {
    throw new Error('案例库场景需要第二枚邀请码：DEMO_INVITE_CODES 至少给两枚（第 1 枚归 onboarding）');
  }
  await registerNewAccount(page, inviteCodeForScenario(LIBRARY.slug, attempt));
}

test(LIBRARY.title, async ({ page }, testInfo) => {
  // 纯浏览、不开对话、不调模型：两分钟足够覆盖一次开户 + 六帧。
  test.setTimeout(120_000);
  const shot = (index: number) => captureStep(page, LIBRARY, index);

  await ensureSession(page, testInfo.retry);

  // ① 案例库列表：`/cases` 不带参数即默认落在案例分区（契约第 3 节）。
  await page.goto(`${BASE_URL}/cases`);
  await expect(page.locator('.sp-title')).toHaveText('案例库');
  await expect(page.getByRole('link', { name: '← 返回' })).toBeVisible();
  await expect(page.getByRole('searchbox', { name: '搜索案例' })).toBeVisible();
  await expect(scopeGroup(page).getByRole('button', { name: '案例' })).toHaveAttribute('aria-pressed', 'true');
  // 非空洞性：列表必须真有条目，且那条被本场景当作主角的案例在列表里。
  await expect(page.locator('article.list-row'), '案例库应有条目（空列表说明库里没有已入库案例）').not.toHaveCount(0);
  const targetRow = rowByTitle(page, CASE_TITLE_HINT);
  await expect(targetRow, `案例库列表里应出现「${CASE_TITLE_HINT}…」这条案例`).toHaveCount(1, {
    timeout: LOAD_TIMEOUT_MS,
  });
  const targetTitle = (await targetRow.locator('strong.lr-title').innerText()).trim();
  expect(targetTitle, '结果行标题应有文本').toContain(CASE_TITLE_HINT);
  await shot(0);

  // ② 就地展开：展开内容随列表返回（契约第 4 节），因此点击必然触发一次带 `expand=` 的取数。
  const toggle = targetRow.locator('button[aria-expanded]');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  const expandResponse = page.waitForResponse(hasExpandParam);
  await toggle.click();
  expect((await expandResponse).status(), '展开取数的 HTTP 状态').toBe(200);
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');

  const bodyId = await toggle.getAttribute('aria-controls');
  if (bodyId === null || !bodyId.startsWith('library-body-')) {
    throw new Error(`行按钮的 aria-controls 不是 library-body-<item_id>：${String(bodyId)}`);
  }
  const body = page.locator(`#${bodyId}`);
  await expect(body, '展开后的正文容器应可见').toBeVisible({ timeout: LOAD_TIMEOUT_MS });
  // 非空洞性：正文得有实质文本，而不是一个空的展开壳。
  const bodyText = (await body.innerText()).trim();
  expect(bodyText.length, '展开后的正文应有实质文本').toBeGreaterThan(MIN_BODY_CHARS);
  await expect(body.locator('h3'), '正文应带小节标题').not.toHaveCount(0);
  const readableBlocks = body.locator('.readable-paragraph, .readable-heading, .readable-list, .readable-quote');
  expect(await readableBlocks.count(), '正文应经 ReadableText 排成读物（至少一块 .readable-*）').toBeGreaterThan(0);
  await shot(1);

  // ③ 来源与适用范围：折叠块的默认态与展开态都要看得到差别，否则「收着」这句话没有依据。
  const sourceDetails = targetRow.locator('details', { hasText: '来源与适用范围' });
  await expect(sourceDetails, '每条案例都应带「来源与适用范围」折叠块').toHaveCount(1);
  await expect(sourceDetails.locator('dl'), '未展开时适用范围字段应收起').toBeHidden();
  await sourceDetails.locator('summary').click();
  await expect(sourceDetails.locator('dl'), '点开折叠块后适用范围字段应可见').toBeVisible();
  const factValues = await sourceDetails.locator('dd').allInnerTexts();
  expect(factValues.length, '折叠块里应有来源 / 适用范围字段').toBeGreaterThan(0);
  expect(factValues.join('').trim().length, '适用范围字段的值不应全为空').toBeGreaterThan(0);
  await shot(2);

  // ④ 资料库：同一路由换 `?section=knowledge`，页头与检索框一起换词。
  const knowledgeResponse = page.waitForResponse((response) => isListResponse(response, 'library', 'knowledge'));
  await page.goto(`${BASE_URL}/cases?section=knowledge`);
  expect((await knowledgeResponse).status(), '资料库列表的 HTTP 状态').toBe(200);
  await expect(page.locator('.sp-title')).toHaveText('资料库');
  await expect(scopeGroup(page).getByRole('button', { name: '资料' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('searchbox', { name: '搜索资料' })).toBeVisible();
  // 非空洞性：资料库不能是空列表，标题也不能全空。
  await expect(page.locator('article.list-row'), '资料库应有已入库条目').not.toHaveCount(0, {
    timeout: LOAD_TIMEOUT_MS,
  });
  const knowledgeTitles = await page.locator('strong.lr-title').allInnerTexts();
  expect(knowledgeTitles.length, '资料列表应有标题').toBeGreaterThan(0);
  expect(knowledgeTitles.join('').trim().length, '资料列表的标题不应全为空').toBeGreaterThan(0);
  await shot(3);

  // ⑤ 检索命中：先切回案例分区（关键词取自案例标题，见 KEYWORD 的说明），再输入关键词。
  const backToCases = page.waitForResponse((response) => isListResponse(response, 'library', 'case'));
  await scopeGroup(page).getByRole('button', { name: '案例' }).click();
  expect((await backToCases).status(), '切回案例分区的 HTTP 状态').toBe(200);
  await expect(page.locator('.sp-title')).toHaveText('案例库');

  const searchResponse = page.waitForResponse((response) => isListResponse(response, 'query', KEYWORD));
  await page.getByRole('searchbox', { name: '搜索案例' }).fill(KEYWORD);
  expect((await searchResponse).status(), '检索的 HTTP 状态').toBe(200);
  const hitRow = rowByTitle(page, CASE_TITLE_HINT);
  await expect(hitRow, `关键词「${KEYWORD}」应命中这条案例（真检索链，不是前端过滤）`).toHaveCount(1, {
    timeout: LOAD_TIMEOUT_MS,
  });
  const hitSnippet = (await hitRow.locator('p.lr-sub').innerText()).trim();
  expect(hitSnippet.length, '命中行的摘要应有文本').toBeGreaterThan(0);
  await shot(4);

  // ⑥ 深链定位：没有 `/cases/:id`，靠 `?item=<item_id>` 在这一页里定位并展开同一条。
  const itemId = bodyId.slice('library-body-'.length);
  await page.goto(`${BASE_URL}/cases?item=${itemId}`);
  await expect(page.locator('.sp-title')).toHaveText('案例库');
  const locatedRow = rowByTitle(page, CASE_TITLE_HINT);
  await expect(locatedRow, '深链应定位到同一条案例').toHaveCount(1, { timeout: LOAD_TIMEOUT_MS });
  await expect(locatedRow.locator('button[aria-expanded]'), '深链定位后该条应自动展开').toHaveAttribute(
    'aria-expanded',
    'true',
    { timeout: LOAD_TIMEOUT_MS },
  );
  const locatedBody = page.locator(`#${bodyId}`);
  await expect(locatedBody).toBeVisible({ timeout: LOAD_TIMEOUT_MS });
  // 非空洞性：深链展开的正文同样要有实质内容（否则定位到的只是一张空卡）。
  // 必须**轮询**到内容到齐：容器在 `expand=` 取数回来之前就已可见，直接读 innerText 会读到 0
  // （2026-10-27 实测就是这么红的：行已 expanded、容器可见，正文长度 0）。
  await expect
    .poll(async () => (await locatedBody.innerText()).trim().length, {
      timeout: LOAD_TIMEOUT_MS,
      message: '深链展开后的正文应有实质文本（容器可见 ≠ 内容已到）',
    })
    .toBeGreaterThan(MIN_BODY_CHARS);
  // 必须滚到展开的正文再截：深链落地时页面在顶部，不滚就会和第 1 帧（列表首屏）逐字节相同——
  // 那是「清单的帧唯一性判据」当场抓出来的（2026-10-28 实测），不是猜的。
  await locatedBody.scrollIntoViewIfNeeded();
  await shot(5);
});
