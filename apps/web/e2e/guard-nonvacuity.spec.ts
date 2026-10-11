/**
 * 模块: e2e/guard-nonvacuity.spec
 * 职责: 证明 fullPage 高度守卫不是恒真的检查——在目标外壳结构下，用生产同一个取量函数与
 *       判据函数，跑出「不展开则抛错」与「展开则通过」两种结果
 * 数据来源:
 *   - docs/证据/orchestrator-20261002-001/T01-rulings.md: MUST — 追加裁决第 2 条
 *     「守卫的作用不是通过，而是在外壳落地后第一时间变红……请确保它真的会红」
 *   - docs/证据/orchestrator-20261002-001/T01-review-rulings.md: MUST — P1-1 的修法
 *     （判据改用隐藏溢出；本文件必须喂与生产调用点相同的量，且必须覆盖 stage padding = 24 与 0）
 *   - docs/证据/orchestrator-20261002-001/facts.md §3: MUST — 目标外壳结构的几何（含 padding）
 * 边界:
 *   - 依赖: e2e/support/*、@playwright/test
 *   - 被依赖: 无（由 `pnpm --filter @campfire/web shots` 一并驱动）
 * 禁止行为:
 *   - 禁止自己另算一个溢出量（必须调用生产的 measureOverflow）——本轮 P1-1 的根因正是
 *     「生产喂文档级、证明喂内层级」，两者不是同一个量，于是证明无效
 *   - 禁止只测一种外壳形态（padding 恰好是把守卫从「被整段跳过」变成「运行但通过」的变量）
 *   - 禁止改产品代码来做这个模拟（全部在浏览器侧用 DOM 操作完成）
 *
 * 为什么需要本文件
 *
 * 高度守卫的失败模式在当前实现下不会发生：现在由文档滚动，fullPage 天然拿到整页。
 * 它的价值全在设备外壳（T02）落地之后，因此必须在浏览器侧模拟那个结构才能证明它会红。
 *
 * T02 落地后前提已变（2026-10-02）
 *
 * T02（设备外壳）已于 2026-10-02 落地，本用例原来的「应用无外壳」前提已不成立，
 * 故改为：**注入模拟外壳之前，先用产品自己在窄视口使用的退化方式（`display: contents`）
 * 中和真实外壳的三层**，把 `#root` 恢复成「无外壳」形态，再跑原来的两种 padding 形态。
 *
 * 为什么选这个做法（而不是「直接针对真实 `.device-screen`」）
 *
 * 我在两视口都实测了真实外壳（探针输出 `docs/证据/orchestrator-20261002-001/T01-assets/probe-shell-desktop.txt`）：
 *   - desktop：真实外壳确实形成陷阱（`.device-screen` `overflow-y:auto`，profile 裁 1184px、
 *     memory 裁 82px，陷阱图高 2000px），所以「直接针对真实 `.device-screen`」在 desktop 可行；
 *   - mobile：三层都是 `display: contents`、`clientHeight/scrollHeight` 均为 0，
 *     由文档滚动、不产生任何裁切（profile 的陷阱图高 4056px = 内容全高、`clipped=[]`）。
 *     即在 mobile 上真实外壳不构成陷阱，选那条路会让 mobile 侧无东西可证。
 * 本用例必须同时在两个 project 上产出证据（放行判据），因此选与视口无关的做法：
 * 中和真实外壳后注入模拟外壳。它还原了本文档开头那套「应用无外壳」前提，
 * 于是 padding 0/24 这个变量仍然可测，且不需按视口分支。
 *
 * 为什么不是「删掉真实外壳的 DOM 节点」：那会改变 `#root` 的子树结构，
 * 使被测形态与产品实际渲染的形态脱钩；而 `display: contents` 正是产品自己在窄视口用的同一种手段
 * （`global.css` 里三层默认即为 `display: contents`），用它中和等于复用产品行为，不引入新语义。
 *
 * 已知边界（不掩饰）
 *
 * 本文件是模拟外壳，不是 T02 的真实 DOM。它证明的是「在我构造的这两种形态下守卫会红」；
 * 更强的「任何外壳形态下都会红」未证。真实外壳在 desktop 上的陷阱形态由
 * `shots.spec.ts` 的生产路径覆盖（那里没有模拟外壳）。
 * 若 T02 的真实结构把溢出拆成外层与内层两段独立滚动，
 * measureOverflow 取 max 的语义会低估——那时本用例不会红，而真实守卫也仍可能漏。
 * 该边界同时写在 OverflowMeasurement.hiddenOverflowPx 的注释里。
 */

import { mkdir, readFile, writeFile } from 'node:fs/promises';

import { expect, test } from '@playwright/test';

