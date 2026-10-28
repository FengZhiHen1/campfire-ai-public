/**
 * 模块: demo/scenarios/consult-citation.spec
 * 职责: 真栈走一遍「日常咨询 → 真检索 → 依据区呈现」，按声明顺序截图，并如实标出回指缺口
 * 数据来源:
 *   - ./consult-citation.schema.ts: MUST — 步骤顺序与讲解词（本文件不另写一份文案）
 *   - ../support/stack.ts: MUST — 开户四层判据、咨询入口 `startDailyConsult`、正文首字、提问卡判据
 *   - apps/web/src/features/consult/view/MessageParts/CitationPart.tsx: 依据区形态——
 *     `details.citation-block`、summary「依据 N 条」、`article.citation-item`、`.citation-title`、
 *     来源行「来源：…」、标题是可点的 deep-link
 *   - apps/web/src/features/consult/view/MessageParts/ToolIndicator.tsx: 工具行 `details.tool-row`
 *     的 `data-state` 取 `running` / `finished`，行内文案形如「查阅资料 · 已结束」
 *   - apps/web/src/shared/types/sse.ts:79-86: `CitationRecord` 无 `item_id` ⇒ deep-link 恒为 null
 *   - apps/api/skills/onboarding/SKILL.md 与 modules/accounts/onboarding.py: 无行或 in_progress
 *     ⇒ 首轮注入引导；skipped / completed ⇒ 不注入（本场景必须先让引导终结，见下方说明）
 * 边界:
 *   - 依赖: @playwright/test、./consult-citation.schema、../support/{shots,stack,paths}
 *   - 被依赖: playwright.demo.config.ts（project `demo`）
 * 禁止行为:
 *   - 禁止用 page.route / route.fulfill 伪造 SSE、工具行或依据（真栈材料一旦伪造就不再证明链路可用）
 *   - 禁止把「依据区一定出现」写成硬断言：检索是否发生由模型决定，缺依据要记一条明确的不足，
 *     既不静默通过、也不让它吞掉后面的帧
 *   - 禁止只把依据区截下来就完事：回指已经可用（2026-10-28），最后一帧必须真的点进去
 *   - 禁止用「停止按钮消失」这类瞬时状态当本轮终态判据（实测会造成假红，理由见下方 waitRoundSettled）
 *
 * ## 为什么这条链要先让引导终结
 *
 * 全新账号的**首次日常会话首轮**由服务端注入 onboarding skill，而该 skill 的 `allowed-tools`
 * 不含 `search_knowledge` / `search_cases`，并且它一次一问地用提问卡把输入区收起（对话工作面的
 * `answering` 分支）——也就是说：新账号的第一轮**既不可能检索、也没法再自由提问**。
 * 本场景要拍的是「日常咨询 + 真检索」，因此先用产品自己的跳过端点（HTTP与SSE契约第 6 节，
 * 界面上没有入口，只能在 API 层面调用）把该账号的引导置为 `skipped`，再用共享入口
 * `startDailyConsult` 起一轮干净的日常咨询。
 *
 * 如实登记代价：跳过走的是**真实端点 + 真实会话 cookie**（真 HTTP，不是本装置禁止的 mock），
 * 但它不是界面上点得出来的路径；另外建会话与发消息在 `startDailyConsult` 里是捆在一起的，
 * 而跳过端点按会话判归属，所以这里会先建一个**不进入材料**的会话专门拿 id。
 * 两处都已在交付报告里写明（含「建议提升到 support/」的清单）。
 */

import { expect, test, type Page } from '@playwright/test';

import { CONSULT_CITATION } from './consult-citation.schema';
import { BASE_URL } from '../support/paths';
import { captureStep } from '../support/shots';
import {
  inviteCodeForScenario,
  registerNewAccount,
  startDailyConsult,
  waitFirstToken,
  waitMounted,
  waitRunSettled,
} from '../support/stack';

/**
 * 本场景提的问题。
 *
 * 三个条件同时满足才可用：
 * ① 具体到会触发检索（日常咨询的纪律是**给建议前先检索**；泛泛一句「你能做什么」检索与否全看模型心情）；
 * ② 与已入库的资料**真的对得上**，让检索一轮就够——本机库里的 7 条知识条目是国家规范/指南类文本，
 *    其中一条正是走失（wandering）主题；
 * ③ 窄到不触发多轮检索。2026-10-27 实测：问「超市广播音乐怎么办」这类大问题，模型会连查四五次资料，
 *    一次运行叠加六次模型调用，撞上产品 180 秒的单轮上限（页面挂「模型暂时不可用」），
 *    材料于是红在「模型太慢」而不是「链路不通」。
 */
