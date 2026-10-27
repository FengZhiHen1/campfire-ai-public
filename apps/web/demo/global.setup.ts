/**
 * 模块: demo/global.setup
 * 职责: 开新批——校验声明、检查真实栈前提、把上一轮材料挪到可恢复处、清空落点、写本轮批号
 * 数据来源:
 *   - docs/运维/演示材料生成.md: MUST — 「每轮覆盖」语义、前提前置检查清单、失败可恢复
 *   - apps/web/e2e/global.setup.ts: MUST — 「按 `--project=` 精确判定本次是否截图入口」的做法
 * 边界:
 *   - 依赖: node:fs、node:crypto、node:path（Node 内置）、./support/*、./scenarios/registry
 *   - 被依赖: playwright.demo.config.ts（globalSetup）
 * 禁止行为:
 *   - 禁止在前提不满足时静默跳过（缺环境 = 失败：材料宣称的是「这条链路跑通过」）
 *   - 禁止**先清空再检查前提**：那样一次「模型没起」的失败会先把上一轮可用材料删掉
 *     （2026-10-27 独立复查 FAIL-1/FAIL-4 指出的正是这个顺序）
 *   - 禁止在「只复核清单」时清空落点：`--project=demo-manifest --no-deps` 必须能在不动材料的
 *     前提下重跑四条判据，否则复核动作本身就是销毁证据
 */

import { randomUUID } from 'node:crypto';
import { cp, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

import {
  BASE_URL,
  DEMO_OUT_DIR,
  MANIFEST_PATH,
  REPO_ROOT,
  RUN_ID_PATH,
  SIDECAR_DIR,
} from './support/paths';
import { SCENARIOS } from './scenarios/registry';
import { validateScenario } from './support/scenario';

/** 前提检查的上界：真实栈由使用者起，等太久没有意义。 */
const READY_TIMEOUT_MS = 10_000;

/**
 * 上一轮材料的暂存位置（`.tmp/` 之下）。
 *
 * 为什么需要：`demo/` 不入库，清空后只能靠**再跑一次**恢复，而一次完整走查要真模型额度与
 * 数分钟。清空前把可用材料留一份到 `.tmp/`，失败时至少能手工还原。
 * 放 `.tmp/` 而不是落点内部：落点里的图会被「产物 ⊆ 声明」判据当成孤儿图。
 */
const PREVIOUS_MATERIAL_BACKUP = resolve(REPO_ROOT, '.tmp', 'demo-previous');

/**
 * 「只复核清单」的入口参数。
 *
 * 判据是**排除法**而不是「含 `--project=demo`」：不加 `--project` 时 Playwright 跑全部 project，
 * 那也是一次截图入口，必须清空开新批。第一版写成「含 `--project=demo` 才清空」，于是
 * `pnpm demo`（不带 project 过滤，最常见的那种用法）走了「只复核」分支——沿用上一轮批号、
 * 不清理落点，新旧材料混在同一批里，而 `runId` 相同使混批判据也看不出来（2026-10-27 实测）。
 */
const VERIFY_ONLY_ARG = '--project=demo-manifest';

/** 校验场景声明自洽；不自洽就在截图之前失败。 */
function assertDeclarations(): void {
  const problems = SCENARIOS.flatMap((scenario) => validateScenario(scenario));
  if (problems.length > 0) {
    throw new Error(`场景声明不自洽（${String(problems.length)} 条）：\n- ${problems.join('\n- ')}`);
  }
}

/** 读健康端点；网络失败也转成「不 ready」，由调用方统一报错。 */
async function fetchReadyz(): Promise<{
  ready: boolean;
  components: Record<string, { status: string; detail?: string }>;
}> {
  try {
    const response = await fetch(`${BASE_URL}/readyz`, {
      signal: AbortSignal.timeout(READY_TIMEOUT_MS),
    });
    const body = (await response.json()) as {
      ready?: boolean;
      components?: Record<string, { status: string; detail?: string }>;
    };
    return { ready: body.ready === true, components: body.components ?? {} };
  } catch (error) {
    return { ready: false, components: { backend: { status: 'unreachable', detail: String(error) } } };
  }
}

/** 邀请码池（逗号分隔）；空池返回空数组，由调用方判失败。 */
export function invitePool(): string[] {
  return (process.env.DEMO_INVITE_CODES ?? process.env.DEMO_INVITE_CODE ?? '')
    .split(',')
    .map((code) => code.trim())
    .filter((code) => code !== '');
}

/** 真实栈前提：健康端点必须 ready（含 model 项）、邀请码池非空。 */
async function assertStackReady(): Promise<void> {
  const ready = await fetchReadyz();
  if (!ready.ready) {
    const detail = Object.entries(ready.components)
      .map(([name, item]) => `${name}=${item.status}${item.detail === undefined ? '' : `（${item.detail}）`}`)
      .join('\n- ');
    throw new Error(
      `真实栈前提不满足：GET ${BASE_URL}/readyz 未返回 ready:true。\n` +
        `各组件状态：\n- ${detail}\n` +
        '按 docs/运维/演示材料生成.md 第 3 节先把后端、Vite、Worker 起起来。',
    );
  }
  if (invitePool().length === 0) {
    throw new Error(
      '缺少邀请码：请先 `uv run python -m campfire.cli invite issue` 现签，再以 DEMO_INVITE_CODES 传入。\n' +
        '（每个场景各开一个新账号，一枚码只用一次；不复用上一轮的码——复用会得到 HTTP 200 + GENERAL_ERROR 的假绿）',
    );
  }
}

export default async function globalSetup(): Promise<void> {
  // ① 声明自洽：步骤 id 重复、空讲解词这类问题必须在截图之前暴露。
  assertDeclarations();

  const reset = !process.argv.some((argument) => argument === VERIFY_ONLY_ARG);

  if (!reset) {
    // 复核入口（`--project=demo-manifest --no-deps`）：**不动落点**，沿用已存在的批号，
    // 让四条判据可以单独重跑。
    const existing = await readFile(RUN_ID_PATH, 'utf8').catch(() => '');
    if (existing.trim() === '') {
      throw new Error(
        `落点里没有批号（${RUN_ID_PATH}）：说明这里还没有跑过截图。` +
          '先跑 `pnpm --filter @campfire/web demo` 生成一轮材料，再来复核清单。',
      );
    }
    return;
  }

  // ② 前提先查，再动材料：顺序反了会让「模型没起」的失败顺手删掉上一轮可用材料。
  await assertStackReady();

  // ③ 上一轮材料留一份到 `.tmp/`（可恢复），然后清空落点。
  const hasPrevious = (await readdir(DEMO_OUT_DIR).catch(() => [])).length > 0;
  if (hasPrevious) {
    await rm(PREVIOUS_MATERIAL_BACKUP, { recursive: true, force: true });
    await cp(DEMO_OUT_DIR, PREVIOUS_MATERIAL_BACKUP, { recursive: true });
  }
  const entries = await readdir(DEMO_OUT_DIR, { withFileTypes: true }).catch(() => []);
  for (const entry of entries) {
    await rm(resolve(DEMO_OUT_DIR, entry.name), { recursive: true, force: true });
  }
  await mkdir(SIDECAR_DIR, { recursive: true });
  await rm(MANIFEST_PATH, { force: true });

  // ④ 写本轮批号。
  const runId = `${new Date().toISOString()}-${randomUUID().slice(0, 8)}`;
  await writeFile(RUN_ID_PATH, runId, 'utf8');
}
