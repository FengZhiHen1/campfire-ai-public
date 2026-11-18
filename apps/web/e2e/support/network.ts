/**
 * 模块: e2e/support/network
 * 职责: 免后端的网络夹具装配——精确 pathname 匹配、兜底 fail-closed、字体放行与请求账本
 * 数据来源:
 *   - 原证物 orchestrator-20261002-001/T01.md: MUST — 裁决 D（page.route + 兜底 handler 必须让测试失败）
 *     与验收标准「任何 /api/** 请求若未被夹具命中，脚本以非 0 退出并点名该 URL」
 *   - .dsh/skills/code-craft/SKILL.md: MUST — CORE-07（边界显式，无静默兜底）
 * 边界:
 *   - 依赖: @playwright/test 的 Page/Route
 *   - 被依赖: e2e/shots.spec.ts
 * 禁止行为:
 *   - 禁止让未命中的 /api/** 请求静默通过（静默 404 会渲染成空态，看起来「截图成功」实则没验证到目标形态）
 *   - 禁止放行外部请求
 */

import { expect, type Page, type Route } from '@playwright/test';

import type { ApiFixture } from './fixtures';
import { BASE_URL } from './paths';

/** 业务接口前缀（infrastructure/http/client 的 API_PREFIX）。 */
export const API_PREFIX = '/api';

/** 一次请求的记录。 */
export interface RequestRecord {
  /** 完整 URL（含查询串）。 */
  url: string;
  /** pathname（不含查询串）。 */
  pathname: string;
  method: string;
  /** 命中的夹具描述；未命中为 null。 */
  matched: string | null;
}

/**
 * 请求账本：判定「哪些端点被请求过 / 没被请求过」时的唯一依据。
 *
 * 字段刻意保持精简：每个字段都必须有真实的写入点与读取者。
 * 本轮 P2-1 删掉了 `failClosedViolations` 与 `aborted` 两个从无写入点的字段——
 * 它们当初配的注释还承诺了「兜底 handler 里 `expect.soft(...)` 的失败会走这条路」，
 * 而兜底 handler 里根本没有 `expect.soft`。注释承诺一个不存在的机制比字段多余更糟：
 * 后来者会据此以为「未命中一定已被收集并断言」，从而不去写那条断言。
 */
export interface RequestLedger {
  records: RequestRecord[];
  /** 未被任何夹具命中的 `/api/**` 请求（fail-closed 的判据，由 `expectNoUnmatchedApi` 读取）。 */
  unmatched: RequestRecord[];
  /** 被阻断的外部请求（非本机预览服务器、也不在放行白名单里；由 `expectNoExternalRequests` 读取）。 */
  blockedExternal: RequestRecord[];
}

/** 新建一本空账本。 */
export function createLedger(): RequestLedger {
  return { records: [], unmatched: [], blockedExternal: [] };
}

/** 把一条记录格式化成「点名该 URL」所需的文本。 */
function describe(record: RequestRecord): string {
  return `${record.method} ${record.url}`;
}

/**
 * 装配网络夹具并返回请求账本。
 *
 * 前置: page 尚未 goto（route 必须在页面发起请求之前注册）
 * 后置: 夹具内的请求被即时 fulfill；未命中的 /api/** 请求被记录进 `unmatched` 并让页面
 *      收到 501（使空态/错误态可见）；白名单外的外部请求被 abort 并记录进 `blockedExternal`
 * 异常: 无——失败不以异常表达，而是落进账本的 `unmatched` / `blockedExternal`，
 *      由调用方用 `expectNoUnmatchedApi` / `expectNoExternalRequests` 显式断言。
 *      这样做的理由见那两个函数：断言点在用例体里，失败点与失败原因在同一处。
 *
 * 为什么匹配用精确 pathname 而不是 glob：glob 的 `**` 会把 `/api/consult/sessions`
 * 与 `/api/consult/sessions/{id}/messages` 同时吞掉，夹具一旦写错就会静默命中错误端点。
 * 精确 pathname 配「未命中即失败」的兜底，写错会立刻暴露成一条点名的失败。
 */
