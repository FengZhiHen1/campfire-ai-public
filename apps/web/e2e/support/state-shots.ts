/**
 * 模块: e2e/support/state-shots
 * 职责: 关键状态图的逐图 sidecar 形状与读写（`states.spec.ts` 据此核对与汇总）
 * 数据来源:
 *   - docs/design/DESIGN.md: MUST — 「关键状态截图统一在 .tmp/screenshots/states」
 *   - 原证物 orchestrator-20261002-001/T01-review-rulings.md: MUST — P2-3
 *     「部分成功运行会留下旧产物……要能发现混批」
 *   - apps/web/e2e/support/manifest.ts: MUST — 同一套做法（落盘即复算、批号随 sidecar 走）
 * 边界:
 *   - 依赖: node:fs/promises（Node 内置）、e2e/support/paths
 *   - 被依赖: e2e/ui-interactions.spec.ts（写入者）、e2e/states.spec.ts（核对者）
 * 禁止行为:
 *   - 禁止用文件时间戳代替显式批号判「是不是本轮」（`support/runid.ts` 的禁令：时间戳回答
 *     不了「这两张图是不是同一轮」）
 *   - 禁止把「读不到 sidecar」当成零张放过（读不到即失败，由调用方判空并失败）
 *
 * 为什么不复用 `ShotSidecar`：那张 sidecar 承载「页 × 视口 × 图种」矩阵的字体取证、中和
 * 取证与滚动指标（二十余个必填字段），而状态图没有页夹具、也不做字体判据。硬套会逼出
 * 一批恒为空的字段，而「填了但没人看」的字段会让清单看起来比实际更可信。
 */

import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';

import { STATE_SIDECAR_DIR, stateSidecarPath, type StateShotName, type ViewportName } from './paths';

/** 一张状态图的 sidecar（由交互用例写、由 `states.spec.ts` 核对并汇总）。 */
export interface StateShotSidecar {
  state: StateShotName;
  viewport: ViewportName;
  /** PNG 相对仓库根的 POSIX 路径（进清单）。 */
  file: string;
  /** PNG 绝对路径（供核对时回读复算；不进清单，理由同 ShotSidecar）。 */
  absolutePath: string;
  /** 本张图所属批号；核对时与本轮批号逐条比对，不一致即混批。 */
  runId: string;
  sha256: string;
  bytes: number;
  width: number;
  height: number;
  /** 是否整页图（交互用例在展开后截的那种）。 */
  fullPage: boolean;
  /** 展开后测得的内容高（CSS px）；视口图为 null。 */
  contentHeightPx: number | null;
}

/**
 * 写一条 sidecar。
 *
 * 目录不存在时在这里建：截图用例已经在 `states/` 上建过一次目录，但 sidecar 落在
 * `.run/states/`（另一个目录，理由见 `paths.ts`）。两处各自保证自己的父目录存在，
 * 比要求调用方记得建两次更不容易漏。
 */
export async function writeStateSidecar(sidecar: StateShotSidecar): Promise<void> {
  await mkdir(STATE_SIDECAR_DIR, { recursive: true });
  await writeFile(stateSidecarPath(sidecar.state, sidecar.viewport), `${JSON.stringify(sidecar, null, 2)}\n`, 'utf8');
}

/** 读回全部 sidecar；目录不存在返回空数组（由调用方判空并失败）。 */
export async function readStateSidecars(): Promise<StateShotSidecar[]> {
  const names = await readdir(STATE_SIDECAR_DIR).catch(() => [] as string[]);
  // 豁免 no-array-sort 的理由同 manifest.ts：排的是 filter 返回的副本；`toSorted` 不在 lib 目标里。
  // oxlint-disable-next-line unicorn/no-array-sort
  const ordered = names.filter((entry) => entry.endsWith('.json')).sort();
  const sidecars: StateShotSidecar[] = [];
  for (const name of ordered) {
    sidecars.push(JSON.parse(await readFile(`${STATE_SIDECAR_DIR}/${name}`, 'utf8')) as StateShotSidecar);
  }
  return sidecars;
}
