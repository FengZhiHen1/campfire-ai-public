/**
 * 模块: demo/support/shots
 * 职责: 截一张演示图并立刻写它的 sidecar——声明、产物、批号三者在同一处对齐
 * 数据来源:
 *   - docs/运维/演示材料生成.md: MUST — 每步一张图 + 一条 sidecar；sidecar 记本批批号
 *   - apps/web/e2e/support/{runid,manifest}.ts: 同构做法（PNG + sidecar + 汇总复算）
 * 边界:
 *   - 依赖: node:fs、node:crypto、node:path（Node 内置）、@playwright/test、./paths、./scenario
 *   - 被依赖: scenarios/*.spec.ts
 * 禁止行为:
 *   - 禁止在截图时记录未经实读的哈希（值一律来自本次对磁盘文件的实读）
 *   - 禁止吞掉「批号缺失」：缺批号说明没走 global.setup，混批检测会失效
 */

import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';

import type { Page } from '@playwright/test';

import { RUN_ID_PATH, sidecarPath, shotFilePath, toRepoRelative, type ScenarioSlug } from './paths';
import type { DemoScenario } from './scenario';

/** 一张图的 sidecar 形状。 */
export interface DemoShotSidecar {
  /** 场景短名。 */
  slug: ScenarioSlug;
  /** 本张图在声明里的序号（0 起）。 */
  index: number;
  /** 步骤短名。 */
  stepId: string;
  /** 讲解词（原样来自声明，供 manifest 与展示引用）。 */
  caption: string;
  /** 相对仓库根的 POSIX 路径（进 manifest）。 */
  file: string;
  /** 本张图所属批号。 */
  runId: string;
  /** 截图时刻（ISO 8601）。 */
  capturedAt: string;
  /** 实读得到的 sha256。 */
  sha256: string;
  /** 实读得到的字节数。 */
  bytes: number;
  /** 实读得到的像素宽高。 */
  width: number;
  /** 实读得到的像素高。 */
  height: number;
}

/** 读 PNG 的 IHDR 宽高（PNG 布局：0..7 签名，16..19 宽，20..23 高，大端）。 */
export function readPngSize(bytes: Buffer): { width: number; height: number } {
  if (bytes.length < 24 || bytes.readUInt32BE(0) !== 0x89504e47) {
    throw new Error('不是 PNG（签名不符）：拒绝猜测尺寸');
  }
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

/** 读本轮批号；缺失即抛（不降级成默认值，否则混批会静默通过）。 */
export async function readRunId(): Promise<string> {
  const text = await readFile(RUN_ID_PATH, 'utf8').catch(() => null);
  if (text === null || text.trim() === '') {
    throw new Error(`批号文件不存在或为空（${RUN_ID_PATH}）：globalSetup 未运行，无法判定产物是否同批`);
  }
  return text.trim();
}

/**
 * 按声明截一张图并写 sidecar。
 *
 * 前置: 调用方已把页面带到该步骤要展示的状态（本函数只负责「拍下来并记账」）
 * 后置: `<落点>/<slug>/<NN>-<id>.png` 与 `<落点>/.run/<slug>/<NN>-<id>.png.json` 已落盘
 * 异常: 写盘失败、PNG 读不出尺寸、批号缺失——一律向上抛（不吞）
 */
export async function captureStep(page: Page, scenario: DemoScenario, index: number): Promise<DemoShotSidecar> {
  const step = scenario.steps[index];
  if (step === undefined) {
    throw new Error(`${scenario.slug}: 声明里没有第 ${String(index + 1)} 步，不能截一张没有讲解词的图`);
  }
  const target = shotFilePath(scenario.slug, index, step.id);
  await mkdir(dirname(target), { recursive: true });
  // `animations:'disabled'`：动画中途截会得到半透明/位移中间态，与「演示材料」用途冲突。
  await page.screenshot({ path: target, animations: 'disabled' });

  const bytes = await readFile(target);
  const size = readPngSize(bytes);
  const sidecar: DemoShotSidecar = {
    slug: scenario.slug,
    index,
    stepId: step.id,
    caption: step.caption,
    file: toRepoRelative(target),
    runId: await readRunId(),
    capturedAt: new Date().toISOString(),
    sha256: createHash('sha256').update(bytes).digest('hex'),
    bytes: bytes.length,
    width: size.width,
    height: size.height,
  };
  const meta = sidecarPath(scenario.slug, index, step.id);
  await mkdir(dirname(meta), { recursive: true });
  await writeFile(meta, `${JSON.stringify(sidecar, null, 2)}\n`, 'utf8');
  return sidecar;
}
