/**
 * 模块: e2e/manifest.spec
 * 职责: 汇总逐图 sidecar 成 manifest.json，并把「manifest 与磁盘一致」变成机器断言
 * 数据来源:
 *   - 原证物 orchestrator-20261002-001/T01.md: MUST — 目标 4 与验收标准
 *     「manifest 记录 sha256 与字节数，与文件实际值一致——审查者会抽查复算」
 *   - 原证物 orchestrator-20261002-001/T01-rulings.md: MUST — 裁决 1（清点变 40 张、
 *     kind 字段）与追加裁决（fullPage 图记 contentHeightPx / expandedScrollContainer）
 *     与裁决 2（fontLoaded 必为 true）
 * 边界:
 *   - 依赖: e2e/support/{manifest,paths}、@playwright/test
 *   - 被依赖: playwright.config.ts 的 manifest project（依赖两个截图 project）
 * 禁止行为:
 *   - 禁止在 sidecar 缺张时生成 manifest（张数不足即失败，不产出一份「看起来完整」的清单）
 *   - 禁止直接搬运 sidecar 里的哈希（必须回读磁盘复算，见 buildManifest 的说明）
 *
 * 2026-10-07（拆分 `shots` / `e2e` 两条入口）起，本文件**不再断言 `assertedContent` 非空**：
 * 内容断言已归 `content.spec.ts`，截图入口不再求值它们，该字段恒为空数组（保留字段是为了
 * 不因一次拆分改动 `formatVersion` 的形状）。「截图必须有料」这条不变量因此**转移**到
 * `pnpm e2e`——它靠命名 project 隔离（`content-*`），其失败不会再挡住截图。
 * 反过来说：**跑完 `pnpm shots` 不等于验收通过，必须再跑 `pnpm e2e`。**
 */

