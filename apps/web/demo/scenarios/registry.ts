/**
 * 模块: demo/scenarios/registry
 * 职责: 已实现场景的声明清单——manifest 与前提校验的唯一入口
 * 数据来源:
 *   - docs/运维/演示材料生成.md: MUST — 场景清单与「声明即材料」的口径
 * 边界:
 *   - 依赖: ./*.schema（每个已实现场景一份声明）
 *   - 被依赖: demo/global.setup.ts、demo/manifest.spec.ts、apps/web/tests/demo-coverage.test.ts
 * 禁止行为:
 *   - 禁止在此处写场景步骤：步骤与讲解词属于 `*.schema.ts`，这里只做装配
 *   - 禁止追加未实现场景（manifest 会把缺失的图判成失败，而不是「还没做」）
 */

import type { DemoScenario } from '../support/scenario';
import { CONSULT_CITATION } from './consult-citation.schema';
import { EMERGENCY } from './emergency.schema';
import { LIBRARY } from './library.schema';
import { MEMORY } from './memory.schema';
import { ONBOARDING } from './onboarding.schema';
import { PROFILE } from './profile.schema';

/** 已实现场景（顺序即 manifest 与磁盘目录顺序，且必须与 `SCENARIO_SLUGS` 同序）。 */
export const SCENARIOS: readonly DemoScenario[] = [
  ONBOARDING,
  CONSULT_CITATION,
  EMERGENCY,
  LIBRARY,
  PROFILE,
  MEMORY,
];
