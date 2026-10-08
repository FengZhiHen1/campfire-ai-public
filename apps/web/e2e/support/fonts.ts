/**
 * 模块: e2e/support/fonts
 * 职责: 真实思源宋体的加载等待与 fail-loud 守卫（判据经可失败性实测选定）
 * 数据来源:
 *   - docs/证据/orchestrator-20261002-001/T01-rulings.md: MUST — 裁决 2
 *     （放行字体两个 host 真实出网；截图前等字体就绪；字体未加载即让用例失败）
 *   - docs/design/tokens.css: MUST — `--font-display` 的第一顺位就是 "Noto Serif SC"
 *   - docs/design/DESIGN.md: MUST — 调性节「宋体标题承载读物的温度」
 * 边界:
 *   - 依赖: playwright 的 Page 类型
 *   - 被依赖: e2e/shots.spec.ts
 * 禁止行为:
 *   - 禁止在字体未加载时继续截图（静默产出回退字形的图，比失败更糟——会让人拿错误的图去审字形）
 *   - 禁止把「判据恒真」当成守卫有效（见下方「关于裁决指定的判据」——已实测其恒真）
 */

import type { Page } from '@playwright/test';

/** 标题字体的族名（与 tokens.css 的 `--font-display` 首顺位一致）。 */
export const DISPLAY_FONT_FAMILY = 'Noto Serif SC';

/**
 * 判据用的字号与字重。
 *
 * 与 `docs/证据/design-render/render.mjs` 采用同一组值（`500 28px`）：字重 500 与字号 28px
 * 都取自契约的标题阶梯，因此这条判据问的是「标题字体在这个实际用法下可用吗」。
 */
export const DISPLAY_FONT_WEIGHT = 500;
export const DISPLAY_FONT_SIZE_PX = 28;

/**
 * 字体判据字符串（CSS font shorthand 语法）。
 *
 * 形状必须是 `<weight> <size> <family>`，族名带引号。
 */
export function displayFontProbe(): string {
  return `${String(DISPLAY_FONT_WEIGHT)} ${String(DISPLAY_FONT_SIZE_PX)}px "${DISPLAY_FONT_FAMILY}"`;
}

/**
 * 真实性判据用的「必然不存在」族名（负对照）。
 *
 * 为什么需要负对照：一条守卫若对不存在的族也返回「可用」，它就永远不会失败，
 * 也就不构成守卫。本模块在每次运行时用同一个判据去问这个不存在的族，
 * 若它也答「可用」，就说明判据本身是坏的——此时直接让用例失败，
 * 而不是让一个恒真的检查冒充守卫（AGENTS.md：禁止留下永远不会失败的检查）。
 */
const NEGATIVE_CONTROL_FAMILY = 'Totally Bogus Font Xyz';

/** 负对照的判据字符串。 */
function negativeControlProbe(): string {
  return `${String(DISPLAY_FONT_WEIGHT)} ${String(DISPLAY_FONT_SIZE_PX)}px "${NEGATIVE_CONTROL_FAMILY}"`;
}

/**
 * 标题字体族出现的等待上界（毫秒）。
 *
 * 有界（CORE-11）：本机实测样式表落定在百毫秒级，5 秒是「本机不可能达到、
 * 真挂住时又不会把失败拖成分钟级」的余量。
 */
const FAMILY_DECLARATION_TIMEOUT_MS = 5_000;

/** 轮询间隔（毫秒）。 */
const FAMILY_DECLARATION_POLL_MS = 100;

/**
 * 取材结果：字体是否真的可用。
 *
 * 同时记录裁决指定的 `check()` 与真正承重的 `load()`/`loadedFaceCount` 判据，
 * 便于审查者看出「哪一条在承重」（见下方说明）。
 */
export interface FontEvidence {
  /** 裁决指定的判据字符串（`document.fonts.check` 的入参）。 */
  probe: string;
  /** `document.fonts.check(probe)` 的返回值。注意：它对本机任意族名都返回 true，不承重。 */
  available: boolean;
  /** `document.fonts.load(probe)` 命中的 FontFace 数量——这是承重判据，0 即字体缺失。 */
  loadedFaceCount: number;
  /** 该族中 `status === 'loaded'` 的 face 数（承重判据之二）。 */
  loadedFacesForFamily: number;
  /** 负对照（不存在的族）在 `document.fonts.load()` 下的命中数，必须为 0。 */
  negativeControlFaceCount: number;
  /** `document.fonts.status`（在有界轮询之后读，避免量到探针自己造成的 loading）。 */
  status: string;
  /** 有界轮询结束时，该族是否已被声明（P2-2 的竞态诊断用；为 false 即「等不到」）。 */
  declaredAfterWait: boolean;
  /** 为等到该族被声明而实际等待的毫秒数。 */
  waitedMs: number;
  /** 页面上被 `@font-face` 声明过的族名（确认思源宋体确实被声明过）。 */
  declaredFamilies: string[];
}

