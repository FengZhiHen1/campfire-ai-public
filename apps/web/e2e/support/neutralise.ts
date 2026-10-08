/**
 * 模块: e2e/support/neutralise
 * 职责: fullPage 截图前的两处布局中和——fixed 元素入流、主滚动容器及其祖先链展开（以及截后恢复）
 * 数据来源:
 *   - docs/证据/orchestrator-20261002-001/T01-rulings.md: MUST — 裁决 1「fullPage 的已知陷阱」
 *     与其追加裁决第 1、2、3 条（必须展开实际滚动容器、必须恢复并断言回到原状、加高度守卫）
 *   - docs/证据/design-render/render.mjs:59 与 docs/证据/design-render/README.md:29-33: MUST —
 *     本仓既有的同语义解法：用 `position: static !important` 把吸附/固定中和为文档流
 *   - apps/web/src/shared/styles/components.css:446,642: MUST — 产物里唯二的 position:fixed 规则
 *     是 `.tab-bar` 与 `.confirm-sheet`（由编译产物的 CSS 实测枚举，非猜测）
 * 边界:
 *   - 依赖: playwright 的 Page 类型
 *   - 被依赖: e2e/shots.spec.ts
 * 禁止行为:
 *   - 禁止改任何视觉参数（颜色/边框/圆角/尺寸/间距）——只动 position 与布局约束
 *   - 禁止不恢复（同一 page 上后续还要跑内容断言与写 sidecar；残留样式会污染记录）
 *   - 禁止只展开滚动容器而不管其祖先（固定高度的祖先会把展开后的内容重新裁掉）
 */

import type { Page } from '@playwright/test';

import { CSS_LAYOUT_TOLERANCE_PX, PNG_HEIGHT_TOLERANCE_PX } from './paths';

/**
 * 中和 fixed 的注入样式。
 *
 * 只把 `position` 改为 `static`，不改任何视觉参数——与 `docs/证据/design-render/render.mjs` 的
 * `FLOW_CSS` 同语义（那边中和的是 `.emergency-controls` 的 sticky）。用 `!important`
 * 是必要的：要覆盖的规则本身在产物里带同等或更高特异性，且这段样式必须赢。
 *
 * 为什么必须中和：`.tab-bar` 与 `.confirm-sheet` 是 `position: fixed`。Chromium 的 fullPage
 * 截图会让 fixed 元素只出现在其视口位置，于是长图里底部导航会卡在中间——视觉审查会误读成
 * 「页面中段浮着一条栏」。中和后它们按文档流出现在页面末尾，与 `docs/证据/design-render/README.md`
 * 第 33 行登记的取舍一致（「固定定位元素在分区图里按文档流呈现，不代表运行时的覆盖层级」）。
 */
const NEUTRALISE_CSS = `
.tab-bar, .confirm-sheet {
  position: static !important;
}
`;

/** 注入样式节点的 id；恢复时按它精确移除。 */
const STYLE_ELEMENT_ID = '__shots_neutralise__';

/** 产物里唯二的 fixed 选择器（由编译产物的 CSS 实测枚举）。 */
const FIXED_SELECTORS = ['.tab-bar', '.confirm-sheet'] as const;

/**
 * 是否展开主滚动容器（只给消融实验用，默认展开）。
 *
 * 关掉它（`SHOTS_ABLATION_NO_EXPAND=1`）只影响展开这一步；fixed 中和与
 * `assertNoFixedAtCaptureTime` 照常走——于是两个机制各自独立可消融：
 * 本开关只检验「有没有真的展开」，`SHOTS_ABLATION_NO_FIXED_FIX` 只检验 fixed 断言。
 *
 * 注意这条承诺的调用方义务（本轮 P2-C）：关掉展开时，调用方仍须调用
 * `expandForFullPage`（它内部按本开关决定跳不跳过 loosening），而不得整段跳过该函数——
 * 否则 fixed 中和也不会注入，D1 那轮的长图会带着「卡在中段的 tab 栏」，
 * 而这条注释却说中和照常。正确做法见 `shots.spec.ts` 的 fullPage 分支：
 * 消融态走同一个函数、只是它内部不展开。
 */
const EXPANSION_ENABLED = process.env.SHOTS_ABLATION_NO_EXPAND !== '1';

/** 是否注入 fixed 中和样式（只给消融实验用，默认注入）。 */
const FIXED_NEUTRALISATION_ENABLED = process.env.SHOTS_ABLATION_NO_FIXED_FIX !== '1';

/**
 * 断言截图时刻页面上没有任何 `position: fixed` 的元素。
 *
 * 前置: 已注入中和样式并等待样式生效（fullPage 截图之前调用）
 * 后置: 通过——所有 fixed 选择器的计算样式都不是 fixed
 *
 * @throws Error 仍有元素是 fixed——fullPage 图会把它们画在视口位置（长图中段），
 *   看起来像「页面中段浮着一条底部导航」，会让视觉审查误读版式
 *
 * 为什么这条守卫是必要的（而不是「中和了就行」）：中和样式失效时，尺寸断言与高度守卫
 * 都不会发现——图还是那么高、宽也对，只是 fixed 元素被画错了位置。
 * 这是本包唯一能发现该失真的断言，故它必须真的会失败（见 ablation-D2 的实测）。
 */
