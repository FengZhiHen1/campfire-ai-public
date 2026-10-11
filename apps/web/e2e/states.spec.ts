/**
 * 模块: e2e/states.spec
 * 职责: 把「关键状态图」从写在 DESIGN.md 里的承诺变成机器判据——声明 ⇔ 产物，且都是本轮产物
 * 数据来源:
 *   - docs/design/DESIGN.md: MUST — 「关键状态截图统一在 .tmp/screenshots/states」
 *   - docs/证据/orchestrator-20261002-001/T01-review-rulings.md: MUST — P2-3（混批必须可发现）
 *   - apps/web/e2e/support/paths.ts: MUST — `STATE_SHOTS` 是声明真源，本文件不另立一份名单
 *   - apps/web/e2e/manifest.spec.ts: MUST — 同一套做法（sidecar 汇总、回读磁盘复算哈希）
 * 边界:
 *   - 依赖: e2e/support/{manifest,paths,runid,state-shots}、node:fs/promises、@playwright/test
 *   - 被依赖: playwright.config.ts 的 `states-manifest` project（依赖两条内容断言 project）
 * 禁止行为:
 *   - 禁止在本文件里重抄状态名单（漏一个名字就等于把那条状态的缺口藏起来）
 *   - 禁止在缺张时按「目录里现有的图」汇总清单（那会把「少截了一张」变成一份看起来齐全的清单）
 *   - 禁止只用「文件在场」当判据：上一轮遗留的图同样在场，必须逐条核对 sidecar 里的批号
 *
 * 判据分四步，每步都能单独变红：
 *   1. **声明 ⊆ 产物**：每个状态 × 两个视口都要有 sidecar（缺张点名）；
 *   2. **产物 ⊆ 声明**：sidecar 里不得出现未声明的状态（改名后留下的旧 sidecar 会在这里暴露）；
 *   3. **同批**：每条 sidecar 的批号必须等于本轮批号（P2-3 的形态：落点里混了两次运行）；
 *   4. **与磁盘一致**：逐张回读 PNG 复算 sha256 与字节数，并校验像素宽 = 视口宽 × 倍率。
 *
 * 第 3、4 步与 `manifest.spec.ts` 同源；第 1、2 步是矩阵清单不需要、而「按需截图」必须的
 * ——状态图没有固定的页 × 视口矩阵可以反推张数。
 *
 * 注意：本判据问的是「这批图是不是**本次运行**产出的」，因此它只在整个 `pnpm e2e` 一次跑完时
 * 才有意义。单独跑 `--project=states-manifest --no-deps` 会因本轮批号刚被重写而与上一轮的
 * sidecar 不符——那是**如实失败**（这批图确实不是本轮的），不是假红。
 */

import { readFile, writeFile } from 'node:fs/promises';

import { expect, test } from '@playwright/test';

import { sha256Of } from './support/manifest';
import {
  DEVICE_SCALE_FACTOR,
  STATE_MANIFEST_PATH,
  STATE_SHOTS,
  STATE_SHOTS_DIR,
  VIEWPORTS,
  VIEWPORT_NAMES,
  stateShotFileName,
  toRepoRelative,
  type StateShotName,
  type ViewportName,
} from './support/paths';
import { readRunId } from './support/runid';
import { readStateSidecars } from './support/state-shots';

/** 一份声明的「状态 × 视口」组合的稳定标识。 */
function label(state: StateShotName, viewport: ViewportName): string {
  return stateShotFileName(state, viewport);
}

test('关键状态图齐张、同批、与磁盘一致，并写出可复算的清单', async () => {
  const runId = await readRunId();
  const sidecars = await readStateSidecars();

  // 1) 声明 ⊆ 产物。
  const declared = STATE_SHOTS.flatMap((state) => VIEWPORT_NAMES.map((viewport) => label(state, viewport)));
  const present = sidecars.map((sidecar) => label(sidecar.state, sidecar.viewport));
  const missing = declared.filter((name) => !present.includes(name));
  expect(missing, `关键状态图缺张（本轮批号 ${runId}）：这些交互用例没有写出 sidecar 与图`).toHaveLength(0);

  // 2) 产物 ⊆ 声明。落到这里说明有人改了状态名却没清旧 sidecar——那正是「清单看起来齐了」的来源。
  const undeclared = present.filter((name) => !declared.includes(name));
  expect(undeclared, '存在未声明的状态图 sidecar：状态名改过而旧 sidecar 未清').toHaveLength(0);
  expect(new Set(present).size, '存在重复的「状态 × 视口」组合').toBe(present.length);

  // 3) 同批（P2-3）。批号来自本轮 globalSetup 写入的批号文件。
  const foreign = sidecars.filter((sidecar) => sidecar.runId !== runId);
  expect(
    foreign.map((sidecar) => `${sidecar.file}(批号 ${sidecar.runId || '缺失'})`),
    `有状态图不属于本轮（本轮批号 ${runId}）：落点里混了其它运行的产物`,
  ).toHaveLength(0);

  // 4) 与磁盘一致：逐张回读复算，并校验像素宽与视口相符。
  const files: { file: string; bytes: number; sha256: string; width: number; height: number }[] = [];
  for (const sidecar of sidecars) {
    const bytes = await readFile(sidecar.absolutePath);
    expect(sha256Of(bytes), `${sidecar.file} 的 sha256 与 sidecar 不一致（写盘后被改过或写坏了）`).toBe(sidecar.sha256);
    expect(bytes.byteLength, `${sidecar.file} 的字节数与 sidecar 不一致`).toBe(sidecar.bytes);
    expect(bytes.byteLength, `${sidecar.file} 是空文件`).toBeGreaterThan(0);
    expect(
      sidecar.width,
      `${sidecar.file} 的像素宽应为「视口宽 × 倍率」= ${String(VIEWPORTS[sidecar.viewport].width * DEVICE_SCALE_FACTOR)}`,
    ).toBe(VIEWPORTS[sidecar.viewport].width * DEVICE_SCALE_FACTOR);
    files.push({
      file: toRepoRelative(sidecar.absolutePath),
      bytes: bytes.byteLength,
      sha256: sha256Of(bytes),
      width: sidecar.width,
      height: sidecar.height,
    });
  }

  // 5) 写清单并回读复算：清单里的值必须能从磁盘上的文件重新算出来，否则它不是证据。
  await writeFile(
    STATE_MANIFEST_PATH,
    `${JSON.stringify(
      {
        formatVersion: 1,
        runId,
        outputDir: toRepoRelative(STATE_SHOTS_DIR),
        deviceScaleFactor: DEVICE_SCALE_FACTOR,
        states: STATE_SHOTS,
        viewports: VIEWPORT_NAMES,
        files,
      },
      null,
      2,
    )}\n`,
    'utf8',
  );
  const reread = JSON.parse(await readFile(STATE_MANIFEST_PATH, 'utf8')) as { files: { file: string; sha256: string }[] };
  expect(reread.files).toHaveLength(declared.length);
  for (const entry of reread.files) {
    const sidecar = sidecars.find((candidate) => toRepoRelative(candidate.absolutePath) === entry.file);
    expect(sidecar, `${entry.file} 在清单里但不在 sidecar 里`).toBeDefined();
    if (sidecar === undefined) continue;
    expect(sha256Of(await readFile(sidecar.absolutePath)), `${entry.file} 的 sha256 与清单不一致`).toBe(entry.sha256);
  }
});