import { PAGE_SHOTS } from './support/fixtures';
import { awaitDisplayFont } from './support/fonts';
import { readPngSize } from './support/manifest';
import {
  assertFullPageExpanded,
  assertNoClippedContent,
  expandForFullPage,
  findClippedElements,
  measureOverflow,
} from './support/neutralise';
import { installNetwork } from './support/network';
import { DEVICE_SCALE_FACTOR, SIDECAR_DIR, VIEWPORTS, isViewportName } from './support/paths';
import { expectSessionInjected, installSession } from './support/session';

/** 目标外壳的 stage padding（facts.md §3 的目标结构）。 */
const SHELL_STAGE_PADDING_PX = 24;

/** 证明产物的落点（在 sidecar 目录下，随 `.tmp/` 被 gitignore）。 */
const EVIDENCE_DIR = `${SIDECAR_DIR}/guard-nonvacuity`;

/**
 * 中和 T02 真实外壳，把 `#root` 还原成「无外壳」形态。
 *
 * 做法：给三层加 `display: contents`——这是产品自己在窄视口用的同一种手段
 * （`global.css` 里 `.device-stage`/`.device`/`.device-screen` 默认即为 `display: contents`），
 * 因此不是新语义，只是把宽视口的那套反向施加回去。
 *
 * 为什么必须做（本轮 P1-1''）：T02 落地后真实外壳已在 DOM，本用例再注入模拟外壳就成了第二层，
 * 于是页面上有两个独立滚动容器、且面积完全相同（390×844）。生产展开逻辑当时只放开
 * 「面积最大」的那一个，平局时按文档序取前者（外层模拟容器），真实的 `.device-screen`
 * 不是它的后代、不在被展开的祖先链上，于是仍裁 1184px ⇒ 主判据红。
 * 中和真实外壳后，本用例恢复它设计时的前提（应用无外壳），模拟外壳就是唯一的外壳。
 *
 * 注意：这一层中和只在本用例内注入（用内联样式），用完由 `page.goto` 的重新加载清掉，
 * 不触碰任何产品文件。
 */
function neutraliseRealShellScript(): string {
  return `(() => {
  const selectors = ['.device-stage', '.device', '.device-screen'];
  const neutralised = [];
  for (const selector of selectors) {
    for (const element of Array.from(document.querySelectorAll(selector))) {
      if (element instanceof HTMLElement) {
        element.style.display = 'contents';
        neutralised.push(selector);
      }
    }
  }
  return { neutralised };
})()`;
}

/**
 * 构造「T02 目标外壳 + 长内容」的注入脚本。
 *
 * 结构（与 facts.md §3 的目标结构一致）：
 * body > .stage(padding) > .device(固定高) > .screen(overflow-y:auto) > 应用内容
 *
 * 参数化 paddingPx 的理由：审查者实测 padding 是把守卫从「整段被跳过」（pad=0 时
 * 文档级溢出为 0）变成「运行但通过」（pad=24 时文档级溢出 48）的那个变量，
 * 两种形态都必须覆盖——否则又是在验一个与生产不同的东西。
 *
 * 注入前必须已调用 `neutraliseRealShellScript`（见该函数的说明）。
 */
function shellScript(paddingPx: number): string {
  return `(() => {
  const root = document.getElementById('root');
  if (root === null) return { ok: false, reason: '#root 不存在' };

  const stage = document.createElement('div');
  stage.id = '__sim_stage__';
  stage.style.cssText = 'width:100%;min-height:100vh;display:flex;justify-content:center;' +
    'padding:${String(paddingPx)}px;box-sizing:border-box;';

  const device = document.createElement('div');
  device.id = '__sim_device__';
  device.style.cssText = 'width:390px;height:${String(VIEWPORTS.mobile.height)}px;overflow:hidden;position:relative;';

  const screen = document.createElement('div');
  screen.id = '__sim_screen__';
  screen.style.cssText = 'width:100%;height:100%;overflow-y:auto;';

  while (root.firstChild !== null) screen.append(root.firstChild);
  // 测试明确制造溢出，不依赖产品页碰巧足够长；密度调整后短页也必须保留负对照。
  const content = screen.querySelector('.phone-shell');
  if (content instanceof HTMLElement) {
    content.style.minHeight = '${String(VIEWPORTS.mobile.height + 128)}px';
    const marker = document.createElement('p');
    marker.textContent = '截图守卫测试：展开后必须能看见这一行。';
    marker.style.marginTop = 'auto';
    content.append(marker);
  }
  device.append(screen);
  stage.append(device);
  root.append(stage);

  return {
    ok: true,
    stagePaddingPx: ${String(paddingPx)},
    documentHeight: document.documentElement.scrollHeight,
    viewportHeight: document.documentElement.clientHeight,
    screenScrollHeight: screen.scrollHeight,
    screenClientHeight: screen.clientHeight,
  };
})()`;
}