export async function assertNoFixedAtCaptureTime(page: Page): Promise<void> {
  const stillFixed = await page.evaluate((selectors: readonly string[]) => {
    const offenders: string[] = [];
    for (const selector of selectors) {
      for (const element of Array.from(document.querySelectorAll(selector))) {
        if (getComputedStyle(element).position === 'fixed') offenders.push(selector);
      }
    }
    return offenders;
  }, FIXED_SELECTORS);

  if (stillFixed.length > 0) {
    throw new Error(
      `fullPage 截图时刻仍有 position:fixed 的元素（${[...new Set(stillFixed)].join(' / ')}）：` +
        'Chromium 会把 fixed 元素画在它的视口位置，于是长图里底部导航卡在页面中段，' +
        '视觉审查会误读成「页面中段浮着一条栏」。中和样式未生效或未注入。',
    );
  }
}

/** 单个被改过布局约束的元素及其原始内联值。 */
interface LayoutBackup {
  /** `documentElement` / `body`，或元素的 `tag.class` 描述。 */
  target: string;
  height: string;
  maxHeight: string;
  overflowY: string;
}

/**
 * 一个正在裁切内容的元素（结构化表征）。
 *
 * 这是本包守卫的主判据：展开失效的直接表征就是「还有元素在裁切它的内容」。
 * 它不依赖任何跨来源数值比较，因而天然结构无关——见 `findClippedElements` 的说明。
 */
export interface ClippedElement {
  /** 元素描述（标签 + id + 类名）。 */
  selector: string;
  /** 计算样式的 `overflow-y`。 */
  overflowY: string;
  /** 可视高（CSS px）。 */
  clientHeightPx: number;
  /** 内容高（CSS px）。 */
  scrollHeightPx: number;
  /** 被裁掉的纵向像素（`scrollHeight - clientHeight`）。 */
  clippedByPx: number;
  /** 为什么它不算被裁（若属于刻意截断）；为空串表示确实在裁切内容。 */
  deliberateReason: string;
}

/**
 * 扫描页面上所有正在裁切内容的元素。
 *
 * 为什么这是主判据（而不是继续修数值比较）
 *
 * 前三轮我在同一个判据上连续犯了三种错：量选错（文档级 vs 内层级）、算式错（跨来源相加）、
 * 比较式错——最后这次是「图高 ≥ X」这个比较**根本无法区分「已展开」与
 * 「未展开但文档恰好够高」**：短内容下 `required` 塌成文档自身高，陷阱图高恰好等于需要值。
 * 结构化表征问的是另一个问题：「此刻还有东西被裁吗？」——它有明确的是/否，
 * 不经过任何数值阈值，因此不会出现「两个状态落到同一个值」的情形。
 *
 * 扫描集合
 *
 * `overflow-y ∈ {auto, scroll, hidden, clip}`。含 `hidden`/`clip` 是必须的：
 * `overflow:hidden` 的外壳会把内容裁掉且不可滚动，只看 `auto|scroll` 完全看不见它
 * （审查者的矩阵里那 2 个 `clip-hidden` 形态正是如此）。
 *
 * 排除刻意截断（否则会把真守卫换成假红源）
 *
 * 真实应用里存在设计决定的截断，它们不是缺陷，`fullPage` 本就不该展开它们：
 *   1. `text-overflow: ellipsis` —— 单行省略。实测 `span.sp-title`
 *      （`components.css:437`）`clientHeight=36 / scrollHeight=38`，差 2px；
 *   2. `-webkit-line-clamp` 非 none —— 多行 clamp（`libraryPage.module.css:65`、
 *      `memoryPage.module.css:10`）；
 *   3. `clip-path` 非 none —— 视觉隐藏。实测 `.sr-only`
 *      （`components.css:75`：1×1px + `clip-path: inset(50%)`）差 27px，
 *      是无障碍用途的视觉隐藏（内容对屏幕阅读器仍可见），更不是「被裁的内容」。
 *
 * 前两条由裁决明确要求；第三条是我用真实页面探针发现的（`docs/证据/orchestrator-20261002-001/T01-assets/probe-clip-mobile.txt`：
 * 若不排除，`chat` 与 `cases` 各有一个 27px 的假红源）。三者的共同点是
 * 该 CSS 属性的用途就是截断，所以按属性判定比按像素差判定更本质。
 *
 * 容差
 *
 * 其余元素允许 `CSS_LAYOUT_TOLERANCE_PX`（2 CSS px）。依据见该常量的注释——核心是
 * 「刻意截断按属性排除，容差只吸收整数取整」，且实测排除后非刻意条目为 0。
 *
 * 前置: page 已 goto 且内容渲染稳定
 * 后置: 返回所有仍在裁切内容的元素（含刻意截断项，带 `deliberateReason`），按被裁量降序
 * 异常: 无——测量失败返回空数组，由调用方决定（不在这里抛，避免把测量问题伪装成断言问题）
 */