// 问题选「走失怎么防」有两个实测理由：① 库里有对应语料（CDC 走失指引 + 筛查规范 + 干预指南），
// 检索能命中；② 它足够具体，模型不会一上来连查七八次——换「国家规范怎么要求」那种问题试过，
// 模型连着查了 7 次仍未成文，直接撞上 180 秒单轮上限（2026-10-28 实测）。
const QUESTION = '孩子出门容易走丢，我们平时可以怎么防？';

/** 案例库/资料库那一侧的加载上界（与 `library.spec.ts` 同一口径，不另立标准）。 */
const LOAD_TIMEOUT_MS = 20_000;

/** 静定判据的取样间隔：3 秒一次，够密到不错过收尾，也够疏到不把流式抖动当成新内容。 */

/**
 * 建一个日常会话并停在该页（**不提问**），返回会话 URL。
 *
 * 为什么需要它：引导跳过端点的路径参数是 `session_id`（它先按会话判归属再写账号状态），
 * 而 `startDailyConsult` 把「建会话」与「发第一条消息」封在同一个动作里——必须先有会话
 * 才谈得上跳过。判据与 `startDailyConsult` 逐条对齐：201、URL 落在会话页、输入框可见。
 */
async function openDailySession(page: Page): Promise<string> {
  await page.goto(`${BASE_URL}/consult`);
  await waitMounted(page);
  const created = page.waitForResponse(
    (response) => response.url().endsWith('/api/consult/sessions') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: /开始新的日常咨询/ }).click();
  expect((await created).status(), '建会话的 HTTP 状态').toBe(201);
  await expect(page).toHaveURL(/\/consult\/sessions\/[0-9a-z-]+/);
  await expect(page.locator('#consult-composer')).toBeVisible({ timeout: 20_000 });
  return page.url();
}

/**
 * 把这个账号的引导置为 `skipped`（HTTP与SSE契约第 6 节）。
 *
 * anti-CSRF 的**真实**判据：会话是 cookie 型且取 `VIA_CUSTOM_HEADER`
 * （`core/auth/supertokens.py:184`），而 SDK 在 `session_request_functions.py:182-190` 只做一件事——
 * **要求请求带 `rid` 头**，不看任何 cookie。第一版按「`sAntiCsrf` cookie + `anti-csrf` 头」
 * 实现（`VIA_TOKEN` 模式的形状），实测直接抛「取不到 anti-CSRF 令牌」。
 * 这里用 `page.request`（与浏览器共享 cookie 存储）发真实 HTTP 请求，`rid` 头照 SDK 的写法给。
 *
 * 异常: 非 200、或状态不是 `skipped`——一律抛出（不降级、不当作已跳过）
 */
async function skipOnboarding(page: Page, sessionUrl: string): Promise<void> {
  const sessionId = sessionUrl.split('/').pop() ?? '';
  const response = await page.request.post(`${BASE_URL}/api/consult/sessions/${sessionId}/onboarding/skip`, {
    headers: { rid: 'anti-csrf', 'content-type': 'application/json' },
    data: {},
  });
  expect(response.status(), '跳过引导端点的 HTTP 状态').toBe(200);
  const body = (await response.json()) as { state?: string };
  expect(body.state, '跳过引导后的状态').toBe('skipped');
}