/**
 * 等待字体加载并就绪，并断言标题字体真的可用。
 *
 * 前置: page 已 goto（`index.html` 里的 `<link>` 已发起字体请求）
 * 后置: 返回取证；`loadedFaceCount > 0`、`loadedFacesForFamily > 0`、负对照为 0、status 为 loaded
 *
 * @throws Error 字体未加载、负对照异常（判据恒真）或字体仍在加载中
 *
 * 关于本轮 P2-2：为什么先有界轮询「该族被声明」
 *
 * 审查者与编排器各观测到一次假红（约 1/9 次），失败信息是「已声明的族：（无）」——
 * 说明那一刻 document.fonts 里根本没有 Noto Serif SC 的 @font-face，
 * 即样式表还没被解析进 CSSOM，而不是字体请求失败。
 * document.fonts.ready 不保证这一点：它只保证「当前已知的字体加载结束」，
 * 若评估发生在样式表落定之前，那一刻已知的字体集合就是空的。
 *
 * 处置：有界轮询直到该族出现在 document.fonts（上界 FAMILY_DECLARATION_TIMEOUT_MS），
 * 再做承重断言。这修的是竞态本身，而不是用重试把红抹掉——因此 retries 仍保持 0
 * （重试会让「真的没加载」也变得可以侥幸通过）。
 *
 * 关于裁决指定的判据（实测与裁决不一致，已按意图实现并单列报告）
 *
 * 裁决 2 要求断言 `document.fonts.check('500 28px "Noto Serif SC"') === true`。实测该判据
 * 恒为 true，因此它不可能失败（原始记录 `docs/证据/orchestrator-20261002-001/T01-assets/probe-fontguard.txt`）：
 *
 * ```
 * checkReal:   true    ← 真族名
 * checkBogus:  true    ← 不存在的族名 "Totally Bogus Font Xyz" 也返回 true
 * loadReal:    2       ← load() 命中 2 个 face
 * loadBogus:   0       ← load() 对不存在的族返回 0（这才是可失败的判据）
 * ```
 *
 * CSS Font Loading 规范里 `check()` 只判断「若此处用该族，是否所有需要的字体都已加载」，
 * 而「需要」按字形覆盖判定；对未被任何元素使用的族，规范允许返回 true。
 * 本项目所有中文字形最终都能由系统回退字体渲染，于是 `check()` 恒真。
 *
 * 处置：裁决的意图明确（「不成立即让用例失败」「静默产出回退字形的图比失败更糟」），
 * 但指定的机制达不到该意图。因此本函数：
 *   1. 用可失败的 `load()` + loaded face 计数作为真正的闸门（没有它就是一个假守卫）；
 *   2. 仍在 manifest 里记录 `check()` 的值（`available`），保持与裁决的字面连续，
 *      并在文档里标注它不承重，避免后来者误以为它在把关；
 *   3. 用负对照自检判据本身——若连不存在的族都答「可用」，直接失败，
 *      不让一个恒真的检查冒充守卫。
 *
 * 这条不一致已作为「文档错误类」写入报告 §4.3，附证据对，由编排器裁决。
 */
