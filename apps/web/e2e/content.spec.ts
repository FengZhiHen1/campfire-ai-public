/**
 * 模块: e2e/content
 * 职责: 逐页内容断言——证明「每页真的渲染出了有料的目标形态」，而不是空态或错误态
 * 数据来源:
 *   - 原证物 orchestrator-20261002-001/T01.md: MUST — 裁决 F（逐页内容断言，
 *     且必须能在内容缺失时失败，不许写成恒真）
 *   - apps/web/e2e/support/fixtures.ts: MUST — 每页的断言清单（本文件只负责求值与呈现）
 * 边界:
 *   - 依赖: e2e/support/{assertions,fixtures,page-open,paths}、@playwright/test
 *   - 被依赖: 无（由 `pnpm --filter @campfire/web e2e` 驱动）
 * 禁止行为:
 *   - 禁止把断言写成恒真（例如只断言「页面存在」）——它必须能在内容缺失时失败
 *   - 禁止在断言失败时吞掉异常（失败必须让用例失败，不降级成 warning）
 *   - 禁止在此处截图（截图归 shots.spec.ts；两条入口各自单一职责）
 *
 * 为什么与 shots.spec.ts 分开（2026-10-07 用户裁决「拆成两条」）
 *
 * 原先 `pnpm shots` 一条命令既截图又求值内容断言，后果是**内容断言一失败就一张图都没有**：
 * 而那正是最需要看图的时候——审查者要看「页面到底渲染成了什么样」，却被断言拦在了截图之前。
 * 拆开之后：`shots` 负责出图（无论内容断言是否通过都会出图），`e2e` 负责判定内容。
 *
 * **取舍如实登记**：拆开意味着 manifest 不再记录 `assertedContent`（跨运行无法与同一批 PNG
 * 对齐——Playwright 每次运行都会重开批号并清 `.run/`），因此「截图必须有料」这条不变量
 * **现在只由本文件承担**。跑完 `shots` 不等于验收通过，必须再跑 `e2e`。
 */

import { test } from '@playwright/test';

import { evaluateAssertions } from './support/assertions';
import { PAGE_SHOTS } from './support/fixtures';
import { attachPageProblems, openPage } from './support/page-open';

for (const shot of PAGE_SHOTS) {
  test(`${shot.name} 内容断言`, async ({ page }, testInfo) => {
    // 断言求值的前置（注入登录态、装夹具、等字体、fail-closed 判定）与截图完全同源：
    // 两者共用 openPage，避免「截图验的是一个形态、断言验的是另一个形态」。
    const { pageProblems } = await openPage(page, shot, testInfo);

    // 完整来源改为渐进展开，继续用原四条判据检查字段，不能靠减少命中数放过缺失。
    if (shot.name === 'cases') {
      for (const disclosure of await page.getByText('来源与适用范围', { exact: true }).all()) {
        await disclosure.click();
      }
    }

    // 断言数组为空时 evaluateAssertions 自己会抛（空数组等于没有断言，属配置错误）。
    // 断言失败即用例失败——不求值后续断言，由 evaluateAssertions 抛出。
    const evidence = await evaluateAssertions(page, shot.assertions);

    // 命中的特征串落成附件：审查者能据它回答「这条断言到底命中了什么」。
    await testInfo.attach(`${shot.name}-content-evidence.json`, {
      body: JSON.stringify({ page: shot.name, path: shot.path, evidence }, null, 2),
      contentType: 'application/json',
    });

    // 页面自身的 console 错误不阻断判定，但必须留痕（不静默）。
    await attachPageProblems(testInfo, shot.name, pageProblems);
  });
}