export async function installNetwork(page: Page, fixtures: readonly ApiFixture[]): Promise<RequestLedger> {
  const ledger = createLedger();

  // 兜底：先注册，后注册的 route 优先级更高，因此具体夹具会覆盖它。
  await page.route('**/*', async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());

    // 预览服务器自身的静态资源与页面导航放行（这是被测产物，不是外部依赖）。
    if (url.origin === BASE_URL) {
      const isApiCall = url.pathname === API_PREFIX || url.pathname.startsWith(`${API_PREFIX}/`);
      if (!isApiCall) {
        await route.continue();
        return;
      }

      const record: RequestRecord = { url: request.url(), pathname: url.pathname, method: request.method(), matched: null };
      ledger.records.push(record);
      ledger.unmatched.push(record);

      // 未命中的业务请求返回 501（不是 404）：页面的错误态会显式呈现「未预期错误」，
      // 而不是渲染成一片空列表。同时给一个可解析的 JSON 正文，避免页面因解析失败
      // 抛出与真实原因无关的异常、掩盖「夹具没写」这一事实。
      await route.fulfill({
        status: 501,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: `截图夹具未覆盖 ${request.method()} ${url.pathname}：请在 e2e/support/fixtures.ts 里补一条夹具，或把该端点加入 mustNotRequest`,
        }),
      });
      return;
    }

    // 页面与截图均不加载第三方静态资源。
    const external: RequestRecord = { url: request.url(), pathname: url.pathname, method: request.method(), matched: null };
    ledger.records.push(external);
    ledger.blockedExternal.push(external);
    await route.abort('blockedbyclient');
  });

  // 具体夹具：后注册者优先，因此它们都覆盖上面的兜底。
  for (const fixture of fixtures) {
    await page.route(
      (url) => url.pathname === fixture.path,
      async (route: Route) => {
        const request = route.request();
        if (request.method() !== fixture.method) {
          // 方法不符不算命中：它说明调用点与夹具的约定不一致，必须暴露而不是放行。
          const record: RequestRecord = {
            url: request.url(),
            pathname: new URL(request.url()).pathname,
            method: request.method(),
            matched: null,
          };
          ledger.records.push(record);
          ledger.unmatched.push(record);
          await route.fulfill({
            status: 501,
            contentType: 'application/json',
            body: JSON.stringify({
              detail: `夹具 ${fixture.path} 只声明了 ${fixture.method}，实际收到 ${request.method()}`,
            }),
          });
          return;
        }

        const body = typeof fixture.body === 'function' ? (fixture.body as () => unknown)() : fixture.body;
        ledger.records.push({
          url: request.url(),
          pathname: fixture.path,
          method: request.method(),
          matched: `${fixture.method} ${fixture.path}`,
        });
        await route.fulfill({
          status: fixture.status ?? 200,
          contentType: 'application/json',
          body: JSON.stringify(body),
        });
      },
    );
  }

  // mustNotRequest 是「必须为空」清单：它不改本函数的行为，判定由 spec 的
  // expectNeverRequested 承担——不在这里藏一个只有本函数知道的隐式状态。
  return ledger;
}

/**
 * 等待请求账本静默下来。
 *
 * 前置: page 已 goto
 * 后置: 在不超过 `maxWaitMs` 的范围内等到「连续 `quietMs` 没有新请求」，或有界超时后返回
 * 异常: 无——超时不是错误，只是「静默窗口没等到」；账本此刻仍然是完整的可判定输入
 *
 * 为什么需要它：fail-closed 判定必须早于内容断言（它是内容断言的前提——夹具没覆盖全，
 * 内容断言失败的原因就不再是「页面形态不对」而是「夹具没写」）。但此刻页面的请求可能
 * 还没发完，直接判定会把「还没发出」误判成「没被覆盖」。因此先等一个静默窗口。
 *
 * 为什么不用 `page.waitForLoadState('networkidle')`：那会挂在持续的轮询/长连接上，
 * 而本基建需要的是「账本不再增长」这一本地事实，与页面的网络生命周期无关。
 */
export async function waitForLedgerQuiet(
  ledger: RequestLedger,
  options: { quietMs?: number; maxWaitMs?: number } = {},
): Promise<{ settled: boolean; elapsedMs: number }> {
  const quietMs = options.quietMs ?? 300;
  const maxWaitMs = options.maxWaitMs ?? 5_000;
  const started = Date.now();
  let lastCount = ledger.records.length;
  let lastChangeAt = Date.now();

  while (Date.now() - started < maxWaitMs) {
    await new Promise((resolve) => setTimeout(resolve, 50));
    if (ledger.records.length !== lastCount) {
      lastCount = ledger.records.length;
      lastChangeAt = Date.now();
      continue;
    }
    if (Date.now() - lastChangeAt >= quietMs) {
      return { settled: true, elapsedMs: Date.now() - started };
    }
  }
  return { settled: false, elapsedMs: Date.now() - started };
}

/**
 * 断言请求账本没有 fail-closed 违规。
 *
 * 前置: 页面已完成渲染与内容断言
 * 后置: 通过——没有任何未被夹具命中的 /api/** 请求；未通过时抛出点名 URL 的错误
 * 异常: Error——消息逐个列出未命中的 `METHOD URL`
 *
 * 为什么单独成函数而不是塞进 afterEach：Playwright 的 afterEach 里失败会被记成
 * 「清理期间的错误」，与断言失败的诊断价值不同；放在用例体里，失败点与失败原因在同一处。
 */
export function expectNoUnmatchedApi(ledger: RequestLedger): void {
  expect(
    ledger.unmatched.map(describe),
    '有 /api/** 请求未被夹具命中（fail-closed）：这些请求会渲染成空态或错误态，截图不能作为目标形态的证据',
  ).toHaveLength(0);
}

/** 断言没有发生任何外部（非本机预览服务器、也不在被接管清单里）请求。 */
export function expectNoExternalRequests(ledger: RequestLedger): void {
  expect(
    ledger.blockedExternal.map(describe),
    '存在被阻断的外部请求：页面或资源离开了本地预览服务器',
  ).toHaveLength(0);
}

/**
 * 断言「必须为空」的端点前缀确实一次都没被请求过。
 *
 * @param ledger 请求账本
 * @param prefixes 端点的 pathname 前缀（如 `/api/consult/runs/`）
 */
export function expectNeverRequested(ledger: RequestLedger, prefixes: readonly string[]): void {
  for (const prefix of prefixes) {
    const hits = ledger.records.filter((record) => record.pathname.startsWith(prefix));
    expect(
      hits.map(describe),
      `端点前缀 ${prefix} 属于「必须为空」清单，但本次运行被请求了`,
    ).toHaveLength(0);
  }
}