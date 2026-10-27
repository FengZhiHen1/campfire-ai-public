/**
 * 模块: demo/manifest.spec
 * 职责: 汇总核对——声明、产物、批号、磁盘实读四者必须对得上；通过后写出可复算的 manifest.json
 * 数据来源:
 *   - docs/运维/演示材料生成.md: MUST — 四步判据与「清单存在 ⇔ 本轮核对通过」
 *   - apps/web/e2e/states.spec.ts: 同型核对做法
 * 边界:
 *   - 依赖: ./support/manifest、./scenarios/registry
 *   - 被依赖: 无（链路末端）
 * 禁止行为:
 *   - 禁止在核对失败时仍写出 manifest（那会让「清单在」不再能证明「本轮通过」）
 */

import { expect, test } from '@playwright/test';

import { SCENARIOS } from './scenarios/registry';
import { buildDemoManifest, writeDemoManifest } from './support/manifest';
import { SCENARIO_SLUGS } from './support/paths';

test('演示材料齐备且与磁盘一致，写出 manifest', async () => {
  const { manifest, problems } = await buildDemoManifest(SCENARIOS);

  // 逐条列出问题：只说「不一致」会让人去翻目录，而不是去修那一处。
  expect(problems, `演示材料核对失败（${String(problems.length)} 条）：\n- ${problems.join('\n- ')}`).toEqual([]);

  // 非空洞性：核对通过还必须意味着「真有一批图」，否则空目录也能过。
  // 两条都用**独立真源**（登记清单与 0），不用 `SCENARIOS.length`：
  // 声明集合清空时，与自身比较恒真，那条断言就永远不会失败（独立复查 FAIL-7）。
  expect(manifest.totals.scenarios).toBe(SCENARIO_SLUGS.length);
  expect(manifest.totals.shots).toBeGreaterThan(0);

  const file = await writeDemoManifest(manifest);
  // 用 annotation 而不是 console.log：仓库 oxlint 把 `no-console` 定为 error，
  // 而 list reporter 会把 annotation 打出来，信息一样能被看见。
  test.info().annotations.push({
    type: 'manifest',
    description:
      `${file}｜场景 ${String(manifest.totals.scenarios)}｜图 ${String(manifest.totals.shots)}｜` +
      `字节 ${String(manifest.totals.bytes)}｜批号 ${manifest.runId}`,
  });
});
