/**
 * 模块: demo/support/manifest
 * 职责: 汇总本轮演示材料并做四步核对——声明、产物、批号、磁盘实读必须互相对得上
 * 数据来源:
 *   - docs/运维/演示材料生成.md: MUST — 四步判据（声明⊆产物、产物⊆声明、同批、哈希复算）
 *   - apps/web/e2e/states.spec.ts: 同型做法（「声明 ⇔ 产物 ⇔ 同批 ⇔ 与磁盘一致」）
 * 边界:
 *   - 依赖: node:fs、node:crypto（Node 内置）、./paths、./scenario、./shots
 *   - 被依赖: demo/manifest.spec.ts
 * 禁止行为:
 *   - 禁止把「读不到 sidecar」当成「这张图不存在」以外的解释（读不到就是失败）
 *   - 禁止只核对声明的图而漏掉多出来的图：孤儿图无人点名就等于没有清理语义
 */

import { createHash } from 'node:crypto';
import { readFile, readdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

import {
  BASE_URL,
  DEMO_OUT_DIR,
  DEVICE_SCALE_FACTOR,
  MANIFEST_PATH,
  VIEWPORT,
  sidecarPath,
  toRepoRelative,
} from './paths';
import type { DemoScenario } from './scenario';
import { readPngSize, readRunId, type DemoShotSidecar } from './shots';

/** manifest 里的一步。 */
export interface DemoManifestStep {
  index: number;
  stepId: string;
  caption: string;
  file: string;
  sha256: string;
  bytes: number;
  width: number;
  height: number;
}

/** manifest 里的一个场景。 */
export interface DemoManifestScenario {
  slug: string;
  title: string;
  claim: string;
  steps: DemoManifestStep[];
}

/** 整份 manifest。 */
export interface DemoManifest {
  formatVersion: 1;
  runId: string;
  generatedAt: string;
  /** 落点（相对仓库根）；换机器后据此定位。 */
  outputDir: string;
  /** 被测站点根：材料来自哪个站点必须可回溯（`DEMO_BASE_URL` 可以把装置指到别处）。 */
  origin: string;
  viewport: { width: number; height: number; deviceScaleFactor: number };
  scenarios: DemoManifestScenario[];
  totals: { scenarios: number; shots: number; bytes: number };
}

/** 递归列出落点下所有 PNG（绝对路径）。`.playwright/` 是 Playwright 自己的产物区，不算材料。 */
async function listPngs(dir: string): Promise<string[]> {
  const entries = await readdir(dir, { withFileTypes: true }).catch(() => []);
  const found: string[] = [];
  for (const entry of entries) {
    if (entry.name === '.playwright') continue;
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) found.push(...(await listPngs(full)));
    else if (entry.name.endsWith('.png')) found.push(full);
  }
  return found;
}

/** 读一张 sidecar；读不到或形状不对都算失败项，由调用方汇总。 */
async function readSidecar(path: string): Promise<DemoShotSidecar | null> {
  const raw = await readFile(path, 'utf8').catch(() => null);
  if (raw === null) return null;
  try {
    return JSON.parse(raw) as DemoShotSidecar;
  } catch {
    return null;
  }
}

/**
 * 汇总并核对，返回 `{ manifest, problems }`。
 *
 * 前置: 已跑完全部场景 project（`demo-manifest` 用 `dependencies` 保证顺序）
 * 后置: 不写盘（写盘由调用方决定，失败时不落 manifest——「清单存在」等价于「本轮核对通过」）
 * 判据（任一不满足即 problems 非空）:
 *   1. 声明 ⊆ 产物：每一步都有对应 PNG 与 sidecar
 *   2. 产物 ⊆ 声明：落点里没有声明之外的多余 PNG（防孤儿图）
 *   3. 同批：每条 sidecar 的 runId 与本轮一致
 *   4. 与磁盘一致：sha256 / 字节 / 像素均以本次实读为准复算
 */