/**
 * 本证明覆盖的页面。
 *
 * 必须同时含长页与短页——本轮 P1-1' 的盲区正是「内容不高于视口」的短页形态，
 * 而上一版只用 profile（长页），因此盲区逃过了那一轮的永久用例。
 * 选定依据（实测，见探针记录）：
 *   - `profile`：长页，外壳下内层溢出 1184px（最重的溢出）；
 *   - `memory`：短页，外壳下内层溢出 156px 而文档高等于视口高，
 *     正是「required 塌成文档自身高」的形态——旧判据在此漏报。
 */
const EVIDENCE_PAGES = ['profile', 'memory'] as const;

/** 逐页逐 padding 形态的两个方向判定。 */
test('守卫非空洞性：目标外壳下 fullPage 守卫会红，展开后转绿', async ({ page }, testInfo) => {
  // 视口名决定文件名的唯一性：两个 project 并发跑，写同名文件会互相覆盖。
  const viewport = isViewportName(testInfo.project.name) ? testInfo.project.name : 'mobile';
  await mkdir(EVIDENCE_DIR, { recursive: true });

  await installSession(page, { enabled: true });

  for (const pageName of EVIDENCE_PAGES) {
    const shot = PAGE_SHOTS.find((candidate) => candidate.name === pageName);
    expect(shot, `fixtures 里应有 ${pageName} 页配置`).toBeTruthy();
    // 夹具每页装一次（route 的注册顺延到下一次 goto 生效）。
    await installNetwork(page, shot?.fixtures ?? []);

    // 两种外壳形态各跑一遍完整的两方向判定。每轮重新加载页面：
    // 上一轮的模拟外壳与中和样式留在 DOM 里，下一轮注入就会把它套进新的滚动容器里
    // （嵌套独立滚动是真实存在的形态，但会让第二轮验的东西与第一轮不同）。重载把这一整类残留清掉。
    for (const paddingPx of [SHELL_STAGE_PADDING_PX, 0]) {
      const label = `${pageName}-pad${String(paddingPx)}-${viewport}`;
      await page.goto(shot?.path ?? '/profile', { waitUntil: 'load' });
      await expectSessionInjected(page);
      await awaitDisplayFont(page);
      await page.waitForTimeout(300);

      // 先中和 T02 的真实外壳，恢复本用例「应用无外壳」的前提（见函数说明与文件头）。
      const shellNeutralisation = await page.evaluate<{ neutralised: string[] }>(neutraliseRealShellScript());

      await page.evaluate(shellScript(paddingPx));

      // 生产同一个取量函数：P1-1 修正的核心——上一版这里是自己算的内层溢出。
      const overflow = await measureOverflow(page);

      // ── 第一遍：不展开，整页图只会截到外壳首屏 ──
      const trapPath = `${EVIDENCE_DIR}/${label}-NOT-EXPANDED.png`;
      await page.screenshot({ path: trapPath, animations: 'disabled', fullPage: true });
      const trapPng = readPngSize(await readFile(trapPath));

      // 主判据（结构化表征）：此刻仍有容器在裁切 ⇒ 必须抛错。
      // 这是本轮 P1-1' 的修法，也是本证明的核心。
      const trapClipped = await findClippedElements(page);
      let mainCriterionRed = false;
      let mainCriterionMessage = '';
      try {
        assertNoClippedContent(trapClipped, `陷阱态-${label}`);
      } catch (error) {
        mainCriterionRed = true;
        mainCriterionMessage = error instanceof Error ? error.message : String(error);
      }

      // 辅助判据（高度比较）：记录而不作为通过条件。
      // 它在短页上会绿——那正是本轮盲区，把它记下来是为了让「旧判据为什么会漏」留在证据里，
      // 并防止将来有人把辅助判据提回主判据。
      let heightCriterionRed = false;
      try {
        assertFullPageExpanded({
          fullPngHeightPx: trapPng.height,
          measurement: overflow,
          deviceScaleFactor: DEVICE_SCALE_FACTOR,
          context: `陷阱态-${label}`,
        });
      } catch {
        heightCriterionRed = true;
      }

      // ── 第二遍：调用本包实际的展开逻辑（并过 DOM 层的展开断言）──
      const { result, restore, assertRestored, assertExpanded } = await expandForFullPage(page, overflow);
      const expandedPath = `${EVIDENCE_DIR}/${label}-EXPANDED.png`;
      let expansionAssertionMessage = '';
      try {
        await assertExpanded();
      } catch (error) {
        expansionAssertionMessage = error instanceof Error ? error.message : String(error);
      }
      // 无论断言是否通过都截图：这样「展开没生效」的现场也留下证据，
      // 而不是让后面的 readFile 抛一个与病因无关的 ENOENT。
      await page.screenshot({ path: expandedPath, animations: 'disabled', fullPage: true });

      // 截图时刻再扫一遍（与生产同一条断言）。
      const expandedClipped = await findClippedElements(page);
      let captureTimeRed = false;
      try {
        assertNoClippedContent(expandedClipped, `展开后截图-${label}`);
      } catch {
        captureTimeRed = true;
      }

      await restore();
      await assertRestored();

      const expandedPng = readPngSize(await readFile(expandedPath));

      let heightCriterionPasses = true;
      try {
        assertFullPageExpanded({
          fullPngHeightPx: expandedPng.height,
          measurement: overflow,
          deviceScaleFactor: DEVICE_SCALE_FACTOR,
          context: `展开后-${label}`,
        });
      } catch {
        heightCriterionPasses = false;
      }

      const evidenceRecord = {
        label,
        // T02 真实外壳的中和结果：空数组表示该视口下产品本来就没有真实外壳（mobile 的
        // `display: contents` 退化形态下三层仍在 DOM，故通常非空；留档以便区分两种情况）。
        realShellNeutralised: shellNeutralisation.neutralised,
        shell: {
          stagePaddingPx: paddingPx,
          // 同时记文档级与隐藏级，让审查者看出旧判据会漏多少
          documentOverflowPx: overflow.documentOverflowPx,
          innerOverflowPx: overflow.innerOverflowPx,
          requiredContentHeightPx: overflow.requiredContentHeightPx,
          documentHeightPx: overflow.documentHeightPx,
          viewportHeightPx: overflow.viewportHeightPx,
          // 滚动容器清单：本用例应当只有模拟外壳那一个（真实外壳已被中和）
          scrollContainers: overflow.scrollContainers.map((entry) => ({
            selector: entry.selector,
            overflowPx: entry.overflowPx,
          })),
        },
        withoutExpand: {
          pngHeightPx: trapPng.height,
          mainCriterionRed,
          mainCriterionMessage,
          // 辅助判据在陷阱态的结果：短页为 false（= 旧判据的盲区，如实留档）
          heightCriterionRed,
          realClips: trapClipped
            .filter((entry) => entry.deliberateReason === '')
            .map((entry) => ({ selector: entry.selector, clippedByPx: entry.clippedByPx })),
          deliberateClips: trapClipped
            .filter((entry) => entry.deliberateReason !== '')
            .map((entry) => ({ selector: entry.selector, reason: entry.deliberateReason })),
        },
        withExpand: {
          expandedScrollContainer: result.expandedScrollContainer,
          expandedAncestors: result.expandedAncestors,
          pngHeightPx: expandedPng.height,
          captureTimeRed,
          expansionAssertionMessage,
          heightCriterionPasses,
        },
      };

      await testInfo.attach(`guard-nonvacuity-${label}.json`, {
        body: JSON.stringify(evidenceRecord, null, 2),
        contentType: 'application/json',
      });

      // 同时落一份留在磁盘上的证据：testInfo.attach 的产物在 Playwright 的 outputDir 里，
      // 而那个目录每次运行都会被清空——若只写 attach，下一轮跑完这轮的证明就没了。
      await writeFile(`${EVIDENCE_DIR}/guard-nonvacuity-${label}.json`, `${JSON.stringify(evidenceRecord, null, 2)}\n`, 'utf8');

      // 核心断言：未展开时主判据必须抛错，长页短页都要成立。
      // 这正是短页盲区的永久覆盖。
      expect(
        mainCriterionRed,
        `${label}：未展开时应让主判据（结构化表征）抛错——否则守卫在该形态下是空洞的`,
      ).toBe(true);
      // 前提断言：模拟外壳必须是页面上唯一的滚动容器来源。若真实外壳没被中和干净，
      // 这里会出现两个容器（正是 T02 落地后本用例变红的形态），这条断言会直接点名。
      expect(
        overflow.scrollContainers.map((entry) => entry.selector),
        `${label}：中和真实外壳后，滚动容器应只剩模拟外壳这一个（否则本用例又在验叠加形态）`,
      ).toEqual([expect.stringContaining('__sim_screen__')]);
      // 展开后两条判据都必须通过（否则说明展开本身有问题）。
      expect(expansionAssertionMessage, `${label}：DOM 层展开断言应通过，实际报错：${expansionAssertionMessage}`).toBe('');
      expect(captureTimeRed, `${label}：展开后截图时刻不应再有元素裁切内容`).toBe(false);
      expect(heightCriterionPasses, `${label}：展开后辅助判据（高度）应通过`).toBe(true);
      expect(
        result.expandedAncestors.length,
        '展开应穿透祖先链（外壳场景下固定高度的祖先必须一并放开，否则内容仍被裁掉）',
      ).toBeGreaterThan(0);
    }
  }
});
