/**
 * @vitest-environment node
 *
 * 模块: tests/demo-coverage
 * 职责: 把「登记的场景 ↔ 声明文件 ↔ 真跑脚本」三者一一对应变成会失败的检查
 * 数据来源:
 *   - apps/web/demo/support/paths.ts: MUST — `SCENARIO_SLUGS`（已实现场景清单的单一真源）
 *   - apps/web/demo/scenarios/registry.ts: MUST — 声明装配入口
 * 边界:
 *   - 依赖: vitest、node:fs、demo/support/{paths,scenario}、demo/scenarios/registry
 *   - 被依赖: 无（`pnpm test` 收集）
 * 禁止行为:
 *   - 禁止把场景清单抄成本文件的字面量（那样新增场景时它照样绿，等于没有检查）
 *   - 禁止在「登记了但没脚本」时降级成 warning（缺口会留在安静的一侧）
 *
 * ## 为什么需要这个文件
 *
 * 演示装置的核对链只保证「声明过的步骤都有图」：`demo/manifest.spec.ts` 遍历的是
 * `registry.ts` 装配出来的声明。于是有两种缺口它天然看不见：
 *
 * ① 场景**登记进 `SCENARIO_SLUGS` 却忘了写 spec** ⇒ 该场景的声明根本不在 registry 里，
 *    一次运行下来少了一整个场景，而 manifest 仍然自洽地宣布「全部齐备」；
 * ② 删掉/改名某个场景时，`scenarios/` 里留下的 `*.schema.ts`/`*.spec.ts` 成了孤儿，
 *    不再被任何入口收集，磁盘上也不会留下可发现的痕迹。
 *
 * 两者都是「永远不会失败的检查」的典型形态。本文件把三处清单绑在一起：
 * `SCENARIO_SLUGS`（登记）⇄ `scenarios/*.schema.ts`（声明）⇄ `scenarios/*.spec.ts`（真跑）。
 */

import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { SCENARIOS } from '../demo/scenarios/registry';
import { validateScenario } from '../demo/support/scenario';
import { SCENARIO_SLUGS } from '../demo/support/paths';

/**
 * 去掉 TS 注释后的源码（块注释与行注释）。
 *
 * 只为一个判据服务：`captureStep(` 出现在注释里不算调用。用正则会误伤 `https://`，
 * 故行注释那一步要求 `//` 前面不是冒号。
 */
function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1');
}

/** `apps/web/demo/scenarios` 的绝对路径；用 `import.meta.url` 而不是 `__dirname`（ESM 下不存在）。 */
const SCENARIOS_DIR = fileURLToPath(new URL('../demo/scenarios/', import.meta.url));
const files = readdirSync(SCENARIOS_DIR);

describe('演示场景清单与声明、脚本一一对应', () => {
  it('已实现场景清单非空（提取到 0 个场景即失败）', () => {
    // 非空洞性：清单空了以后，下面每一条都会「遍历零个元素全绿」。
    expect(SCENARIO_SLUGS.length).toBeGreaterThan(0);
  });

  it('registry 装配的声明与 SCENARIO_SLUGS 同序且同集合', () => {
    expect(SCENARIOS.map((scenario) => scenario.slug)).toEqual([...SCENARIO_SLUGS]);
  });

  it('每个登记的场景都有 schema 与 spec 两个文件', () => {
    for (const slug of SCENARIO_SLUGS) {
      expect(files, `缺少 scenarios/${slug}.schema.ts`).toContain(`${slug}.schema.ts`);
      expect(files, `缺少 scenarios/${slug}.spec.ts`).toContain(`${slug}.spec.ts`);
    }
  });

  it('scenarios/ 里没有登记之外的孤儿文件', () => {
    const declared = new Set(SCENARIO_SLUGS.flatMap((slug) => [`${slug}.schema.ts`, `${slug}.spec.ts`]));
    // `registry.ts` 是装配入口，不是场景文件，按名排除。
    const orphans = files.filter((name) => name !== 'registry.ts' && !declared.has(name));
    expect(orphans, `未被 SCENARIO_SLUGS 登记的孤儿文件：${orphans.join(', ')}`).toEqual([]);
  });

  it('每个 spec 真的用声明截图（不是只 import 了声明）', () => {
    for (const slug of SCENARIO_SLUGS) {
      const source = readFileSync(resolve(SCENARIOS_DIR, `${slug}.spec.ts`), 'utf8');
      // 先剥掉注释再判：子串匹配会被「注释里写了 captureStep(」糊弄过去
      // （独立复查 FAIL-9：那样守卫就在检查一段说明文字，而不是检查代码）。
      const code = stripComments(source);
      expect(code, `${slug}.spec.ts 没有调用 captureStep`).toContain('captureStep(');
      expect(code, `${slug}.spec.ts 没有引用自己的声明模块`).toContain(`./${slug}.schema`);
    }
  });

  it('每个声明自洽（步骤 id 唯一、讲解词非空）', () => {
    const problems = SCENARIOS.flatMap((scenario) => validateScenario(scenario));
    expect(problems).toEqual([]);
  });
});