export async function buildDemoManifest(
  scenarios: readonly DemoScenario[],
): Promise<{ manifest: DemoManifest; problems: string[] }> {
  const problems: string[] = [];
  const runId = await readRunId();
  const declared = new Set<string>();
  const manifestScenarios: DemoManifestScenario[] = [];

  for (const scenario of scenarios) {
    const steps: DemoManifestStep[] = [];
    for (const [index, step] of scenario.steps.entries()) {
      const target = resolve(DEMO_OUT_DIR, scenario.slug, `${String(index + 1).padStart(2, '0')}-${step.id}.png`);
      const file = toRepoRelative(target);
      declared.add(file);

      const bytes = await readFile(target).catch(() => null);
      if (bytes === null) {
        // 判据 1 的反面：声明了却没图纸。
        problems.push(`${scenario.slug}[${step.id}]: 声明了这一张，但磁盘上没有 ${file}`);
        continue;
      }
      const sidecar = await readSidecar(sidecarPath(scenario.slug, index, step.id));
      if (sidecar === null) {
        problems.push(`${scenario.slug}[${step.id}]: sidecar 缺失或不可解析（无法证明它是本轮产物）`);
      } else {
        if (sidecar.runId !== runId) {
          problems.push(
            `${scenario.slug}[${step.id}]: sidecar 批号 ${sidecar.runId} 与本轮 ${runId} 不一致（混批）`,
          );
        }
        if (sidecar.stepId !== step.id) {
          problems.push(`${scenario.slug}[${step.id}]: sidecar 记的步骤是 ${sidecar.stepId}，与声明不符`);
        }
      }

      const size = readPngSize(bytes);
      const sha256 = createHash('sha256').update(bytes).digest('hex');
      if (sidecar !== null && sidecar.sha256 !== sha256) {
        problems.push(
          `${scenario.slug}[${step.id}]: 磁盘 sha256 与 sidecar 记录不一致（图被换过或手改过）`,
        );
      }
      if (size.width !== VIEWPORT.width * DEVICE_SCALE_FACTOR) {
        problems.push(
          `${scenario.slug}[${step.id}]: 宽 ${String(size.width)} ≠ 视口 ${String(VIEWPORT.width)}×${String(DEVICE_SCALE_FACTOR)}`,
        );
      }
      if (size.height < VIEWPORT.height * DEVICE_SCALE_FACTOR) {
        problems.push(
          `${scenario.slug}[${step.id}]: 高 ${String(size.height)} 小于视口高×倍率 ${String(VIEWPORT.height * DEVICE_SCALE_FACTOR)}`,
        );
      }

      steps.push({
        index,
        stepId: step.id,
        caption: step.caption,
        file,
        sha256,
        bytes: bytes.length,
        width: size.width,
        height: size.height,
      });
    }
    manifestScenarios.push({ slug: scenario.slug, title: scenario.title, claim: scenario.claim, steps });
  }

  // 判据 2：落点里不许有声明之外的 PNG（孤儿图）。
  for (const png of await listPngs(DEMO_OUT_DIR)) {
    const repoRel = toRepoRelative(png);
    if (!declared.has(repoRel)) {
      problems.push(`落点里有声明之外的多余图：${repoRel}（删场景或改名后留下的孤儿图）`);
    }
  }

  // 帧唯一性：同一场景里两张图哈希相同 ⇒ 讲解词声称的「另一个画面」其实没拍到
  // （2026-10-27 独立复查实测：第 7、8 步曾同哈希，因为没滚动就把同一屏拍了两次）。
  for (const scenario of manifestScenarios) {
    const seen = new Map<string, string>();
    for (const step of scenario.steps) {
      const first = seen.get(step.sha256);
      if (first !== undefined) {
        problems.push(
          `${scenario.slug}: 「${first}」与「${step.stepId}」两张图逐字节相同——第二张不是新画面`,
        );
      } else {
        seen.set(step.sha256, step.stepId);
      }
    }
  }

  const shots = manifestScenarios.reduce((sum, s) => sum + s.steps.length, 0);
  const manifest: DemoManifest = {
    formatVersion: 1,
    runId,
    generatedAt: new Date().toISOString(),
    outputDir: toRepoRelative(DEMO_OUT_DIR),
    origin: BASE_URL,
    viewport: { ...VIEWPORT, deviceScaleFactor: DEVICE_SCALE_FACTOR },
    scenarios: manifestScenarios,
    totals: { scenarios: manifestScenarios.length, shots, bytes: manifestScenarios.reduce((sum, s) => sum + s.steps.reduce((n, x) => n + x.bytes, 0), 0) },
  };
  return { manifest, problems };
}

/** 写 manifest（只在核对通过时由调用方调用）。 */
export async function writeDemoManifest(manifest: DemoManifest): Promise<string> {
  await writeFile(MANIFEST_PATH, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  return toRepoRelative(MANIFEST_PATH);
}