export async function findClippedElements(page: Page): Promise<ClippedElement[]> {
  return page.evaluate((tolerancePx: number): ClippedElement[] => {
    /** 给元素生成一个够用的描述：标签名 + 可选 id + 可选类名。 */
    const describe = (element: Element): string => {
      const tag = element.tagName.toLowerCase();
      const idPart = element.id === '' ? '' : `#${element.id}`;
      const classPart = element.classList.length === 0 ? '' : `.${[...element.classList].join('.')}`;
      return `${tag}${idPart}${classPart}`;
    };

    /** 该元素是否属于「刻意截断」；返回原因字符串或空串。 */
    const deliberateReasonOf = (computed: CSSStyleDeclaration): string => {
      if (computed.textOverflow === 'ellipsis') return 'text-overflow: ellipsis（单行省略，设计内截断）';
      const clamped = computed.webkitLineClamp;
      if (clamped !== 'none' && clamped !== '') return `-webkit-line-clamp: ${clamped}（多行 clamp，设计内截断）`;
      if (computed.clipPath !== 'none') return `clip-path: ${computed.clipPath}（视觉隐藏，如 .sr-only）`;
      return '';
    };

    const found: ClippedElement[] = [];
    for (const element of Array.from(document.querySelectorAll('*'))) {
      const computed = getComputedStyle(element);
      if (!['auto', 'scroll', 'hidden', 'clip'].includes(computed.overflowY)) continue;
      const clippedByPx = element.scrollHeight - element.clientHeight;
      // 容差吸收整数取整（依据见 CSS_LAYOUT_TOLERANCE_PX 的注释）。
      if (clippedByPx <= tolerancePx) continue;
      found.push({
        selector: describe(element),
        overflowY: computed.overflowY,
        clientHeightPx: element.clientHeight,
        scrollHeightPx: element.scrollHeight,
        clippedByPx,
        // 刻意截断的元素也返回（带上原因），而不是在这里静默过滤掉：
        // 调用方能从返回值里看到「它被看见了、但按设计不算被裁」，排障时不会有盲区。
        deliberateReason: deliberateReasonOf(computed),
      });
    }
    // 按被裁量降序：失败信息里最严重的那条排在最前，便于一眼看到主因。
    // 豁免 no-array-sort：排的是本函数内新建的数组；`toSorted` 不在本项目 TS lib 目标里。
    // oxlint-disable-next-line unicorn/no-array-sort
    return found.sort((left, right) => right.clippedByPx - left.clippedByPx);
  }, CSS_LAYOUT_TOLERANCE_PX);
}

/**
 * 断言给定的扫描结果里没有「真的在裁切内容」的元素。
 *
 * 前置: `clipped` 来自 `findClippedElements(page)`
 * 后置: 通过——不存在 `deliberateReason === ''` 的条目
 *
 * @throws Error 存在真裁切元素——fullPage 图只截到了它们的可视部分，内容被丢在可视区之外
 *
 * 为什么做成纯函数（收扫描结果而不是自己扫）：调用方在两个时刻需要它——
 * 「展开之后」（`assertExpanded`）与「截图时刻」（`assertNothingClippedAtCaptureTime`），
 * 两处的判据必须是同一份实现，否则又是一次「同一量两条口径」。
 */
export function assertNoClippedContent(clipped: readonly ClippedElement[], context: string): void {
  const real = clipped.filter((entry) => entry.deliberateReason === '');
  if (real.length === 0) return;

  const details = real
    .map((entry) => `${entry.selector}（overflow-y:${entry.overflowY}，裁掉 ${String(entry.clippedByPx)}px）`)
    .join('、');
  throw new Error(
    `${context} 时刻仍有 ${String(real.length)} 个元素在裁切内容：${details}。` +
      'fullPage 图只截到这些元素的可视部分，被裁掉的内容不在图里——长图不可用于逐页版式审计。' +
      '若这些是设计内的截断（单行省略 / line-clamp / clip-path），应落在 deliberateReason 分支里而不计入。',
  );
}

/** 中和与展开的取证记录。 */
export interface NeutraliseResult {
  /** 是否确实中和了至少一个 fixed 元素。 */
  fixedNeutralised: boolean;
  /** 被中和的 fixed 选择器（本次实际命中的）。 */
  neutralisedSelectors: string[];
  /**
   * 被展开的滚动容器。
   *
   * 单个容器时是它的元素描述；多个时用顿号连接（T02 落地后可能出现真实外壳与
   * 测试构造的模拟外壳同时存在——见 `expandForFullPage` 里「为什么返回全部」）；
   * `documentElement` 表示页面本身不滚动、走文档滚动那条分支。
   */
  expandedScrollContainer: string;
  /**
   * 被展开的祖先链（不含滚动容器自身），供审查者判断展开是否穿透了外层固定高度。
   *
   * 多个滚动容器时是它们祖先链的并集（去重后按文档序）。
   */
  expandedAncestors: string[];
  /**
   * 展开后测得的内容高（CSS px）——即 fullPage 图应有的高度（乘倍率后比对）。
   *
   * 注意：该值不再是主判据（见 `findClippedElements` 的说明）。
   * 它保留下来作为辅助：用于尺寸断言与取证记录，以及
   * `capture()` 那条「图高 ≈ 内容高」的一致性校验。
   */
  contentHeightPx: number;
}

/** 一个仍在纵向溢出的滚动容器。 */
export interface ScrollContainerOverflow {
  /** 元素描述（标签 + id + 类名）。 */
  selector: string;
  /** 被这个容器藏住的纵向像素（`scrollHeight - clientHeight`）。 */
  overflowPx: number;
  /** 该容器的内容总高（`scrollHeight`）——容器内全部内容平铺后的高度。 */
  scrollHeightPx: number;
  /** 该容器的可视高（`clientHeight`）。 */
  clientHeightPx: number;
}

/**
 * 页面的纵向溢出测量——生产守卫的唯一输入。
 *
 * 为什么要有这个结构体、而不是让守卫收一个裸数字：本轮 P1-1 的根因正是「喂错了量」——
 * 生产调用点喂的是文档级溢出，而设备外壳结构下溢出发生在内层滚动容器里，
 * 于是守卫要么被整段跳过、要么用一个比真实藏住量小一个数量级的数字通过。
 * 把「该量什么」收进一个函数、并让守卫只接受这个结构体，就从签名上排除了
 * 「调用方自己算一个别的数」（例如只取 `documentElement` 的差）这一类错误。
 */
