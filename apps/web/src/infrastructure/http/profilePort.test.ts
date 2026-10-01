/**
 * 模块: src/infrastructure/http/profilePort.test
 * 职责: 档案端口的查询参数回归守卫——历史（已更正）条目的 opt-in 开关真有出口
 * 数据来源:
 *   - docs/技术设计/面/profile/档案面HTTP契约.md: MUST — 第 3 节（条目读取的查询参数与分组）
 *   - docs/design/pages/档案页.md: MUST — 第 33、62 行（历史条目出行首「已更正」标）
 * 边界:
 *   - 依赖: infrastructure/http/profilePort、http/client
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言契约外的路径或查询参数（本用例只钉 `include_superseded` 的有无）
 *
 * 为什么这一层也要守卫：页面用例注入的是端口替身，端口实现把开关丢掉它照样绿——
 * 那是「测试守护 bug」的形态（页面断言齐全而真实请求没带参数）。这里钉住
 * 「缺省不发、opt-in 才发」这段真实拼串逻辑，消融掉 profilePort 的那一行即变红。
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { httpProfilePort } from './profilePort';

/** 空的条目页响应（本用例只关心请求形状，不关心载荷）。 */
function emptyPage(): Response {
  return new Response(JSON.stringify({ items: [], candidates: [], next_cursor: null }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** 打桩 fetch 并记录每次请求的 URL。 */
function stubFetch(seen: string[]): void {
  vi.stubGlobal(
    'fetch',
    (async (input: RequestInfo | URL) => {
      seen.push(String(input));
      return emptyPage();
    }) as unknown as typeof fetch,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('httpProfilePort.listItems — 历史条目的 opt-in 开关', () => {
  it('缺省请求不带 include_superseded：服务端按 false 处理，历史条目不返回', async () => {
    const seen: string[] = [];
    stubFetch(seen);

    await httpProfilePort.listItems('o1');

    expect(seen).toEqual(['/profile/objects/o1/items']);
  });

  it('opt-in 后请求带上 include_superseded=true，且与候选开关可同时出现', async () => {
    const seen: string[] = [];
    stubFetch(seen);

    await httpProfilePort.listItems('o1', { includeCandidates: true, includeSuperseded: true });

    expect(seen).toEqual(['/profile/objects/o1/items?include_candidates=true&include_superseded=true']);
  });
});