import { readFile, stat, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

import { expect, test } from '@playwright/test';

import { buildManifest, readSidecars, sha256Of, type ShotsManifest } from './support/manifest';
import {
  MANIFEST_PATH,
  PAGE_NAMES,
  SHOTS_OUT_DIR,
  SHOT_KINDS,
  SIDECAR_DIR,
  VIEWPORTS,
  VIEWPORT_NAMES,
  isShotKind,
  toRepoRelative,
} from './support/paths';
import { readRunId } from './support/runid';

/** 期望的张数：页 × 视口 × 图种（裁决 1 追加后为 10 × 2 × 2 = 40）。 */
const EXPECTED_SHOT_COUNT = PAGE_NAMES.length * VIEWPORT_NAMES.length * SHOT_KINDS.length;

test('汇总 sidecar 成 manifest 并复算', async () => {
  const sidecars = await readSidecars(SIDECAR_DIR);

  // 张数硬校验：sidecar 少一张就说明有图没截到（或 sidecar 目录被上一轮污染）。
  // 这里必须失败而不是「按现有的汇总」——一份缺页的 manifest 会被读成「这些页都验过了」。
  // 豁免 no-array-sort：排的是 map 返回的副本；`toSorted` 不在本项目的 TS lib 目标里。
  // oxlint-disable-next-line unicorn/no-array-sort
  const labels = sidecars.map((sidecar) => `${sidecar.page}-${sidecar.viewport}-${sidecar.kind}`).sort();
  expect(
    labels,
    `sidecar 张数应为 ${String(PAGE_NAMES.length)} 页 × ${String(VIEWPORT_NAMES.length)} 视口 × ${String(SHOT_KINDS.length)} 图种`,
  ).toHaveLength(EXPECTED_SHOT_COUNT);

  // 每个「页 × 视口 × 图种」组合恰好一张：缺张与重复都会被抓到，而不是靠总数碰巧相等。
  expect(new Set(labels).size, '存在重复的「页 × 视口 × 图种」组合').toBe(EXPECTED_SHOT_COUNT);

  // P2-3：所有 sidecar 必须同批。混批 = 某个落点里同时有两次运行的产物
  // （部分成功的一轮留下的），这时「清单里的 sha256」与它声称的那些 PNG 可能不再对应。
  // 这条断言存在的意义就是发现那种情况，而不是拼出一份看起来完整的清单。
  const runId = await readRunId();
  const foreign = sidecars.filter((sidecar) => sidecar.runId !== runId);
  expect(
    foreign.map((sidecar) => `${sidecar.file}(批号 ${sidecar.runId || '缺失'})`),
    `有 sidecar 不属于本轮（本轮批号 ${runId}）：落点里混了其它运行的产物，清单会与实际 PNG 不对应`,
  ).toHaveLength(0);

  const manifest = await buildManifest(sidecars, {
    outputDir: toRepoRelative(SHOTS_OUT_DIR),
    viewports: VIEWPORTS,
    runId,
  });

  await writeFile(MANIFEST_PATH, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');

  // 复算：重新读回刚落盘的 manifest，对每张图重算 sha256 与字节数。
  // 这一步与 buildManifest 内部的复算刻意重复——前者验「写盘时的值对不对」，
  // 后者验「落盘后的清单与文件仍然一致」（写盘本身可能失败或被截断）。
  const reread = JSON.parse(await readFile(MANIFEST_PATH, 'utf8')) as ShotsManifest;
  expect(reread.shots).toHaveLength(manifest.shots.length);
  expect(reread.formatVersion, '格式版本应为 2（每页每视口两张图 + 字体/中和取证字段）').toBe(2);

  for (const shot of reread.shots) {
    const fileName = shot.file.split('/').pop();
    expect(fileName, `${shot.file} 不是一个带文件名的路径`).toBeTruthy();
    const absolute = resolve(SHOTS_OUT_DIR, fileName ?? '');
    const exists = await stat(absolute).catch(() => null);
    expect(exists, `${shot.file} 不存在于落点目录`).not.toBeNull();
    const bytes = await readFile(absolute);
    expect(sha256Of(bytes), `${shot.file} 的 sha256 与 manifest 不一致`).toBe(shot.sha256);
    expect(bytes.byteLength, `${shot.file} 的字节数与 manifest 不一致`).toBe(shot.bytes);

    // 裁决 2：字体必须真的加载。用例里 `awaitDisplayFont` 会让未加载直接失败，
    // 这里再查一次是因为「manifest 记录了什么」也要自洽——审查者只看文件，
    // 不该出现「清单里写着 fontLoaded:false 而用例却绿了」这种矛盾记录。
    // 承重判据是 load() 命中数（check() 实测恒真、不承重，见 fonts.ts 的说明）。
    expect(shot.fontLoaded, `${shot.file} 记录 fontLoaded=false：截图用的是回退字形，证据不可用`).toBe(true);
    expect(shot.fontLoadedFaceCount, `${shot.file} 的 fonts.load() 命中数为 0：字体未加载`).toBeGreaterThan(0);
    expect(shot.fontLoadedFacesForFamily, `${shot.file} 的 Noto Serif SC loaded face 数为 0`).toBeGreaterThan(0);
    expect(
      shot.fontNegativeControlFaceCount,
      `${shot.file} 的负对照命中数不为 0：字体判据恒真，守卫无效`,
    ).toBe(0);
    expect(shot.fontStatus, `${shot.file} 的字体状态应为 loaded`).toBe('loaded');

    // 图种必须真的是两个已知值之一。manifest 是磁盘上的 JSON（可能被手改、
    // 被半截写入、或来自旧版本），因此这里不裸信它的 `kind`：先收窄类型再据它分支，
    // 未知值会以「不是 viewport/full」的形式立刻暴露，而不是悄悄走进 else 分支。
    expect(
      isShotKind(shot.kind),
      `${shot.file} 的图种 "${String(shot.kind)}" 不是 viewport/full 之一（manifest 可能来自旧版本或被改坏）`,
    ).toBe(true);

    // 追加裁决：fullPage 图必须记录它展开了什么、展开后多高；视口图则不该有这些值。
    if (shot.kind === 'full') {
      expect(shot.contentHeightPx, `${shot.file}（fullPage）缺少 contentHeightPx`).not.toBeNull();
      expect(shot.expandedScrollContainer, `${shot.file}（fullPage）缺少 expandedScrollContainer`).not.toBeNull();
    } else {
      expect(shot.kind, `${shot.file} 的图种不是 viewport/full`).toBe('viewport');
      expect(shot.contentHeightPx, `${shot.file}（视口图）不该有 contentHeightPx`).toBeNull();
    }
  }

  // 逐图种计数：40 = 20 视口图 + 20 fullPage 图。单看总数会漏掉「某种图种少了一张、
  // 另一种多了一张」这类错位。
  for (const kind of SHOT_KINDS) {
    const ofKind = reread.shots.filter((shot) => shot.kind === kind);
    expect(
      ofKind.length,
      `图种 ${kind} 应有 ${String(PAGE_NAMES.length * VIEWPORT_NAMES.length)} 张`,
    ).toBe(PAGE_NAMES.length * VIEWPORT_NAMES.length);
  }
});