export interface OverflowMeasurement {
  /** 视口高（CSS px）= `documentElement.clientHeight`。 */
  viewportHeightPx: number;
  /** 视口宽（CSS px）= `documentElement.clientWidth`。 */
  viewportWidthPx: number;
  /** 文档高（CSS px）= `documentElement.scrollHeight`。 */
  documentHeightPx: number;
  /** 文档宽（CSS px）= `documentElement.scrollWidth`。 */
  documentWidthPx: number;
  /** 文档级纵向溢出（CSS px）；0 表示文档本身不滚动。 */
  documentOverflowPx: number;
  /**
   * 所有仍在纵向溢出的内部滚动容器（`overflow-y` 为 auto/scroll 且确实溢出）。
   *
   * 保留清单而非只留最大值：审查者据此知道是哪个元素藏了内容，
   * 而不是只看到一个数字（排障时「1184 藏在哪」比「有 1184」有用得多）。
   */
  scrollContainers: ScrollContainerOverflow[];
  /** 内部容器的最大纵向溢出（CSS px）；无内部滚动容器时为 0。 */
  innerOverflowPx: number;
  /**
   * 隐藏溢出（CSS px）= `max(documentOverflowPx, innerOverflowPx)`。
   *
   * 这是「文档级」与「内层容器」两种滚动形态的统一判据，因此与结构无关——
   * 当前实现（文档滚动）取到文档级那份，设备外壳落地后（内层 `.device-screen` 滚动）
   * 取到内层那份，守卫都能看到一个与真实藏住量同量级的值。
   *
   * 已知边界（如实登记，不掩饰）：取 `max` 而非求和，因此对
   * 「外层容器自己藏一部分、其可见区内又嵌一个独立滚动容器再藏一部分」这种嵌套独立滚动
   * 的形态会低估（低估的是总量，方向是让守卫更容易漏，故不构成假绿的安全风险，
   * 但会削弱守卫强度）。本轮的目标外壳结构（单层 `.device-screen`）不受影响。
   */
  hiddenOverflowPx: number;
  /**
   * 「整页图至少要有多高」的内容高（CSS px）——展开成功后 fullPage 应达到的高度。
   *
   * 为什么不是 `viewportHeightPx + hiddenOverflowPx`
   *
   * 裁决给的判据是「`(clientHeight + hiddenOverflow) × 倍率`」。**当溢出来自内层容器时，
   * 那个 `clientHeight` 必须是该容器自己的可视高，而不是文档的可视高**——
   * 两者不等（外壳场景：`.device-screen` 视口高 844，而文档视口高在 desktop 下是 1000）。
   * 实现时我一度写成 `documentElement.clientHeight + innerOverflowPx`，在 desktop 下
   * 得到 1000 + 1241 = 2241，而真实展开后的内容高只有 2133，于是误报展开失败
   * （被 `guard-nonvacuity` 的 `assertExpanded` 抓到，见 `docs/证据/orchestrator-20261002-001/T01-assets/r3-run2.txt`）。
   * 这不是裁决的问题，是「把两个不同来源的量相加」这个动作本身错。
   *
   * 本字段的算法（逐来源取，不跨来源相加）
   *
   * 每个「滚动来源」各自给出它需要多高：
   *   - 文档：`documentHeightPx`（= 文档可视高 + 文档溢出）；
   *   - 每个内层容器：`scrollHeightPx`（= 容器可视高 + 容器溢出）；
   * 取这些值的最大者。语义是「页面上最高的那段内容有多高」，与滚动发生在哪一层无关。
   * 这是裁决意图（结构无关的判据）的忠实实现，只是把「相加」换成了「逐来源取最大」。
   */
  requiredContentHeightPx: number;
}

/**
 * 测量页面的纵向溢出（生产守卫的唯一输入来源）。
 *
 * 前置: page 已 goto 且内容已渲染稳定；展开之前调用（展开会把溢出消掉，测不到真实值）
 * 后置: 返回文档级与内层容器两种形态的溢出测量，`hiddenOverflowPx` 取两者较大者
 * 异常: 无——测量失败降级为 0，由守卫决定是否跳过（不在这里抛错，避免把测量问题伪装成守卫问题）
 *
 * 为什么必须在中和/展开之前调用：`expandForFullPage` 会把滚动容器放开，
 * 放开之后 `scrollHeight - clientHeight` 归零，「藏了多少」这个信息就永久丢失了。
 */
export async function measureOverflow(page: Page): Promise<OverflowMeasurement> {
  return page.evaluate((): OverflowMeasurement => {
    /** 给元素生成一个够用的描述：标签名 + 可选 id + 可选类名。 */
    const describe = (element: Element): string => {
      const tag = element.tagName.toLowerCase();
      const idPart = element.id === '' ? '' : `#${element.id}`;
      const classPart = element.classList.length === 0 ? '' : `.${[...element.classList].join('.')}`;
      return `${tag}${idPart}${classPart}`;
    };

    const doc = document.documentElement;
    const body = document.body;

    // 文档级：html 与 body 任一溢出都算（两者在不同浏览器/样式下都可能承担滚动）。
    const htmlOverflow = Math.max(0, doc.scrollHeight - doc.clientHeight);
    const bodyOverflow = body === null ? 0 : Math.max(0, body.scrollHeight - body.clientHeight);
    const documentOverflowPx = Math.max(htmlOverflow, bodyOverflow);

    // 内层：所有仍在纵向溢出的滚动容器。排除 documentElement/body（它们已按文档级计入，
    // 重复计入会让 max 失去意义）。
    const scrollContainers: ScrollContainerOverflow[] = [];
    for (const element of Array.from(document.querySelectorAll('*'))) {
      if (element === doc || element === body) continue;
      const computed = getComputedStyle(element);
      if (computed.overflowY !== 'auto' && computed.overflowY !== 'scroll') continue;
      const overflowPx = element.scrollHeight - element.clientHeight;
      if (overflowPx > 0) {
        scrollContainers.push({
          selector: describe(element),
          overflowPx,
          scrollHeightPx: element.scrollHeight,
          clientHeightPx: element.clientHeight,
        });
      }
    }
    const innerOverflowPx = scrollContainers.reduce((max, entry) => Math.max(max, entry.overflowPx), 0);

    // 逐来源取最大：文档给出「文档高」，每个内层容器给出「容器内容高」。
    // 不跨来源相加——见 requiredContentHeightPx 的说明（相加会在 desktop 下误报）。
    const requiredContentHeightPx = scrollContainers.reduce(
      (max, entry) => Math.max(max, entry.scrollHeightPx),
      doc.scrollHeight,
    );

    return {
      viewportHeightPx: doc.clientHeight,
      viewportWidthPx: doc.clientWidth,
      documentHeightPx: doc.scrollHeight,
      documentWidthPx: doc.scrollWidth,
      documentOverflowPx,
      scrollContainers,
      innerOverflowPx,
      hiddenOverflowPx: Math.max(documentOverflowPx, innerOverflowPx),
      requiredContentHeightPx,
    };
  });
}

