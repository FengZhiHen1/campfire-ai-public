/**
 * 模块: e2e/support/page-open
 * 职责: 「打开一页」的唯一实现——注入登录态、装网络夹具、导航、等字体、判 fail-closed
 * 数据来源:
 *   - docs/证据/orchestrator-20261002-001/T01.md: MUST — 裁决 C（登录态注入）、
 *     裁决 D（夹具 fail-closed）、裁决 F（内容断言的观察前提）
 *   - apps/web/e2e/support/session.ts: MUST — 注入必须在 goto 之前（SDK 冷启动查一次会话）
 * 边界:
 *   - 依赖: @playwright/test、e2e/support/{session,network,fonts,fixtures}
 *   - 被依赖: e2e/shots.spec.ts（截图）与 e2e/content.spec.ts（断言）
 * 禁止行为:
 *   - 禁止把本文件的步骤在调用方各抄一遍（顺序是承重的：注入与夹具都必须早于 goto）
 *   - 禁止吞掉 fail-closed 判定（未覆盖的 /api 请求与清单外外部请求都必须让用例失败）
 *
 * 为什么抽出来（2026-10-07 拆分 `shots` 为「截图」与「断言」两条入口）：
 * 两个 spec 都需要「把页面开到目标形态」这一整套前置，而其中的顺序约束（先注入后 goto、
 * 先等账本静默再判 fail-closed）是过去几轮真实缺陷的产物。在截图与断言两处各写一遍，
 * 就等于给「其中一处漏掉一条顺序约束」留了口子——那种失效不会报错，只会让断言在错误的
 * 页面上求值。
 */

import type { Page, TestInfo } from '@playwright/test';

import { effectiveFixtures, type PageShot } from './fixtures';
import { awaitDisplayFont, type FontEvidence } from './fonts';
import {
  expectNeverRequested,
  expectNoExternalRequests,
  expectNoUnmatchedApi,
  installNetwork,
  waitForLedgerQuiet,
  type RequestLedger,
} from './network';
import { expectSessionInjected, installSession } from './session';

/**
 * 登录态注入开关（只给消融实验用，默认注入）。
 *
 * 任务包要求三次消融各自证明「机制能失败」：兜底 handler、登录态注入、内容断言。
 * 开关读环境变量而不是命令行选项：`playwright test` 会拒绝未知选项（同一理由见 paths.ts）。
 */
const SESSION_INJECTION_ENABLED = process.env.SHOTS_ABLATION_NO_SESSION !== '1';

/** 打开一页之后的全部前置证据与句柄；调用方据它做截图或断言。 */
export interface OpenedPage {
  /** 网络账本（含实际请求清单、放行/阻断的外部主机）。 */
  ledger: RequestLedger;
  /** 字体取证（fail-loud 判据的读数）。 */
  fontEvidence: FontEvidence;
  /** 页面自身的 console.error 与 pageerror 文本；调用方决定落盘还是忽略。 */
  pageProblems: string[];
}

/**
 * 把一页开到「目标形态」。
 *
 * 前置: page 是未导航的新 page
 * 后置: 已注入登录态、已装夹具、已导航、字体已就绪、fail-closed 判定已通过
 * 异常: 会话未注入 / 夹具未覆盖（fail-closed）/ 字体未加载 / 清单外外部请求 → 抛出
 *
 * @param page Playwright 的 page
 * @param shot 该页的截图配置（路由、夹具、必须为空的端点清单）
 * @param testInfo 用于把「账本未静默」这件事作为附件留痕
 */
export async function openPage(page: Page, shot: PageShot, testInfo: TestInfo): Promise<OpenedPage> {
  // 顺序不可调换：注入必须在 goto 之前（SDK 在冷启动查一次会话），
  // 夹具也必须在 goto 之前（首个接口请求可能早于 load 事件）。
  await installSession(page, { enabled: SESSION_INJECTION_ENABLED });
  const ledger = await installNetwork(page, effectiveFixtures(shot));

  const pageProblems: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') pageProblems.push(`console.error: ${message.text()}`);
  });
  page.on('pageerror', (error) => {
    pageProblems.push(`pageerror: ${error.message}`);
  });

  await page.goto(shot.path, { waitUntil: 'load' });

  if (shot.guarded) {
    await expectSessionInjected(page);
  }

  // 字体必须真的就绪才继续：字体 CDN 不可达时这里明确失败（裁决 2 的 fail-loud）。
  const fontEvidence: FontEvidence = await awaitDisplayFont(page);

  // fail-closed 判定必须早于内容断言：它是内容断言的前提。夹具没覆盖全时，
  // 「内容断言失败」会把原因指向页面形态，而真实原因是夹具没写。
  // 先等账本静默（页面请求发完），再点名未覆盖的 URL。
  const quiet = await waitForLedgerQuiet(ledger);
  if (!quiet.settled) {
    // 账本未在上界内静默：fail-closed 仍照常判定，但这件事必须留痕——
    // 静默丢弃它会让「请求还没发完就判通过」这种情况无声无息（P2-6）。
    await testInfo.attach(`${shot.name}-ledger-not-quiet.json`, {
      body: JSON.stringify(
        {
          settled: quiet.settled,
          elapsedMs: quiet.elapsedMs,
          recordCount: ledger.records.length,
          note: '账本未在上界内静默；fail-closed 判定仍然执行，但存在「判定时请求尚未发完」的可能',
        },
        null,
        2,
      ),
      contentType: 'application/json',
    });
  }
  expectNoUnmatchedApi(ledger);
  expectNoExternalRequests(ledger);
  expectNeverRequested(ledger, shot.mustNotRequest ?? []);

  return { ledger, fontEvidence, pageProblems };
}

/**
 * 把页面自身的问题落成附件（不阻断用例）。
 *
 * 为什么只登记不失败：console 错误可能来自第三方（字体 CDN 的告警）或已知的良性路径，
 * 而把它们一律判红会让这条基建失去区分度；但静默丢弃又会让审查者拿到一张「看不出发生过
 * 什么」的图，故落盘留痕。
 */
export async function attachPageProblems(testInfo: TestInfo, label: string, problems: readonly string[]): Promise<void> {
  if (problems.length === 0) return;
  await testInfo.attach(`${label}-page-problems.log`, {
    body: problems.join('\n'),
    contentType: 'text/plain',
  });
}
