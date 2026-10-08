/**
 * @vitest-environment node
 *
 * 模块: tests/routes-coverage
 * 职责: 把「每个产品路由都必须有人截图」变成会失败的检查——防止截图标准静默腐烂
 * 数据来源:
 *   - apps/web/src/app/routes.tsx: MUST — 路由表的单一事实源（本文件以它为准，不另抄清单）
 *   - apps/web/e2e/support/{paths,fixtures}.ts: MUST — 截图矩阵的页面清单
 *   - docs/design/pages/: MUST — 十个页面设计文档与十条路由一一对应
 *   - docs/项目结构设计.md: MUST — 第 9 节（路由与页面）
 * 边界:
 *   - 依赖: vitest、src/app/routes、e2e/support/{paths,fixtures}
 *   - 被依赖: 无（`pnpm test` 收集）
 * 禁止行为:
 *   - 禁止把期望的页面清单抄成本文件的字面量（那样新增路由时它照样绿，等于没有检查）
 *   - 禁止在「路由多 / 截图少」时降级成 warning（必须失败，见下方为什么不警告）
 *
 * ## 为什么需要这个文件（一个真实的空洞，2026-10-07 实测）
 *
 * 拆分 `shots` / `e2e` 两条入口后，`e2e/manifest.spec.ts` 校验的是
 * 「`PAGE_NAMES.length` × 视口 × 图种 = 40 张」——**它只验矩阵内部自洽**。
 * 也就是说：往 `APP_ROUTES` 里加一条路由而忘了往 `PAGE_SHOTS` 里加对应项时，
 * `PAGE_NAMES` 没变 ⇒ **仍然恰好 40 张、manifest 仍然绿、`pnpm shots` 仍然通过**，
 * 而新页面**一张图都没有**。
 *
 * 这正是 `AGENTS.md` 明令禁止的「永远不会失败的检查」：需求是「每个页面都能截图」，
 * 而此前**没有任何机械判据把它与路由表连起来**——它只存在于人的记忆里。
 * 实测（2026-10-07）：`APP_ROUTES` 9 条 + `/login` = **10** 条路由，
 * `PAGE_SHOTS` **10** 项，当前一一对应；但这条对应关系此前无检查守着。
 *
 * ## 为什么放在 `tests/` 而不是放进 `e2e/` 的 spec
 *
 * 本用例要读**产品的**路由表（`buildRouteObjects()`），而 `routes.tsx` 会连带 import
 * `*.module.css`。Playwright 的 Node 加载器不处理 CSS（实测报
 * `SyntaxError: …guidePage.module.css: Unexpected token`），vitest 则经 Vite 转换、
 * 与 `src/app/routes.test.tsx` 同一路径 ⇒ 只有 vitest 能真实读取路由表。
 * 另：`e2e/support/paths.ts` 明令「禁止从 src 下任何模块 import 本文件」，
 * 因此**不能**反过来把 e2e 的常量搬进 src，只能在这类跨层用例里同时引用两边。
 *
 * ## 为什么不写成 warning
 *
 * 「路由有了、截图没有」不是风格问题，而是**验收证据的缺口**：审查者会以为
 * 「十个页面都截过了」。把它降级成 warning 等于把缺口留在安静的一侧。
 */

import { describe, expect, it } from 'vitest';

import { buildRouteObjects } from '../src/app/routes';
import { PAGE_SHOTS } from '../e2e/support/fixtures';
import { PAGE_NAMES } from '../e2e/support/paths';

/**
 * 取产品路由的 path 集合（不含通配路径）。
 *
 * 用 `buildRouteObjects()` 而不是 `APP_ROUTES`：`/login` **只**出现在前者里
 * （它不受守卫保护，因此在路由表之外单独挂），而登录页是必须截图的一页。
 * 通配路径 `*` 不是页面，排除。
 */
function productRoutePaths(): string[] {
  return buildRouteObjects()
    .map((route) => route.path)
    .filter((path): path is string => path !== undefined && path !== '*');
}