/**
 * fullPage 高度守卫：整页图必须真的展开到「视口 + 隐藏溢出」那么高。
 *
 * 前置: 已截出 fullPage 图并从产物实读了它的像素高；`measurement` 来自
 *       `measureOverflow(page)`（展开之前测得）
 * 后置: 通过——整页图高覆盖了「最高滚动来源的内容高」（含 2px 容差）
 *
 * @throws Error 整页图高低于 `requiredContentHeightPx × 倍率`（含容差）——说明滚动容器
 *   没被展开，长图只是「外壳首屏」，不可用于逐页版式审计
 *
 * 这是辅助判据，不是主判据
 *
 * 主判据是 `assertNoClippedContent`（结构化表征：页面上还有没有元素在裁内容）。
 * 本条保留为辅助，因为它能发现主判据看不见的一类异常：容器放开了、没有元素在裁切，
 * 但内容高反而变矮（例如祖先折叠）。
 *
 * 它为什么不能单独用（本轮 P1-1' 的实测）
 *
 * 判据形态是「图高 ≥ `requiredContentHeightPx` × 倍率」，而 `requiredContentHeightPx`
 * 取「文档 `scrollHeight` 与各内层容器 `scrollHeight` 的最大值」。当文档本身就比内容高时
 * （`.phone-shell{min-height:100svh}` 把页面撑到视口高，这在 desktop 外壳下是常态），
 * 未展开的陷阱图高恰好等于文档高 ⇒ 直接满足 ⇒ 绿，而内容仍被内层容器滚出可视区。
 * 审查者逐页实测：目标外壳 + desktop 视口下 10 页有 7 页各藏 156px 而本条是绿的。
 * 教训：判据要能区分它想区分的两个状态——「已展开」与「未展开但文档恰好够高」
 * 会落到同一个值上，所以这个比较式本身不成立（无论量选得多准）。
 *
 * 为什么入参是测量结构体而不是两个数字
 *
 * 更早一轮（P1-1）：生产调用点曾喂文档级溢出，而外壳结构下溢出在内层容器，
 * 于是 1184px 被藏住而守卫毫无反应。让守卫只接受 `OverflowMeasurement`（由
 * `measureOverflow` 产出、同时含两种形态），就从签名上堵住了「调用方自己挑一个量」。
 */
export function assertFullPageExpanded(params: {
  /** fullPage 图的实际像素高（从 PNG 产物实读）。 */
  fullPngHeightPx: number;
  /** 展开之前测得的溢出（必须来自 `measureOverflow`）。 */
  measurement: OverflowMeasurement;
  /** 设备像素比。 */
  deviceScaleFactor: number;
  /** 出错信息里的定位描述（页名 + 视口）。 */
  context: string;
}): void {
  const { measurement } = params;
  // 复用同一个量上的同一个容差常量（P2-E）：`capture()` 与 `manifest` 汇总都在比
  // 「PNG 像素高 vs CSS 内容高 × 倍率」，本条也是——三处必须共用 PNG_HEIGHT_TOLERANCE_PX。
  // （`CSS_LAYOUT_TOLERANCE_PX` 是另一个量：元素自身的 scrollHeight−clientHeight，不涉及 PNG 像素，
  //   故不用于这里。）
  const tolerancePx = PNG_HEIGHT_TOLERANCE_PX * params.deviceScaleFactor;
  const expectedMinHeightPx = measurement.requiredContentHeightPx * params.deviceScaleFactor;
  if (params.fullPngHeightPx >= expectedMinHeightPx - tolerancePx) return;

  const where =
    measurement.scrollContainers.length > 0
      ? `内部滚动容器：${measurement.scrollContainers
          .map((entry) => `${entry.selector}(${String(entry.overflowPx)}px)`)
          .join('、')}`
      : '（无内部滚动容器，溢出在文档级）';

  throw new Error(
    `${params.context} 的整页图只有 ${String(params.fullPngHeightPx)}px，低于「最高滚动来源的内容高」` +
      `${String(measurement.requiredContentHeightPx)}px × ${String(params.deviceScaleFactor)} = ` +
      `${String(expectedMinHeightPx)}px（容差 ${String(tolerancePx)}px）。` +
      `展开前的溢出情况：${where}。fullPage 未真正展开内容，长图不可用。` +
      '注意这是**辅助**判据的报错——主判据（无元素裁切内容）若同时通过，说明异常出在内容高而非裁切上。',
  );
}