test(CONSULT_CITATION.title, async ({ page }, testInfo) => {
  // 真实模型：一轮日常咨询（含检索调用）实测 30–120 秒，最坏情形要走两轮，故给到 6 分钟。
  test.setTimeout(900_000);
  const shot = (index: number) => captureStep(page, CONSULT_CITATION, index);

  // 开户：四层判据在 `registerNewAccount` 里（HTTP 200 + body OK + 跳首页 + 标签栏可见）。
  // 邀请码下标：onboarding 场景占 0，本场景占 1——一枚码 = 一个全新账号。
  await registerNewAccount(page, inviteCodeForScenario(CONSULT_CITATION.slug, testInfo.retry));

  // ① 咨询入口：新账号的咨询列表是空的，入口就是「开始新的日常咨询」。
  await page.goto(`${BASE_URL}/consult`);
  await waitMounted(page);
  await expect(page.getByRole('button', { name: /开始新的日常咨询/ })).toBeVisible({ timeout: 20_000 });
  await shot(0);

  // 前置（不进入材料）：让这个账号的引导终结，理由见文件头「为什么这条链要先让引导终结」。
  // 这里建的会话只为给跳过端点提供归属凭据，随后真正提问走 `startDailyConsult` 新建的会话。
  await skipOnboarding(page, await openDailySession(page));

  // ② 提问：这一句作为会话的第一条消息发出（新会话的首轮不再注入引导）。
  const docsBeforeFirstRound = await page.locator('.msg-doc').count();
  await startDailyConsult(page, QUESTION);
  // 用提问原文的前几个字定位，而不是写死某几个字：问题改过一次，写死的那次直接假红。
  const questionMark = QUESTION.slice(0, 6);
  await expect(page.locator('.bubble-user', { hasText: questionMark }).first(), '使用者消息应已进入消息流').toBeVisible({
    timeout: 20_000,
  });
  await shot(1);

  // ③ 首字：正文开始流式输出，且段落排版已经生效（`.msg-doc` 里的 `.readable-paragraph`）。
  await waitFirstToken(page);
  // `waitFirstToken` 只看「`.msg-doc` 里有字」，而这一轮的 `.msg-doc` 可能只是工具行容器；
  // 真正要等的是**正文段落**出现。2026-10-27 实测：45 秒等不到段落时抓到的现场是
  // 「查阅资料 · 进行中 + 停止按钮」，也就是模型还在跑、正文还没开始——不是产品坏了。
  const answerParagraphs = page.locator('.msg-doc').last().locator('.readable-paragraph');
  await expect
    .poll(
      async () => {
        // 失败态优先：撞上单轮上限时页面会挂 `.error-card`，先认它，别白等满 200 秒。
        const error = page.locator('.error-card');
        if ((await error.count()) > 0) {
          const text = (await error.first().innerText().catch(() => '')).replace(/\s+/g, ' ').trim();
          throw new Error(`这一轮运行失败，页面报错：${text === '' ? '（读不到错误卡片文案）' : text}`);
        }
        return (await answerParagraphs.count()) === 0 ? 0 : (await answerParagraphs.first().innerText()).trim().length;
      },
      { timeout: 200_000, message: '正文段落始终没有出现（模型仍在思考，或本轮失败——看页面错误卡片/后端日志）' },
    )
    .toBeGreaterThan(0);
  await page.locator('.msg-doc').last().scrollIntoViewIfNeeded();
  await shot(2);

  // ④ 等这一轮落定。**不追答模型抛出的追问**——这是刻意的：
  //    日常咨询的纪律是「一次只推进一件事」，答完第一组追问会立刻起第二轮，而第二轮又会
  //    再检索四五次，一次运行叠加到六次以上模型调用就撞上产品 180 秒的单轮上限，
  //    材料于是红在「模型太慢」而不是「链路不通」（2026-10-27 实测，两次都倒在这里）。
  //    要展示的东西第一轮就已经齐了：成文回答 + 依据区。追问那一帧留着不答，也是真实形态。
  const outcome = await waitRunSettled(page, docsBeforeFirstRound);
  expect(outcome === 'done' || outcome === 'question', '这一轮应给出成文回答（哪怕末尾继续追问）').toBe(true);

  // 非空洞性：检索必须真的被调用过（工具行默认收起，但节点存在）。
  // 这是本场景的核心主张，故为硬断言——没有检索，后面谈「依据」就是空话。
  const retrievalRows = page.locator('.tool-row', { hasText: /查阅资料|查阅案例/ });
  expect(
    await retrievalRows.count(),
    '这一轮应至少有一次「查阅资料」或「查阅案例」的工具调用：没有检索就没有依据可谈，材料不成立',
  ).toBeGreaterThan(0);
  // 展开最近一次检索：收起态只有一行名称，展开后才是「检索到了什么」，这是这一步的看点。
  await retrievalRows.last().locator('summary').click();
  await expect(retrievalRows.last()).toHaveJSProperty('open', true);
  await retrievalRows.last().scrollIntoViewIfNeeded();
  await shot(3);

  // ⑤ 完整回答：建议与适用范围都在正文里，段落排版是本轮最终形态。
  //    必须**轮询**：引导被跳过之后模型常会先追问一轮，答完又起第二轮（实测会继续检索）。
  //    20 秒的死等会撞在「上一轮已结束、下一轮还没出字」的空档上，被误读成「正文没渲染」。
  const lastDoc = page.locator('.msg-doc').last();
  await expect
    .poll(
      async () =>
        (await lastDoc.locator('.readable-paragraph').count()) === 0
          ? 0
          : (await lastDoc.locator('.readable-paragraph').last().innerText()).trim().length,
      { timeout: 200_000, message: '最后一条正文始终没有段落（模型可能仍在跑，或本轮失败）' },
    )
    .toBeGreaterThan(0);
  await lastDoc.locator('.readable-paragraph').last().scrollIntoViewIfNeeded();
  await shot(4);

  // ⑥ 依据区：存在就展开截图；不存在就截当前回答并记一条明确的不足。
  //    条件分支的理由：检索与引用是否发生由模型决定，把它写成硬断言会让材料时红时绿。
  //    **取第一条**而不是最后一条：第二轮往往还在流式输出，最后一轮的依据区此刻可能还没挂出来；
  //    要展示的是「本轮回答有依据」这一事实，第一条完整回答就足以证明（实测该轮有「依据 25 条」）。
  const citationBlock = page.locator('.msg-doc details.citation-block').first();
  const citationBlocks = await citationBlock.count();
  if (citationBlocks > 0) {
    const block = citationBlock.first();
    // 默认收起是设计契约（对话页第 5 节），先确认这一形态，再展开。
    await expect(block).toHaveJSProperty('open', false);
    await expect(block.locator('summary')).toContainText(/依据\s*\d+\s*条/);
    const items = block.locator('article.citation-item');
    expect(await items.count(), '依据区至少要有一条依据（空折叠头不该渲染）').toBeGreaterThan(0);
    await block.locator('summary').click();
    await expect(block).toHaveJSProperty('open', true);
    // 回指可用的机械判据（2026-10-28 起）：标题是链接，目标形如 /cases?item=<标识>，
    // 来源行不再出现「本条暂不能跳转到来源条目」。
    await expect(items.first()).toContainText('来源：');
    const firstTitle = items.first().locator('.citation-title');
    await expect(firstTitle, '依据标题应是可点链接（回指断在这里就是链路断了）').toHaveAttribute(
      'href',
      /^\/cases\?item=[^&#]+$/u,
    );
    await expect(items.first()).not.toContainText('本条暂不能跳转到来源条目');
    await block.scrollIntoViewIfNeeded();
    await shot(5);

    // ⑦ 真的点进去：落到案例库浏览页的那一条，正文展开且有实质内容。
    const href = await firstTitle.getAttribute('href');
    const citationTitleText = (await firstTitle.innerText()).trim();
    expect(citationTitleText.length, '依据标题应有可读文本').toBeGreaterThan(0);
    await firstTitle.scrollIntoViewIfNeeded();
    await firstTitle.click();
    await expect(page, '点依据标题应跳到案例库浏览页的条目深链').toHaveURL(
      new RegExp(`${String(href ?? '').replace(/[.*+?^${}()|[\]\\]/gu, '\\$&')}$`, 'u'),
      { timeout: 20_000 },
    );
    // 正文容器的 id 是 `library-body-<item_id>`（见 `LibraryPage.tsx`）：**按 id 精确定位**，
    // 不要用 `[id^="library-body-"]` 取第一个——列表里每条都有正文容器，取到的是别人的（空的）。
    const itemId = new URL(`http://placeholder${String(href)}`).searchParams.get('item') ?? '';
    expect(itemId, '依据链接里应带 item 参数').not.toBe('');
    // 取**整篇文章**而不是里面的按钮：标题与出处分属两个兄弟节点（`LibraryPage` 的
    // `<button>…</button><ItemProvenance/></article>`），只选按钮会读不到「来源：」。
    const deepLinkedRow = page.locator('article.list-row:has(button[aria-expanded="true"])');
    await expect(deepLinkedRow.first(), '深链定位后该条应自动展开').toBeVisible({ timeout: LOAD_TIMEOUT_MS });
    // 落到的是哪一条？用它自己的标题核对——「页面有内容」不等于「到了依据指的那一条」。
    await expect(deepLinkedRow.first(), '展开的那条应当就是依据指向的条目').toContainText(citationTitleText);
    // 条目出处必须已渲染（`来源：…`）；正文长度不作为判据：资料库条目未必有正文分节
    // （`campfire_knowledge_item` 没有 narrative 列，案例条目才有 cards），拿长度当判据会
    // 把「这条资料本来就没有正文」误判成「跳转失败」。2026-10-28 实测过这个错判。
    await expect(deepLinkedRow.first()).toContainText('来源：');
    const deepBody = page.locator(`#library-body-${itemId}`);
    await expect(deepBody, '依据指向的条目正文容器应可见').toBeVisible({ timeout: LOAD_TIMEOUT_MS });
    await deepLinkedRow.first().scrollIntoViewIfNeeded();
    await shot(6);
  } else {
    // 不静默通过：明确记一条不足（它在用例结束时把这条用例判红）；
    // 也不假红：截图照拍，6 帧仍然齐备，manifest 的「声明 ⇔ 产物」不会因为一个概率分支而缺页。
    expect
      .soft(
        citationBlocks,
        '最后一轮回答尾部没有依据区（details.citation-block）：这一轮没有可展示的引用，场景的核心链路未呈现',
      )
      .toBeGreaterThan(0);
    await lastDoc.locator('.readable-paragraph').last().scrollIntoViewIfNeeded();
    await shot(5);
    // 没有依据区就没有第 7 帧可拍：这里**如实缺页**，让清单判据（声明 ⇔ 产物）当场报红，
    // 而不是拿第 6 帧凑数糊上一层「看起来齐了」。
    return;
  }
});
