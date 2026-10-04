/**
 * 模块: e2e/shots
 * 职责: 全页基线截图——十页 × 两视口 × 两图种（视口图 + fullPage 图），逐页注入登录态、
 *       装夹具、等字体、断内容、落盘并写 sidecar
 * 数据来源:
 *   - .tmp/dev-orchestrator/20261002-001/tasks/T01.md: MUST — 目标 1～4、裁决 B/C/D/E/F
 *   - .tmp/dev-orchestrator/20261002-001/feedback/T01-rulings.md: MUST — 裁决 1（两图种都要、
 *     尺寸断言拆两条、fixed 中和）与其追加裁决（fullPage 必须真的展开滚动容器 + fail-loud
 *     高度守卫）与裁决 2（字体真实加载 + document.fonts.check fail-loud）
 *   - apps/web/src/app/routes.tsx: MUST — 十条路由的权威清单
 * 边界:
 *   - 依赖: e2e/support/*、@playwright/test
 *   - 被依赖: 无（由 `pnpm --filter @campfire/web shots` 驱动）
 * 禁止行为:
 *   - 禁止用 dev server 代替 preview（裁决 B：截图对象是构建产物）
 *   - 禁止在字体未加载时出图（裁决 2：静默产出回退字形的图比失败更糟）
 *   - 禁止在中和样式未恢复时继续写 sidecar（残留会污染后续断言与记录）
 *
 * 落盘结构：每张图一条独立 sidecar（`<out>/.run/<file>.json`），由 manifest.spec.ts 在依赖
 * 项目里汇总。为什么不在本文件里汇总：截图用例并发执行，谁先跑完不确定；让汇总发生在全部
 * 截图之后的独立 project 里，时序才不会漂。
 */

import { mkdir, readFile } from 'node:fs/promises';

import { expect, test } from '@playwright/test';

import { evaluateAssertions } from './support/assertions';
import { effectiveFixtures, PAGE_SHOTS } from './support/fixtures';
import { awaitDisplayFont, type FontEvidence } from './support/fonts';
import { readPngSize, sha256Of, writeSidecar, type ShotSidecar } from './support/manifest';
import {
  assertFullPageExpanded,
  assertNoFixedAtCaptureTime,
  assertNothingClippedAtCaptureTime,
  expandForFullPage,
  measureOverflow,
  type NeutraliseResult,
} from './support/neutralise';
import {
  expectNeverRequested,
  expectNoExternalRequests,
  expectNoUnmatchedApi,
  installNetwork,
  waitForLedgerQuiet,
} from './support/network';
import {
  DEVICE_SCALE_FACTOR,
  PNG_HEIGHT_TOLERANCE_PX,
  PAGE_NAMES,
  SIDECAR_DIR,
  VIEWPORTS,
  VIEWPORT_NAMES,
  isViewportName,
  sidecarPath,
  shotFilePath,
  toRepoRelative,
  type PageName,
  type ShotKind,
  type ViewportName,
} from './support/paths';
import { expectSessionInjected, installSession } from './support/session';
import { readRunId } from './support/runid';

/**
 * 登录态注入开关（只给消融实验用，默认注入）。
 *
 * 任务包要求三次消融各自证明「机制能失败」：兜底 handler、登录态注入、内容断言。
 * 后两者的「关掉」分别由本开关与 fixtures 里的 SHOTS_ABLATION_EMPTY_LIST 承担。
 * 开关读环境变量而不是命令行选项：`playwright test` 会拒绝未知选项（同一理由见 paths.ts）。
 */
const SESSION_INJECTION_ENABLED = process.env.SHOTS_ABLATION_NO_SESSION !== '1';

/**
 * fullPage 图高的容差（CSS px；比对时再乘倍率）。
 *
 * 定义在 `paths.ts`，与 manifest 汇总共用同一个值——两处若各自定义，会出现
 * 「用例通过但汇总失败」的错位。
 */
const HEIGHT_TOLERANCE_PX = PNG_HEIGHT_TOLERANCE_PX;

/**
 * 断言 project 名是已知视口名。
 *
 * 不用 `as ViewportName`：类型逃逸会让 project 改名后的行为从「编译期报错」退化成
 * 「运行时用错视口却不报」，而视口名同时决定像素尺寸断言，错了就是一条假绿。
 */