/**
 * 中和 fixed 并把主滚动容器 + 其祖先链展开为「内容全高」。
 *
 * 前置: page 已 goto、内容断言已通过（此时内容高度已稳定）
 * 后置: 返回恢复句柄；调用方必须在截图后立刻 `restore()`
 * 异常: 定位失败时降级为文档滚动（并由 fullPage 高度守卫判定是否真的展开了）
 *
 * 为什么展开祖先链而不只展开滚动容器：设备外壳落地后（T02）结构会是
 * `body > .device-stage > .device(高 844) > .device-screen(overflow-y:auto)`。
 * 只把 `.device-screen` 放开，它的内容仍会被固定 844px 高的 `.device` 裁掉——
 * 那样展开等于没做，而 fullPage 图看起来"成功"了。因此从滚动容器一路向上
 * 到 `documentElement` 都放开布局约束（`height: auto; max-height: none; overflow: visible`），
 * 让内容真的把文档撑高。
 *
 * 只改布局约束，不改任何视觉参数。恢复用「记录原始内联值再写回」：
 * 写回空串会退回样式表值，这正是「回到原状」的语义。
 *
 * `measurement` 必须由调用方用 `measureOverflow(page)` 在本函数之前取得：
 * 展开会把溢出消掉，之后再测就测不到「原本藏了多少」。
 */
