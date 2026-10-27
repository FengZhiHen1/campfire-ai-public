/**
 * 模块: demo/support/scenario
 * 职责: 场景声明的形状与校验——「声明」与「产物」必须一一对应，缺一即失败
 * 数据来源:
 *   - docs/运维/演示材料生成.md: MUST — 每个场景由「步骤声明（有序）」+「截图产物」两半组成，
 *     步骤的 `caption` 是给对外展示直接引用的讲解词
 * 边界:
 *   - 依赖: 无（纯类型与纯函数）
 *   - 被依赖: scenarios/*.schema.ts、scenarios/*.spec.ts、scenarios/registry.ts、support/manifest.ts
 * 禁止行为:
 *   - 禁止允许「只截图不声明」（那样的图没有讲解词、也没人核对它该不该在）
 *   - 禁止允许「只声明不截图」（那样清单会宣布一批不存在的材料）
 */

import type { ScenarioSlug } from './paths';

/** 一个演示步骤：`id` 进文件名，`caption` 是展示时直接念的那句话。 */
export interface DemoStep {
  /** 步骤短名（kebab-case，进文件名，同场景内唯一）。 */
  id: string;
  /** 讲解词：这一步在演示里要说明什么（中文，一句话）。 */
  caption: string;
}

/** 一个场景的声明。 */
export interface DemoScenario {
  slug: ScenarioSlug;
  /** 场景标题（对外展示时的分节名）。 */
  title: string;
  /** 这条演示想证明的链路（一句话，供报告与讲解使用）。 */
  claim: string;
  /** 步骤，顺序即文件名序号。 */
  steps: readonly DemoStep[];
}

/**
 * 校验场景声明自洽，返回按发现顺序排列的错误（空数组即通过）。
 *
 * 前置: 无
 * 后置: 不修改入参
 * 为什么要有：`id` 重复会让两张图同名互撞（后一张静默覆盖前一张），而序号是
 * 「顺序即演示顺序」的唯一载体——重复了就没有可靠顺序。
 */
export function validateScenario(scenario: DemoScenario): string[] {
  const problems: string[] = [];
  if (scenario.slug.trim() === '') problems.push('slug 为空');
  if (scenario.title.trim() === '') problems.push(`${scenario.slug}: title 为空`);
  if (scenario.claim.trim() === '') problems.push(`${scenario.slug}: claim 为空`);
  if (scenario.steps.length === 0) problems.push(`${scenario.slug}: 没有任何步骤（空场景不算材料）`);

  const seen = new Set<string>();
  for (const [index, step] of scenario.steps.entries()) {
    if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(step.id)) {
      problems.push(`${scenario.slug}[${String(index)}]: step id「${step.id}」不是 kebab-case`);
    }
    if (seen.has(step.id)) problems.push(`${scenario.slug}: step id「${step.id}」重复`);
    seen.add(step.id);
    if (step.caption.trim() === '') problems.push(`${scenario.slug}[${step.id}]: caption 为空`);
  }
  return problems;
}