function viewportOf(projectName: string): ViewportName {
  if (!isViewportName(projectName)) {
    throw new Error(`playwright.config.ts 的 project 名 ${projectName} 不是已知视口名（${VIEWPORT_NAMES.join(' / ')}）`);
  }
  return projectName;
}

/** 把 fixtures 里的语义短名收窄到裁决 E 的命名表；不在表内即失败，不静默返回原名。 */
function pageNameOf(name: string): PageName {
  const match: PageName | undefined = PAGE_NAMES.find((candidate) => candidate === name);
  if (match === undefined) throw new Error(`fixtures 里的页面短名 ${name} 不在裁决 E 的命名表内`);
  return match;
}

test.beforeAll(async () => {
  await mkdir(SIDECAR_DIR, { recursive: true });
  // 批号由 global.setup.ts 写入；这里读一次供本文件的每条 sidecar 记录。
  runIdForThisWorker = await readRunId();
});

/**
 * 本 worker 读到的运行批号。
 *
 * 在 `beforeAll` 里读一次（而不是每条 sidecar 各读一次文件）：批号在一次运行内不变，
 * 而 worker 之间共享同一个落点——若每条都读文件，理论上会被并发写盘扰动。
 */
let runIdForThisWorker = '';

for (const shot of PAGE_SHOTS) {
  const pageName = pageNameOf(shot.name);

  test(`${shot.name} 双图种截图与内容断言`, async ({ page }, testInfo) => {
    const viewport = viewportOf(testInfo.project.name);

    // 顺序不可调换：注入必须在 goto 之前（SDK 在冷启动查一次会话），
    // 夹具也必须在 goto 之前（首个接口请求可能早于 load 事件）。
    await installSession(page, { enabled: SESSION_INJECTION_ENABLED });
    const ledger = await installNetwork(page, effectiveFixtures(shot));

    const pageProblems: string[] = [];
    page.on('console', (message) => {
      if (message.type() === 'error') pageProblems.push(`console.error: ${message.text()}`);
    });
    page.on('pageerror', (error) => {
      pageProblems.push(`pageerror: ${error.message}`);
    });

    await page.goto(shot.path, { waitUntil: 'load' });

    if (shot.guarded) {
      await expectSessionInjected(page);
    }

    // 字体必须真的就绪才截图：字体 CDN 不可达时这里明确失败（裁决 2 的 fail-loud）。
    const fontEvidence: FontEvidence = await awaitDisplayFont(page);

    // fail-closed 判定必须早于内容断言：它是内容断言的前提。夹具没覆盖全时，
    // 「内容断言失败」会把原因指向页面形态，而真实原因是夹具没写。
    // 先等账本静默（页面请求发完），再点名未覆盖的 URL。
    const quiet = await waitForLedgerQuiet(ledger);
    if (!quiet.settled) {
      // 账本未在上界内静默：fail-closed 仍照常判定，但这件事必须留痕——
      // 静默丢弃它会让「请求还没发完就判通过」这种情况无声无息（P2-6）。
      await testInfo.attach(`${pageName}-${viewport}-ledger-not-quiet.json`, {
        body: JSON.stringify(
          {
            settled: quiet.settled,
            elapsedMs: quiet.elapsedMs,
            recordCount: ledger.records.length,
            note: '账本未在上界内静默；fail-closed 判定仍然执行，但存在「判定时请求尚未发完」的可能',
          },
          null,
          2,
        ),
        contentType: 'application/json',
      });
    }
    expectNoUnmatchedApi(ledger);
    expectNoExternalRequests(ledger);
    expectNeverRequested(ledger, shot.mustNotRequest ?? []);

    const evidence = await evaluateAssertions(page, shot.assertions);

    // 截图前量一次真实的纵向溢出：它既是「视口图裁掉了多少」的记录，
    // 也是 fullPage 高度守卫的唯一输入（必须在中和/展开之前量，展开会把溢出消掉）。
    //
    // 本轮 P1-1 的根因正是这里曾经只取「文档级」溢出：设备外壳结构下溢出发生在内层
    // 滚动容器，文档级值要么 0（守卫被跳过）要么很小（守卫通过），1184px 被藏住而守卫
    // 毫无反应。measureOverflow 同时给出文档级与内层容器两种形态并取 max，从源头堵住
    // 「量错对象」。
    const overflow = await measureOverflow(page);
    const scroll = {
      documentHeight: overflow.documentHeightPx,
      viewportHeight: overflow.viewportHeightPx,
      documentWidth: overflow.documentWidthPx,
      viewportWidth: overflow.viewportWidthPx,
    };
    const truncatedByPx = overflow.documentOverflowPx;

    // 豁免 no-array-sort：排的是展开后的新数组副本；`toSorted` 不在本项目 TS lib 目标里。
    // oxlint-disable-next-line unicorn/no-array-sort
    const allowedExternalHosts = [...new Set(ledger.allowedExternal.map((record) => new URL(record.url).hostname))].sort();

    /**
     * 落一张图并写它的 sidecar。
     *
     * 尺寸断言按 kind 分两条（裁决 1）：视口图宽高都 = 视口 × 倍率；
     * fullPage 图宽 = 视口宽 × 倍率、高 = 展开后内容高 × 倍率（容差见 HEIGHT_TOLERANCE_PX）。
     */
    const capture = async (kind: ShotKind, neutralised: NeutraliseResult | null): Promise<void> => {
      const filePath = shotFilePath(pageName, viewport, kind);

      // animations: 'disabled' 让循环/一次性动效停在稳定帧——否则呼吸点与确认单滑入
      // 会让同一页两次截图的字节不同（幂等要求：重复执行产出相同画面）。
      await page.screenshot({ path: filePath, animations: 'disabled', fullPage: kind === 'full' });

      // 落盘即复算：先读回真实字节再写 sidecar，sidecar 里不留「我以为写成了」的值。
      const bytes = await readFile(filePath);
      const size = readPngSize(bytes);
      const expected = VIEWPORTS[viewport];
      const expectedWidth = expected.width * DEVICE_SCALE_FACTOR;

      if (kind === 'viewport') {
        expect(
          { width: size.width, height: size.height },
          `${pageName}-${viewport}.png（视口图）的像素尺寸应为「视口 × ${String(DEVICE_SCALE_FACTOR)}」`,
        ).toEqual({ width: expectedWidth, height: expected.height * DEVICE_SCALE_FACTOR });
      } else {
        if (neutralised === null) throw new Error('fullPage 图缺少中和结果，无法校验高度');
        expect(
          size.width,
          `${pageName}-${viewport}-full.png（fullPage 图）的宽应为视口宽 × ${String(DEVICE_SCALE_FACTOR)}`,
        ).toBe(expectedWidth);
        const expectedHeight = neutralised.contentHeightPx * DEVICE_SCALE_FACTOR;
        const delta = Math.abs(size.height - expectedHeight);
        expect(
          delta,
          `${pageName}-${viewport}-full.png 的高 ${String(size.height)} 与「展开后内容高 × ${String(DEVICE_SCALE_FACTOR)}」` +
            `=${String(expectedHeight)} 相差 ${String(delta)}px（容差 ${String(HEIGHT_TOLERANCE_PX * DEVICE_SCALE_FACTOR)}px）`,
        ).toBeLessThanOrEqual(HEIGHT_TOLERANCE_PX * DEVICE_SCALE_FACTOR);
      }

      const sidecar: ShotSidecar = {
        page: pageName,
        viewport,
        kind,
        runId: runIdForThisWorker,
        file: toRepoRelative(filePath),
        absolutePath: filePath,
        sha256: sha256Of(bytes),
        bytes: bytes.byteLength,
        width: size.width,
        height: size.height,
        assertedContent: evidence,
        fixtureNote: shot.note,
        scroll: {
          ...scroll,
          truncatedByPx,
          horizontalOverflowPx: Math.max(0, scroll.documentWidth - scroll.viewportWidth),
          innerOverflowPx: overflow.innerOverflowPx,
          hiddenOverflowPx: overflow.hiddenOverflowPx,
          requiredContentHeightPx: overflow.requiredContentHeightPx,
          hiddenOverflowContainers: overflow.scrollContainers,
        },
        allowedExternalHosts,
        fontLoaded: fontEvidence.loadedFaceCount > 0 && fontEvidence.loadedFacesForFamily > 0,
        fontProbe: fontEvidence.probe,
        fontCheckResult: fontEvidence.available,
        fontLoadedFaceCount: fontEvidence.loadedFaceCount,
        fontLoadedFacesForFamily: fontEvidence.loadedFacesForFamily,
        fontNegativeControlFaceCount: fontEvidence.negativeControlFaceCount,
        fontStatus: fontEvidence.status,
        fontDeclaredFamilies: fontEvidence.declaredFamilies,
        fixedNeutralised: neutralised?.fixedNeutralised ?? false,
        neutralisedSelectors: neutralised?.neutralisedSelectors ?? [],
        expandedScrollContainer: neutralised?.expandedScrollContainer ?? null,
        expandedAncestors: neutralised?.expandedAncestors ?? [],
        contentHeightPx: neutralised?.contentHeightPx ?? null,
        requests: ledger.records.map((record) => {
          // 只留「动作 + 路径」：域名固定是 127.0.0.1:4173，把它写进每一行只会淹没差异。
          const parsed = new URL(record.url);
          return `${record.method} ${parsed.pathname}${parsed.search}`;
        }),
      };
      await writeSidecar(sidecarPath(pageName, viewport, kind), sidecar);
    };

    // 视口图先截：它必须反映未中和的真实渲染状态（中和只在 fullPage 那一步临时发生）。
    await capture('viewport', null);

    // fullPage 图：临时中和 fixed + 展开主滚动容器，截完立刻恢复并断言回到原状。
    //
    // 消融态（`SHOTS_ABLATION_NO_EXPAND=1`）也走同一个函数——只是它内部跳过
    // loosening（见 neutralise.ts 的 EXPANSION_ENABLED）。这样两个机制才真的各自独立：
    // D1 只关掉「展开」而 fixed 中和照常注入，D2（NO_FIXED_FIX）只关掉中和。
    // 早先的写法是消融分支整段跳过本函数，于是中和也没注入，而注释却说「照常注入」
    // （本轮 P2-C）——那样 D1 的长图会带着卡在中段的 tab 栏，测到的东西与注释不符。
    //
    // measurement 由调用方传入且与守卫同源：展开会把溢出消掉，故必须在展开之前量。
    const { result, restore, assertRestored, assertExpanded } = await expandForFullPage(page, overflow);
    try {
      // 中和必须真的生效才截图：失效时尺寸断言与高度守卫都发现不了
      // （图还是那么高），只有 fixed 元素被画错位置——故这一步不可省。
      await assertNoFixedAtCaptureTime(page);
      // 截图前再扫一遍裁切：覆盖「展开看起来生效了、但此刻又被裁回去」的情形。
      // 主判据是结构化表征（有无元素在裁内容），不依赖任何数值比较。
      await assertNothingClippedAtCaptureTime(page);
      // DOM 层确认展开生效（结构化主判据 + 辅助高度判据）。
      await assertExpanded();
      await capture('full', result);
    } finally {
      await restore();
    }

    // 恢复必须被验证，不能只是「我以为恢复了」（追加裁决第 1 条明确要求）。
    await assertRestored();

    // 高度守卫（辅助判据）：整页图高须覆盖「最高滚动来源的内容高」。
    // 判据在 support/neutralise.ts 的 assertFullPageExpanded，入参就是上面那个 overflow——
    // 与 guard-nonvacuity.spec.ts 用的是同一个取量函数与同一个判据函数，
    // 因此那里证明「会抛错」就等于证明生产路径会抛错。
    {
      const fullBytes = await readFile(shotFilePath(pageName, viewport, 'full'));
      assertFullPageExpanded({
        fullPngHeightPx: readPngSize(fullBytes).height,
        measurement: overflow,
        deviceScaleFactor: DEVICE_SCALE_FACTOR,
        context: `${pageName}-${viewport}`,
      });
    }

    // 控制台错误不阻断截图，但要落进运行日志供审查者判断（不静默）。
    if (pageProblems.length > 0) {
      await testInfo.attach(`${pageName}-${viewport}-page-problems.log`, {
        body: pageProblems.join('\n'),
        contentType: 'text/plain',
      });
    }
  });
}