export async function expandForFullPage(
  page: Page,
  measurement: OverflowMeasurement,
): Promise<{
  result: NeutraliseResult;
  /** 把中和样式与展开过的内联值写回展开前状态。 */
  restore: () => Promise<void>;
  /**
   * 断言确实已恢复到展开前的内联值。
   *
   * 为什么由本函数提供而不是单独导出一个 `expectRestored(page, result)`：
   * 正确的判据是「当前内联值 == 记录的原值」，而原值存在 `expandForFullPage` 的闭包里。
   * 若让调用方自己传 `result`，`result` 里并不含原值——那种签名会诱导实现退化成
   * 「内联值应为空」的错误判据（对本来就有内联样式的元素会误报）。
   */
  assertRestored: () => Promise<void>;
  /**
   * 断言展开确实生效——在 DOM 层判，与「读 PNG 像素高」是两条独立通道。
   *
   * 判据分主辅两条（口径与实现一致，不复制旧式）：
   *   1. 主判据：`assertNoClippedContent` —— 页面上不再有元素在裁切内容
   *      （结构化表征，不依赖任何数值比较）；
   *   2. 辅助判据：展开后内容高 ≥ 展开前测得的 `requiredContentHeightPx`（含容差）。
   *
   * 这里不是「内容高 ≥ 视口高 + 展开前隐藏溢出」——那个相加式已被否决
   * （跨来源相加会在 desktop 外壳下误报：1000 + 1184 = 2184 > 真实内容高 2133）。
   *
   * 为什么两条通道都要：PNG 那条验的是「产物对不对」（端到端，但失败信息离病因远），
   * 本通道验的是「DOM 展开对不对」（更早、更近，但看不见截图环节的意外）。
   * P1-1 的教训是「守卫必须被喂对的量」——因此两条通道共用同一个 measurement 对象，
   * 不存在「各算各的、其中一个算错」的可能。
   */
  assertExpanded: () => Promise<void>;
}> {
  const expanded = await page.evaluate(
    ({ css, id, fixedSelectors, injectFixed, expand, tolerancePx }: {
      css: string;
      id: string;
      fixedSelectors: readonly string[];
      injectFixed: boolean;
      expand: boolean;
      tolerancePx: number;
    }) => {
      /** 给元素生成一个够用的描述：标签名 + 可选 id + 可选类名。 */
      const describe = (element: Element): string => {
        const tag = element.tagName.toLowerCase();
        const idPart = element.id === '' ? '' : `#${element.id}`;
        const classPart = element.classList.length === 0 ? '' : `.${[...element.classList].join('.')}`;
        return `${tag}${idPart}${classPart}`;
      };

      /**
       * 展开/恢复与 sidecar 共用的目标标识。
       *
       * `documentElement` 与 `body` 走具名特例：`describe` 会给出 `html`/`body`，
       * 而恢复路径按具名串解析——两处口径必须一致，故统一由本函数产出。
       */
      const targetOf = (element: Element): string => {
        if (element === document.documentElement) return 'documentElement';
        if (element === document.body) return 'body';
        return describe(element);
      };

      const style = document.createElement('style');
      style.id = id;
      style.textContent = css;
      // 消融态（injectFixed=false）时只注入空样式表：样式节点仍在（恢复路径不变），
      // 但不含中和规则——于是 assertNoFixedAtCaptureTime 应当失败。
      if (!injectFixed) style.textContent = '/* 消融态：未注入 fixed 中和规则 */';
      document.head.append(style);

      const hitFixed = fixedSelectors.filter((selector) => document.querySelector(selector) !== null);
      /** 记录并放开一个元素的布局约束。 */
      const loosen = (element: HTMLElement, target: string, backups: LayoutBackup[]): void => {
        backups.push({
          target,
          height: element.style.height,
          maxHeight: element.style.maxHeight,
          overflowY: element.style.overflowY,
        });
        element.style.height = 'auto';
        element.style.maxHeight = 'none';
        element.style.overflowY = 'visible';
      };

      /**
       * 找出所有纵向可滚、且内容确实溢出的容器。
       *
       * 为什么返回全部而不是只挑一个（P2-3 升级为 P1 的修法）：
       * 早先的实现用 `reduce` 取「面积最大」的那一个。一旦页面上有两个独立滚动容器
       * 且面积相同（真实外壳 `.device-screen` 与测试构造的模拟外壳都是 390×844），
       * 严格大于的比较会把平局判给文档序在前的那个（外层），而内层容器不是它的后代、
       * 不在被展开的祖先链上，于是仍裁着内容。T02 落地后这正是实际发生的形态
       * （真实外壳 + `guard-nonvacuity` 的模拟外壳叠加，内层仍裁 1184px）。
       * 改成「全部放开」后不再存在靠文档序决胜的选择，也不再有面积参与判据。
       *
       * 容差用 `tolerancePx`（= `CSS_LAYOUT_TOLERANCE_PX`）而不是裸 `+1`：与
       * `findClippedElements` 的「是否被裁」用同一个口径，避免出现
       * 「恰好 2px 溢出：不算被裁，却算可滚动容器」这种两处判据互相矛盾的情形（P2-E'）。
       */
      const scrollables = Array.from(document.querySelectorAll('*')).filter((element) => {
        const computed = getComputedStyle(element);
        const scrollable = computed.overflowY === 'auto' || computed.overflowY === 'scroll';
        return scrollable && element.scrollHeight > element.clientHeight + tolerancePx;
      });

      const backups: LayoutBackup[] = [];
      const ancestors: string[] = [];

      // 消融态（expand=false）只跳过「展开」这一步，fixed 中和照常注入——
      // 于是高度守卫是唯一可能变红的断言，两个机制各自独立可消融。
      if (expand) {
        if (scrollables.length === 0) {
          // 文档滚动：放开 html 与 body（当前移动端实现的真实形态）。
          loosen(document.documentElement, 'documentElement', backups);
          if (document.body !== null) loosen(document.body, 'body', backups);
        } else {
          // 待放开集合 = 每个滚动容器自身 ∪ 它的整条祖先链（一路到 documentElement）。
          // 用 Set 去重：多个容器的祖先链会大量重叠（真实外壳与模拟外壳共享 #root 以上）。
          // 之所以连祖先一起放开：固定高度的祖先（`.device` 的 height:844px）会把内容重新裁掉。
          const toLoosen = new Set<Element>();
          for (const container of scrollables) {
            let cursor: Element | null = container;
            while (cursor !== null) {
              toLoosen.add(cursor);
              cursor = cursor.parentElement;
            }
          }
          if (document.body !== null) toLoosen.add(document.body);

          const containerSet = new Set<Element>(scrollables);
          for (const element of toLoosen) {
            const target = targetOf(element);
            if (element instanceof HTMLElement) {
              loosen(element, target, backups);
              // 「祖先」= 待放开集合里不是滚动容器本身的那些（与字段语义一致）。
              if (!containerSet.has(element)) ancestors.push(target);
            }
          }
        }
      }

      // 展开后量内容高：这是 fullPage 图应有的高度，也是高度守卫的判据来源。
      // 未展开时按文档高算——那正是「只截到滚动容器首屏」的高度。
      const bodyHeight = document.body === null ? 0 : document.body.scrollHeight;
      const contentHeightPx = Math.max(
        document.documentElement.scrollHeight,
        bodyHeight,
        document.documentElement.clientHeight,
      );

      return {
        fixedNeutralised: hitFixed.length > 0,
        neutralisedSelectors: hitFixed,
        // 多个容器时用顿号连接（字段仍是字符串，便于 sidecar 阅读与人工核对）；
        // 无容器时表示走文档滚动那条分支。
        expandedScrollContainer:
          scrollables.length === 0 ? 'documentElement' : scrollables.map((entry) => describe(entry)).join('、'),
        expandedAncestors: ancestors,
        contentHeightPx,
        backups,
      };
    },
    {
      css: NEUTRALISE_CSS,
      id: STYLE_ELEMENT_ID,
      fixedSelectors: FIXED_SELECTORS,
      injectFixed: FIXED_NEUTRALISATION_ENABLED,
      expand: EXPANSION_ENABLED,
      tolerancePx: CSS_LAYOUT_TOLERANCE_PX,
    },
  );

  const { backups, ...result } = expanded;

  const restore = async (): Promise<void> => {
    await page.evaluate(
      ({ id, saved }: { id: string; saved: LayoutBackup[] }) => {
        document.getElementById(id)?.remove();

        /** 按描述取回元素；`documentElement` / `body` 走特例。 */
        const resolveTarget = (target: string): HTMLElement | null => {
          if (target === 'documentElement') return document.documentElement;
          if (target === 'body') return document.body;
          return document.querySelector<HTMLElement>(target);
        };

        for (const backup of saved) {
          const element = resolveTarget(backup.target);
          if (element === null) continue;
          element.style.height = backup.height;
          element.style.maxHeight = backup.maxHeight;
          element.style.overflowY = backup.overflowY;
        }
      },
      { id: STYLE_ELEMENT_ID, saved: backups },
    );
  };

  /**
   * 断言已恢复到展开前的内联值（不是「内联值为空」）。
   *
   * 为什么不能假定「恢复后内联值为空」：被展开的元素可能本来就有内联样式
   * （设备外壳的 `.device` 自带 `height:844px`，那正是它需要被展开的原因）。
   * 对这类元素，「恢复」意味着写回 `844px` 而不是清空——用「应为空」去判会误报
   * 未恢复，把一个正确的恢复判成失败。故判据是「当前内联值 == 记录的原值」。
   *
   * @throws Error 存在残留（用例失败）——不静默，因为残留会污染同页后续断言与 sidecar
   */
  const assertRestored = async (): Promise<void> => {
    const residue = await page.evaluate(
      ({ id, saved }: { id: string; saved: LayoutBackup[] }) => {
        const styleLeft = document.getElementById(id) !== null;
        const resolveTarget = (target: string): HTMLElement | null => {
          if (target === 'documentElement') return document.documentElement;
          if (target === 'body') return document.body;
          return document.querySelector<HTMLElement>(target);
        };

        const mismatched: string[] = [];
        for (const backup of saved) {
          const element = resolveTarget(backup.target);
          if (element === null) {
            mismatched.push(`${backup.target} 已不在文档中，无法确认恢复`);
            continue;
          }
          for (const [property, actual, expected] of [
            ['height', element.style.height, backup.height],
            ['max-height', element.style.maxHeight, backup.maxHeight],
            ['overflow-y', element.style.overflowY, backup.overflowY],
          ] as const) {
            if (actual !== expected) {
              mismatched.push(
                `${backup.target} 的 ${property} 是 "${actual}"，展开前是 "${expected}"（未恢复）`,
              );
            }
          }
        }
        return { styleLeft, mismatched };
      },
      { id: STYLE_ELEMENT_ID, saved: backups },
    );

    if (residue.styleLeft) {
      throw new Error('中和样式未移除：页面残留 __shots_neutralise__，会污染同页后续断言与 sidecar');
    }
    if (residue.mismatched.length > 0) {
      throw new Error(`展开样式未恢复，页面未回到原状：\n  ${residue.mismatched.join('\n  ')}`);
    }
  };

  /**
   * DOM 层断言：展开后页面上不应再有元素裁切内容。
   *
   * 主判据是结构化表征，不是数值比较（本轮 P1-1' 的修法）
   *
   * 上一版判 `contentHeightPx >= requiredContentHeightPx`，而短内容下 `required` 会塌成
   * 文档自身高（实测：`.phone-shell{min-height:100svh}` 把页面撑到视口高，
   * 于是 `required == 文档高` 成了常态），使「未展开」的图高恰好等于需要值 ⇒ 守卫绿。
   * 该比较无法区分它想区分的两个状态。
   *
   * 现在先问一个不需要阈值的问题：「此刻还有元素在裁它的内容吗？」
   *   - `findClippedElements` 扫 `overflow-y ∈ {auto,scroll,hidden,clip}`，
   *     排除刻意截断（ellipsis / line-clamp / clip-path）；
   *   - 有任何一条非刻意的裁切 ⇒ 展开没生效 ⇒ 抛错。
   * 这个表征与「滚动发生在哪一层」无关，也不需要跨来源比较，因此天然结构无关。
   *
   * 高度比较降为辅助
   *
   * 保留「内容高 ≥ 最高滚动来源的内容高」作为第二条判据：它能发现「容器放开了但
   * 内容高反而变矮」这类异常（例如祖先折叠）。但它不再单独决定通过——
   * 数值比较留着当辅助，正是因为它单独用会被同值状态骗过。
   *
   * 注意：这里不再用 `measurement.hiddenOverflowPx <= 0` 开闸整段跳过。
   * 那个「以视口为基准」的开闸条件正是本轮盲区的放行者：短页 `hiddenOverflowPx` 可能为 0
   * 或很小，于是断言被跳过，而实际上有元素在裁切。现在无论溢出量多少都扫一遍。
   */
  const assertExpanded = async (): Promise<void> => {
    const clipped = await findClippedElements(page);
    assertNoClippedContent(clipped, '展开后（DOM 层）');

    // 辅助判据：内容高不得低于展开前的最高滚动来源。
    const contentHeightPx = await page.evaluate(() => {
      const doc = document.documentElement;
      const body = document.body;
      const bodyHeight = body === null ? 0 : body.scrollHeight;
      return Math.max(doc.scrollHeight, bodyHeight);
    });

    const requiredMinPx = measurement.requiredContentHeightPx;
    // 复用与尺寸断言同一个容差口径（P2-E）：两条判据在同一条量上不得各写一个容差。
    if (contentHeightPx >= requiredMinPx - CSS_LAYOUT_TOLERANCE_PX) return;

    throw new Error(
      `展开后内容高 ${String(contentHeightPx)}px 低于「最高滚动来源的内容高」` +
        `${String(requiredMinPx)}px（容差 ${String(CSS_LAYOUT_TOLERANCE_PX)}px）：展开未生效，` +
        '长图只会截到滚动容器的首屏（这是辅助判据报的错；主判据「无元素裁切内容」已通过，' +
        '说明异常可能出在内容高而非裁切上）。',
    );
  };

  return { result, restore, assertRestored, assertExpanded };
}

/**
 * 断言截图时刻页面上没有元素在裁切内容。
 *
 * 前置: 已中和 fixed 并展开滚动容器（fullPage 截图之前调用）
 * 后置: 通过——没有非刻意截断的元素
 *
 * @throws Error 仍有元素在裁切内容——fullPage 图会丢掉被裁掉的部分
 *
 * 为什么在「展开后」已有一条断言还要再加一条：两者测的是不同时刻。
 * `assertExpanded` 在展开后立刻判（那时容器刚被放开）；本条在截图前判，
 * 覆盖「展开看起来生效了、但截图那一刻又被别的因素裁回去」的情形。
 * 两者共用 `findClippedElements` + `assertNoClippedContent` 同一份实现，
 * 因此不存在「同一量两条口径」。
 */
export async function assertNothingClippedAtCaptureTime(page: Page): Promise<void> {
  const clipped = await findClippedElements(page);
  assertNoClippedContent(clipped, 'fullPage 截图');
}