/**
 * 两段路径是否指同一页。
 *
 * 为什么要按「段」比而不是按字符串比：路由里的参数与截图里的实参形态不同——
 * 路由是 `/consult/sessions/:sessionId`，而截图配置写的是
 * `` `/consult/sessions/${CHAT_SESSION_ID}` ``，求值后成了 `/consult/sessions/sess-1001`。
 * 直接字符串比较会把这一对判成不匹配，于是**真页面被报成缺图**（假红）。
 *
 * 判据：段数相同，且每一段或逐字相同、或至少一侧是参数段（以 `:` 开头）。
 */
function sameRoute(routePath: string, shotPath: string): boolean {
  const routeSegments = routePath.split('/');
  const shotSegments = shotPath.split('/');
  if (routeSegments.length !== shotSegments.length) return false;
  return routeSegments.every((segment, index) => {
    const other = shotSegments[index];
    if (other === undefined) return false;
    return segment === other || segment.startsWith(':') || other.startsWith(':');
  });
}

describe('截图标准：路由表 ↔ 截图配置一一对应', () => {
  it('非空洞性：路由表解析出了页面（解析失效时必须报红，而不是比对两个空集）', () => {
    // 这条是本文件其余用例的**前提守卫**。没有它，一旦 `buildRouteObjects()` 改成
    // 返回别的形状（或过滤条件写错把一切滤掉），上面两个「过滤后为空」的断言
    // 会**双双通过**——那正是「永远不会失败的检查」。
    const routePaths = productRoutePaths();
    expect(routePaths.length, '路由表里应有页面路由；为 0 说明本用例的取法已失效').toBeGreaterThan(0);
    expect(new Set(routePaths).size, '路由路径有重复').toBe(routePaths.length);
  });

  it('每条产品路由都有截图配置（缺一条就是该页永远不会有 PNG）', () => {
    const routePaths = productRoutePaths();
    const shotPaths = PAGE_SHOTS.map((shot) => shot.path);

    const uncovered = routePaths.filter(
      (routePath) => !shotPaths.some((shotPath) => sameRoute(routePath, shotPath)),
    );
    expect(
      uncovered,
      '这些路由没有任何截图配置（往 PAGE_SHOTS 里补一项，或从路由表里去掉该页）：'
        + `\n路由表：${routePaths.join(', ')}\n截图配置：${shotPaths.join(', ')}`,
    ).toHaveLength(0);
  });

  it('每条截图配置都指向一条真路由（否则会静默截到 404 占位页）', () => {
    // 只查正方向会漏掉另一种腐烂：路由被删/改名后截图项留在原地，
    // 而它**仍然出图、仍然计入 40 张**，只是内容是 404。
    const routePaths = productRoutePaths();
    const orphaned = PAGE_SHOTS.filter(
      (shot) => !routePaths.some((routePath) => sameRoute(routePath, shot.path)),
    );
    expect(
      orphaned.map((shot) => `${shot.name}(${shot.path})`),
      '这些截图配置指向的路由已不在路由表里（截图会静默截到「页面不存在」占位页）',
    ).toHaveLength(0);
  });

  it('PAGE_NAMES 与 PAGE_SHOTS 逐项同名同序（两份清单并列维护）', () => {
    // `PAGE_NAMES` 是 manifest 张数口径与基线顺序，`PAGE_SHOTS` 决定实际落盘哪些 PNG。
    // 只改一处时，manifest 仍按 PAGE_NAMES 宣布「40 张」，与实际落盘不符。
    expect(PAGE_SHOTS.map((shot) => shot.name)).toEqual([...PAGE_NAMES]);
  });

  it('截图短名与路径都不重复（重复会互相覆盖而总数看不出来）', () => {
    const names = PAGE_SHOTS.map((shot) => shot.name);
    expect(new Set(names).size, `截图短名有重复：${names.join(', ')}`).toBe(names.length);

    const paths = PAGE_SHOTS.map((shot) => shot.path);
    expect(
      new Set(paths).size,
      `截图路径有重复（同一页截两遍、另一页没截）：${paths.join(', ')}`,
    ).toBe(paths.length);
  });
});