export async function awaitDisplayFont(page: Page): Promise<FontEvidence> {
  const probe = displayFontProbe();
  const controlProbe = negativeControlProbe();

  const evidence = await page.evaluate(
    async ({
      probeText,
      controlText,
      family,
      timeoutMs,
      pollMs,
    }: {
      probeText: string;
      controlText: string;
      family: string;
      timeoutMs: number;
      pollMs: number;
    }) => {
      /** 该族是否已在 document.fonts 里被声明（不限 status）。 */
      const familyDeclared = (): boolean => {
        let found = false;
        document.fonts.forEach((face) => {
          if (face.family.replace(/["']/g, '') === family) found = true;
        });
        return found;
      };

      // 有界轮询：等样式表把 @font-face 落进 CSSOM（P2-2 的竞态修在这里）。
      let waitedMs = 0;
      let declaredAfterWait = familyDeclared();
      while (!declaredAfterWait && waitedMs < timeoutMs) {
        await new Promise((resolve) => setTimeout(resolve, pollMs));
        waitedMs += pollMs;
        declaredAfterWait = familyDeclared();
      }

      await document.fonts.ready;

      // 关键顺序：先读 status，后调用 load()。
      // `document.fonts.load()` 自身会按需发起新的字体请求（思源宋体被切成上百个
      // unicode-range 子集，探针涉及的子集可能还没被页面用到），于是它会把
      // `document.fonts.status` 打回 'loading'。若在 load() 之后读 status，
      // 读到的就是「探针自己造成的加载中」——那是量错了对象。
      const statusAfterPageLoad = document.fonts.status;

      let loadedForFamily = 0;
      const families = new Set<string>();
      document.fonts.forEach((face) => {
        const normalized = face.family.replace(/["']/g, '');
        families.add(normalized);
        if (normalized === family && face.status === 'loaded') loadedForFamily += 1;
      });

      const loadCount = async (text: string): Promise<number> => (await document.fonts.load(text)).length;
      const loadedFaceCount = await loadCount(probeText);
      const negativeControlFaceCount = await loadCount(controlText);

      // 探针触发的加载落定后再量一次该族的 loaded face 数（这一次是探针之后的状态）。
      await document.fonts.ready;
      let loadedForFamilyAfterProbe = 0;
      document.fonts.forEach((face) => {
        if (face.family.replace(/["']/g, '') === family && face.status === 'loaded') loadedForFamilyAfterProbe += 1;
      });

      return {
        available: document.fonts.check(probeText),
        loadedFaceCount,
        loadedFacesForFamily: Math.max(loadedForFamily, loadedForFamilyAfterProbe),
        negativeControlFaceCount,
        status: statusAfterPageLoad,
        declaredAfterWait,
        waitedMs,
        // 豁免 no-array-sort：排的是展开后的新数组副本；`toSorted` 不在本项目 TS lib 目标里。
        // oxlint-disable-next-line unicorn/no-array-sort
        declaredFamilies: [...families].sort(),
      };
    },
    {
      probeText: probe,
      controlText: controlProbe,
      family: DISPLAY_FONT_FAMILY,
      timeoutMs: FAMILY_DECLARATION_TIMEOUT_MS,
      pollMs: FAMILY_DECLARATION_POLL_MS,
    },
  );

  // 先验判据本身：负对照必须为 0，否则「判据恒真」，后面两条断言都没有意义。
  if (evidence.negativeControlFaceCount !== 0) {
    throw new Error(
      `字体判据自检失败：document.fonts.load('${controlProbe}') 命中 ` +
        `${String(evidence.negativeControlFaceCount)} 个 face，而该族名必然不存在。` +
        '这说明判据本身是坏的（恒真），它无法承担守卫职责——先修判据，再谈字体是否加载。',
    );
  }

  if (evidence.loadedFaceCount === 0 || evidence.loadedFacesForFamily === 0) {
    // 把「等到了但没加载」与「根本没等到声明」分开写：两者病因不同（前者是 CDN/网络，
    // 后者是样式表没落定或 index.html 没引入），混成一句话会让排障从错误方向开始。
    const diagnosis = evidence.declaredAfterWait
      ? `该族的 @font-face 已声明（等待 ${String(evidence.waitedMs)}ms），但 face 未加载——指向字体文件请求失败（CDN 不可达或返回异常）`
      : `等待 ${String(evidence.waitedMs)}ms 后该族的 @font-face 仍未出现在 document.fonts——指向样式表未落定或页面未引入该字体`;
    throw new Error(
      `标题字体「${DISPLAY_FONT_FAMILY}」不可用：` +
        `document.fonts.load('${probe}') 命中 ${String(evidence.loadedFaceCount)} 个 face、` +
        `该族 loaded face 数 ${String(evidence.loadedFacesForFamily)}（status=${evidence.status}，` +
        `已声明的族：${evidence.declaredFamilies.join(' / ') || '（无）'}）。${diagnosis}。` +
        '截图会退化为系统回退字形，字号阶梯/字重/行宽的观感全部失真，证据不可用。' +
        '请修好后重跑——这条守卫失败是预期行为，不是可以放宽的噪声。',
    );
  }

  if (evidence.status !== 'loaded') {
    throw new Error(`字体状态为 ${evidence.status} 而非 loaded：仍有字体请求未结束，此时截图可能截到字形切换的中间态`);
  }

  return { probe, ...evidence };
}
