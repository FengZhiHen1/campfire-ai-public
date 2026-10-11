/**
 * 模块: scripts/check-contract-css
 * 职责: 构建后断言——对话面契约样式表真的进了产物 CSS，且「契约里靠源序决胜的同特异性规则对」
 *       在产物里保持契约的先后（顺序守卫），元素级/复合选择器规则没有被漏移植
 * 数据来源:
 *   - src/features/consult/view/consultComponents.css: MUST — 被断言的契约类名清单来源
 *   - docs/design/components.html: MUST — 顺序守卫与规则级断言的**契约源**（真源，只读）
 *   - docs/design/pages/{对话页,应急表单页}.md: MUST — 这些类名承载的视觉契约
 * 边界:
 *   - 依赖: node:fs/promises、node:path、node:url（Node 内置，不引入第三方）
 *   - 被依赖: apps/web 的 build 脚本（vite build 之后）
 * 禁止行为:
 *   - 禁止在产物缺失或读不到 CSS 时静默通过（看不清就失败，不假装成功）
 *   - 禁止只查契约类名而不查通道 canary（读不到文件时两边都 0 命中，会误判成「表没接线」）
 *   - 禁止留下「永远不会失败的检查」：每道闸门都必须在 `--self-test` 的负对照下变红
 *
 * 为什么需要它：类名表是全局类名（不是 CSS Modules），组件里漏写 import 时构建照样成功、
 * 单测照样全绿（vitest 默认 css: false，组件用例只断言 class 字符串），
 * 只有产物里到底有没有这些规则能发现「接线遗漏」。vitest 看不到产物，故断言放在构建后。
 *
 * ── 2026-10-03 加固（T05）────────────────────────────────────────────────
 *
 * 改前的三道检查**只断言 16 个对话面类名「在产物里出现过」**（正则 `.name(?![\w-])`），
 * 不查具体声明、不查契约全集、也不查源序。它**结构性地拦不住**三类真实缺陷：
 *
 *   1. **元素级规则缺失**：`textarea { … }` 8 条声明一条都没进产物，而
 *      `button,input,textarea,select{font:inherit}` 让 `textarea` 这个词命中 ⇒ 旧检查全绿；
 *   2. **复合选择器缺失**：`button.tag { min-height:44px; min-width:44px }` 从未移植，
 *      而 `.tag{…}` 存在 ⇒ 旧检查只查 `tag`，命中即通过；
 *   3. **顺序错误**：`main.tsx` 的 import 顺序让 `consultComponents.css` 排在
 *      `components.css` 之前，于是 `.question-card{padding:0}` 落在 `.tile{padding:20px}`
 *      之前 ⇒ 同特异性、后写者胜 ⇒ 提问卡四周多出 20px 内缩。旧检查不比较偏移，全绿。
 *
 * 新增四道**规则级**闸门（不是类名级），并在 `--self-test` 里对每道都给出会变红的负对照：
 *   A. 元素级规则声明清单（`textarea` 的 8 条 + 4 条伪类/属性态，逐条与契约比声明）
 *   B. 复合选择器规则存在性（`button.tag` 的尺寸声明）
 *   C. 源序守卫（契约里靠源序决胜的规则对，在产物里必须保持同一先后）
 *   D. 契约里「产品真渲染」的选择器必须在产物里出现（A1 净候选清单的机械形态）
 *
 * `--self-test` 的判据是**双向**的：每个变异体既要被新闸门抓到，同一条变异体喂给
 * 旧逻辑（`legacyGate`）时又必须通过——否则「加固」这件事没有被证明有必要。
 */

import { readdir, readFile } from 'node:fs/promises';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(scriptDir, '..');
const repoRoot = resolve(webRoot, '..', '..');

/** 对话面契约类名：每个都对应页面设计里的一处组件契约。 */
const CONSULT_CLASSES = [
  'question-card',
  'question-option',
  'ac-section',
  'ac-head',
  'ac-source',
  'selection',
  'progress-track',
  'bubble-user',
  'msg-doc',
  'citation-block',
  'skill-chip',
  'candidate-toast',
  'chat-progress',
  'expired',
  'reasoning-row',
  'tool-row',
];

/**
 * 通道 canary：这些类名由 T10 的 components.css 提供，与本次断言的表无关。
 * 它们必须命中，否则说明「读产物 CSS」这条通道本身失效（路径错、产物没生成）。
 */
const CANARY_CLASSES = ['btn-primary', 'tile', 'subpage-head', 'list-row', 'status', 'empty-state', 'error-card', 'skeleton'];

/**
 * 闸门 A：元素级规则的契约声明清单。
 *
 * `contractLines` 是 `docs/design/components.html` 的行号，**只作可追溯性记录**；
 * 断言比的是 `declarations` 与服务产物里该选择器规则的声明（逐条比对，不看行号）。
 * 取值来源：契约 193–197 行（`textarea` 与四条状态规则）。
 *
 * 行号在 2026-10-11 的契约重排后订正过一次（原记录指向 133–137）；它不影响判定，
 * 但指错位置会让后来者按行号找不到规则，因此与契约同批维护。
 */
const ELEMENT_RULE_CONTRACTS = [
  {
    selector: 'textarea',
    contractLines: [193],
    declarations: [
      ['width', '100%'],
      ['min-height', '120px'],
      ['padding', 'var(--space-3) var(--space-4)'],
      ['border', '1px solid var(--border)'],
      ['border-radius', 'var(--radius-sm)'],
      ['background', 'var(--surface)'],
      ['color', 'var(--fg)'],
      ['font', 'inherit'],
      ['resize', 'vertical'],
    ],
  },
  { selector: 'textarea::placeholder', contractLines: [194], declarations: [['color', 'var(--muted)'], ['opacity', '1']] },
  {
    selector: 'textarea:focus',
    contractLines: [195],
    declarations: [['outline', 'none'], ['border-color', 'var(--accent)'], ['box-shadow', 'var(--focus-ring)']],
  },
  { selector: 'textarea[aria-invalid="true"]', contractLines: [196], declarations: [['border-color', 'var(--danger)']] },
  { selector: 'textarea:read-only', contractLines: [197], declarations: [['background', 'var(--bg)']] },
];

/**
 * 闸门 B：复合选择器 / 伪类态规则的契约声明清单。
 *
 * `button.tag` 的类名 `tag` 在产物里存在（有基础规则），缺的是**尺寸规则**——
 * 这正是「只 grep `.tag` 会漏掉」的情形（契约 177 行）。
 * `.text-button:disabled` 同理：`.text-button` 在产物里存在，缺的是**禁用态**那一条；
 * 它此前整条不在产物里（实测改前 `disabled` 按钮的计算样式仍是 `opacity: 1`）。
 */
const COMPOUND_RULE_CONTRACTS = [
  {
    selector: 'button.tag',
    contractLines: [177],
    declarations: [['min-height', '44px'], ['min-width', '44px']],
  },
  { selector: '.sp-tag', contractLines: [223], declarations: [['flex', 'none']] },
  {
    selector: '.text-button:disabled',
    contractLines: [190],
    declarations: [['opacity', '0.5'], ['cursor', 'not-allowed']],
  },
];

/**
 * 闸门 C：源序守卫的规则对。
 *
 * 每条 `[前, 后]` 表示：在**契约**里 `前` 的规则先于 `后` 的规则出现。
 * 契约里两者特异性相同（都是单类）且都设 `property`，因此**源序决定胜负**——
 * 产物的先后必须与契约一致，否则可见呈现会翻转。
 *
 * 已登记的对局（每一条都是在同一元素上真共存的两个类，见 T05.md 第三节）：
 *   - `tile` vs `question-card`：`QuestionCard.tsx:45`/`:56` 的 `className="tile question-card"`，
 *     `padding`（`--space-5` = 20px vs `0`）——本包修复的那一例；
 *   - `candidate-toast` vs `chat-candidate`：`ChatWorkspace.tsx:227` 的
 *     `className="candidate-toast chat-candidate"`，`border` / `border-radius` / `padding` / `background`；
 *   - `text-button` vs `question-free-toggle`：`QuestionCard.tsx:131` 的
 *     `className="text-button question-free-toggle"`，`padding` / `border` / `min-height` / `font-size`。
 *
 * **为什么不登记 `tag` vs `meta`**（虽然 `LibraryPage.tsx:127`、`ProfilePage.tsx:525` 等确有
 * `className="tag meta"`）：
 *   1. **退化对局**：两条规则对 `color` 与 `font-size` 声明的值**逐字相同**
 *      （都是 `var(--meta)` / `var(--text-xs)`）⇒ 谁胜出都不改变计算样式，**不可观测**；
 *   2. **同文件内序**：两者都在 `components.css` 里（`.meta` 在 `.tag` 之前，与契约里
 *      `.meta`(173) / `.tag`(174) 的先后一致），导入顺序改不动它——按 `main.tsx` 的
 *      import 调整去修它是错误归因。
 *   两点都由 `assertOrderContractsAreLoadBearing()` 机械校验：若将来有人把某条登记对上
 *   两条规则的值改成相同，或把 `property` 写成本就不冲突的属性，构建会失败而不是静默空转。
 */
const ORDER_CONTRACTS = [
  { before: '.tile', after: '.question-card', property: 'padding', contractLines: [170, 314], note: '提问卡四周多出 20px 内缩' },
  {
    before: '.candidate-toast',
    after: '.chat-candidate',
    property: 'border-radius',
    contractLines: [372, 373],
    note: '候选提示的圆角/边框/内距与契约不同',
  },
  {
    before: '.text-button',
    after: '.question-free-toggle',
    property: 'padding',
    contractLines: [189, 330],
    note: '「用自己的话回答」的内距与边框被文字按钮的 0 值压掉',
  },
  {
    /**
     * 元素级伪类/属性态的一对，形态与上面三对（两个类同时挂在同一元素上）不同：
     * 两端都在同一个 `<textarea>` 元素上，特异性都是 (0,1,1)，都设 `border-color`，
     * 值不同（`--accent` vs `--danger`）⇒ 源序决定「聚焦且校验失败」时显示哪一个。
     * 契约里 `:focus`（components.html:195）在 `[aria-invalid]`（:196）之前，
     * 故危险色胜出——这是有意的：校验失败比聚焦更该被看见。
     * 消费点在 `ProfilePage.tsx:681` 与 `MemoryPage.tsx:216`（两处 `aria-invalid` 真渲染）。
     *
     * 为什么它此前未被守卫：加固时只枚举了「两个类同挂一元素」的形态，而这一对一个类名都没有
     * ⇒ 交换它们对任何类名级断言都不可见。它是顺序外溢面上最后一个未守卫的缺口
     * （T05 审查者发现；当前产物顺序与契约一致，故不是现存缺陷）。
     */
    before: 'textarea:focus',
    after: 'textarea[aria-invalid="true"]',
    property: 'border-color',
    contractLines: [195, 196],
    note: '聚焦且校验失败时，危险边框色被聚焦色压掉（校验失败不再可见）',
  },
];

/** 递归收集目录下的 CSS 文件路径。 */
async function collectCss(dir) {
  const entries = await readdir(dir, { withFileTypes: true }).catch(() => []);
  const files = [];
  for (const entry of entries) {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await collectCss(full)));
    else if (entry.name.endsWith('.css')) files.push(full);
  }
  return files;
}

/** 类名是否作为完整类名出现（不把 .selection-x 当成 .selection）。 */
function hasClass(css, name) {
  return new RegExp(`\\.${name}(?![\\w-])`).test(css);
}

/** 去掉块注释（不影响选择器/声明的位置语义；偏移仍按原文算）。 */
function stripComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, (match) => ' '.repeat(match.length));
}

/**
 * 极简 CSS 扫描：返回按源码顺序的顶层规则 `{ selector, body, offset }`。
 *
 * 能力边界：只做括号配平，不解释 `:is()/:where()`，不展开嵌套；`@media`/`@supports`
 * 块内的规则会被收进来并带 `at` 标记（闸门 C 只比较 `at === null` 的顶层规则——
 * 媒体查询里的规则只在条件命中时参与层叠，与顶层规则比序位是拿两个上下文对局）。
 */
function scanRules(css) {
  const src = stripComments(css);
  const rules = [];
  const walk = (text, base, at) => {
    let i = 0;
    while (i < text.length) {
      const ch = text[i];
      if (ch === '}' || ch === ';' || /\s/.test(ch)) {
        i += 1;
        continue;
      }
      const brace = text.indexOf('{', i);
      if (brace === -1) return;
      const semi = text.indexOf(';', i);
      if (semi !== -1 && semi < brace) {
        i = semi + 1;
        continue;
      }
      const prelude = text.slice(i, brace).trim();
      let depth = 0;
      let j = brace;
      for (; j < text.length; j += 1) {
        if (text[j] === '{') depth += 1;
        else if (text[j] === '}') {
          depth -= 1;
          if (depth === 0) break;
        }
      }
      const body = text.slice(brace + 1, j);
      if (prelude.startsWith('@')) {
        const name = prelude.split(/\s/)[0];
        if (name !== '@keyframes' && !name.startsWith('@-webkit-keyframes')) walk(body, base + brace + 1, prelude);
      } else {
        rules.push({ selector: prelude, body, offset: base + i, at });
      }
      i = j + 1;
    }
  };
  walk(src, 0, null);
  return rules;
}

/** 把选择器文本按顶层 `,` 拆开。 */
function splitSelectors(selector) {
  const parts = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < selector.length; i += 1) {
    const c = selector[i];
    if (c === '(' || c === '[') depth += 1;
    else if (c === ')' || c === ']') depth -= 1;
    else if (c === ',' && depth === 0) {
      parts.push(selector.slice(start, i).trim());
      start = i + 1;
    }
  }
  parts.push(selector.slice(start).trim());
  return parts.filter((p) => p !== '');
}

/** 归一闪缩与引号，便于把两端的选择器文本对齐（产物被压缩器去过引号与空白）。 */
const normSelector = (s) => s.replace(/\s+/g, ' ').replace(/["']/g, '').trim();

/**
 * 归一**声明值**，用于与契约逐条比对。
 *
 * 为什么不能直接字符串相等：压缩器会改写数值的书写形式，实测 `opacity: 0.5` 进产物后是
 * `opacity: .5`。只归一「数字的字面写法」（前导 0、尾随 0），**不归一单位、不归一函数名、
 * 不归一颜色**——那些差异是真差异，必须报出来。
 *   - `0.5` / `.5` / `0.50` ⇒ `0.5`
 *   - `1px solid transparent` 里的 `0px` **不动**（0 与 0px 在 CSS 里语义等价，但本闸门
 *     只做字面归一，避免把「单位写错」也顺手放过；目前没有断言依赖这一条）
 */
function normValue(value) {
  return value
    .replace(/\s+/g, ' ')
    .replace(/["']/g, '')
    .trim()
    .replace(/(^|[\s,(])\.(\d)/g, '$10.$2')
    .replace(/(\d)\.0+(?=[^\d]|$)/g, '$1')
    .replace(/(\.\d*?)0+(?=[^\d]|$)/g, '$1')
    .replace(/(\.\d*?)0+(?=[^\d]|$)/g, '$1');
}

/** 声明表：`prop -> value`（同属性取最后一条，与 CSS 语义一致）。 */
function declarationsOf(body) {
  const out = new Map();
  for (const chunk of body.split(';')) {
    const idx = chunk.indexOf(':');
    if (idx === -1) continue;
    const prop = chunk.slice(0, idx).trim().toLowerCase();
    const value = chunk.slice(idx + 1).trim();
    if (prop !== '') out.set(prop, value);
  }
  return out;
}

/** 取某个选择器的顶层规则集合（按源序）。 */
const rulesFor = (rules, selector) =>
  rules.filter((rule) => rule.at === null && splitSelectors(rule.selector).some((s) => normSelector(s) === normSelector(selector)));

/**
 * 闸门 A/B：断言选择器的规则存在，且契约声明的每条属性都在（值逐条相等）。
 *
 * 返回 `{ code, selector, detail }[]`。
 */
function checkRuleContracts(rules, contracts, code) {
  const violations = [];
  for (const contract of contracts) {
    const hits = rulesFor(rules, contract.selector);
    if (hits.length === 0) {
      violations.push({
        code,
        selector: contract.selector,
        detail: `产物里找不到该选择器的顶层规则（契约 components.html:${contract.contractLines.join(',')}）`,
      });
      continue;
    }
    const merged = new Map();
    for (const rule of hits) for (const [prop, value] of declarationsOf(rule.body)) merged.set(prop, value);
    const missing = [];
    for (const [prop, expected] of contract.declarations) {
      const actual = merged.get(prop);
      if (actual === undefined) missing.push(`${prop} 缺失`);
      else if (normValue(actual) !== normValue(expected)) {
        missing.push(`${prop}: 契约 ${expected} / 产物 ${actual}`);
      }
    }
    if (missing.length > 0) {
      violations.push({
        code,
        selector: contract.selector,
        detail: `声明与契约不一致（契约 components.html:${contract.contractLines.join(',')}）——${missing.join('；')}`,
      });
    }
  }
  return violations;
}

/** 闸门 C：源序守卫。比较两端「顶层规则块」的偏移（同文件内与跨文件都可比）。 */
function checkOrder(rules, contracts, code) {
  const violations = [];
  for (const contract of contracts) {
    const before = rulesFor(rules, contract.before);
    const after = rulesFor(rules, contract.after);
    if (before.length === 0 || after.length === 0) {
      violations.push({
        code,
        selector: `${contract.before} / ${contract.after}`,
        detail: `无法比较源序：${before.length === 0 ? `${contract.before} 在产物里没有顶层规则` : ''}${after.length === 0 ? `${contract.after} 在产物里没有顶层规则` : ''}`,
      });
      continue;
    }
    const beforeOffset = before[before.length - 1].offset;
    const afterOffset = after[after.length - 1].offset;
    if (!(beforeOffset < afterOffset)) {
      violations.push({
        code,
        selector: `${contract.before} / ${contract.after}`,
        detail:
          `源序与契约相反：契约里 ${contract.before}（components.html:${String(contract.contractLines[0])}）在前、` +
          `${contract.after}（:${String(contract.contractLines[1])}）在后；产物里偏移 ${String(beforeOffset)} → ${String(afterOffset)}。` +
          `两者特异性相同且都设 ${contract.property}，源序决定胜负 ⇒ ${contract.note}`,
      });
    }
  }
  return violations;
}

/** 闸门 D：契约里「产品真渲染」的选择器必须在产物里出现（A1 净候选的机械形态）。 */
function checkRenderedSelectors(rules, selectors, code) {
  const violations = [];
  for (const selector of selectors) {
    if (rulesFor(rules, selector).length === 0) {
      violations.push({ code, selector, detail: '该选择器在产物里没有顶层规则（契约与实现缺口）' });
    }
  }
  return violations;
}

/**
 * 闸门 C 的**前提校验**：登记的对局必须真的「靠源序决胜」。
 *
 * 这是防「永远不会失败的检查」的那道闸门（AGENTS.md 的 Behavioral Guidelines 明令禁止）。
 * 一条 ORDER_CONTRACT 只有在下面两条**都**成立时才承重：
 *   1. 两端在契约里都声明了 `property`；
 *   2. 两端的值**不相同**——值相同时谁胜出都不改变计算样式，该判据不可观测。
 *
 * 本包就是靠这条把 `tag` vs `meta` 从清单里剔除的：两条规则对 `color`/`font-size`
 * 声明的值逐字相同（`var(--meta)` / `var(--text-xs)`），且同处 `components.css`，
 * 导入顺序改不动它。**留着它会让守卫在一个不可观测的对局上空转**。
 *
 * 另校验两端的契约源序确实与声明的 `before`/`after` 一致——否则判据本身写反了。
 */
function assertOrderContractsAreLoadBearing(contractRules) {
  const problems = [];
  for (const contract of ORDER_CONTRACTS) {
    const before = rulesFor(contractRules, contract.before);
    const after = rulesFor(contractRules, contract.after);
    if (before.length === 0 || after.length === 0) {
      problems.push(`${contract.before} / ${contract.after}：契约里缺一端的顶层规则，无法校验前提`);
      continue;
    }
    const beforeOffset = before[before.length - 1].offset;
    const afterOffset = after[after.length - 1].offset;
    if (!(beforeOffset < afterOffset)) {
      problems.push(
        `${contract.before} / ${contract.after}：ORDER_CONTRACTS 声明 ${contract.before} 在前，` +
          `但契约里偏移是 ${String(beforeOffset)} → ${String(afterOffset)}（判据写反了）`,
      );
    }
    const valueOf = (hits) => {
      const merged = new Map();
      for (const rule of hits) for (const [prop, value] of declarationsOf(rule.body)) merged.set(prop, value);
      return merged.get(contract.property);
    };
    const beforeValue = valueOf(before);
    const afterValue = valueOf(after);
    if (beforeValue === undefined || afterValue === undefined) {
      problems.push(
        `${contract.before} / ${contract.after}：契约里 ` +
          `${beforeValue === undefined ? contract.before : contract.after} 并不声明 ${contract.property} ⇒ 该对局不是同属性冲突`,
      );
      continue;
    }
    if (beforeValue.replace(/\s+/g, ' ') === afterValue.replace(/\s+/g, ' ')) {
      problems.push(
        `${contract.before} / ${contract.after}：两端 ${contract.property} 的契约值相同（${beforeValue}）⇒ ` +
          '谁胜出都不改变计算样式，这条源序守卫不可观测（永远不会失败）',
      );
    }
  }
  return problems;
}

/** 旧逻辑（加固前的全部内容）：只断言类名出现。**只在 `--self-test` 里用**，作负对照的比较基线。 */
function legacyGate(css) {
  const canaryMissing = CANARY_CLASSES.filter((name) => !hasClass(css, name));
  if (canaryMissing.length > 0) return { ok: false, reason: `canary 未命中 ${canaryMissing.join('/')}` };
  const missing = CONSULT_CLASSES.filter((name) => !hasClass(css, name));
  if (missing.length > 0) return { ok: false, reason: `缺类名 ${missing.join('/')}` };
  return { ok: true, reason: '通过（只查了 16 个类名出现过）' };
}

/** 加固后的全部闸门。 */
function runGates(css) {
  const rules = scanRules(css);
  const violations = [
    ...checkRuleContracts(rules, ELEMENT_RULE_CONTRACTS, 'element-rule'),
    ...checkRuleContracts(rules, COMPOUND_RULE_CONTRACTS, 'compound-rule'),
    ...checkOrder(rules, ORDER_CONTRACTS, 'source-order'),
    ...checkRenderedSelectors(rules, ['textarea', 'button.tag', '.sp-tag', '.text-button:disabled', '.chat-candidate', '.chat-candidate .ct-panel'], 'rendered-selector'),
  ];
  return { rules, violations };
}

// ── 自检：每道闸门都要有会变红的负对照 ────────────────────────────────────

/**
 * 变异体：每个都以「一份**基线通过**的 CSS」为起点，只破坏一件事。
 * `expectGate` 是必须报出该缺陷的闸门代号；`legacyMustPass` 断言旧逻辑在该变异体上**仍然通过**
 * ——那正是「加固有必要」的机械证据（不是推断）。
 */
const MUTATIONS = [
  {
    name: 'A-元素级规则整体缺失（textarea 8 条声明全删，只留 button,input,textarea,select{font:inherit}）',
    mutate: (css) => css.replace(/textarea\{[^{}]*\}/, ''),
    expectGate: 'element-rule',
    legacyMustPass: true,
  },
  {
    name: 'A-元素级规则声明不全（textarea 只删 min-height:120px）',
    mutate: (css) => css.replace('min-height:120px;', ''),
    expectGate: 'element-rule',
    legacyMustPass: true,
  },
  {
    name: 'A-元素级规则声明值错（textarea 的 border-radius 从 --radius-sm 改成 --radius-md）',
    mutate: (css) => css.replace(/textarea\{([^{}]*)\}/, (_m, body) => `textarea{${body.replace('border-radius:var(--radius-sm)', 'border-radius:var(--radius-md)')}}`),
    expectGate: 'element-rule',
    legacyMustPass: true,
  },
  {
    name: 'B-复合选择器缺失（button.tag 尺寸规则删除；.tag 基础规则仍在）',
    mutate: (css) => css.replace(/button\.tag\{[^{}]*\}/, ''),
    expectGate: 'compound-rule',
    legacyMustPass: true,
  },
  {
    name: 'B-复合选择器缺失（.sp-tag 删除）',
    mutate: (css) => css.replace(/\.sp-tag\{[^{}]*\}/, ''),
    expectGate: 'compound-rule',
    legacyMustPass: true,
  },
  {
    name: 'B-伪类态规则缺失（.text-button:disabled 删除；.text-button 基础规则仍在）',
    mutate: (css) => css.replace(/\.text-button:disabled\{[^{}]*\}/, ''),
    expectGate: 'compound-rule',
    legacyMustPass: true,
  },
  {
    name: 'C-源序颠倒（.tile 与 .question-card 两条规则调换位置）',
    mutate: (css) => {
      const tile = /\.tile\{[^{}]*\}/.exec(css);
      const card = /\.question-card\{[^{}]*\}/.exec(css);
      if (tile === null || card === null || tile.index > card.index) return css;
      return css.slice(0, tile.index) + card[0] + css.slice(tile.index + tile[0].length, card.index) + tile[0] + css.slice(card.index + card[0].length);
    },
    expectGate: 'source-order',
    legacyMustPass: true,
  },
  {
    name: 'C-源序颠倒（.candidate-toast 与 .chat-candidate 调换）',
    mutate: (css) => {
      const toast = /\.candidate-toast\{[^{}]*\}/.exec(css);
      const cand = /\.chat-candidate\{[^{}]*\}/.exec(css);
      if (toast === null || cand === null || toast.index > cand.index) return css;
      return css.slice(0, toast.index) + cand[0] + css.slice(toast.index + toast[0].length, cand.index) + toast[0] + css.slice(cand.index + cand[0].length);
    },
    expectGate: 'source-order',
    legacyMustPass: true,
  },
  {
    name: 'C-源序颠倒（.text-button 与 .question-free-toggle 调换）',
    mutate: (css) => {
      const tb = /\.text-button\{[^{}]*\}/.exec(css);
      const qft = /\.question-free-toggle\{[^{}]*\}/.exec(css);
      if (tb === null || qft === null || tb.index > qft.index) return css;
      return css.slice(0, tb.index) + qft[0] + css.slice(tb.index + tb[0].length, qft.index) + tb[0] + css.slice(qft.index + qft[0].length);
    },
    expectGate: 'source-order',
    legacyMustPass: true,
  },
  {
    name: 'D-真渲染选择器缺失（.chat-candidate .ct-panel 的 max-height 规则删除）',
    mutate: (css) => css.replace(/\.chat-candidate \.ct-panel\{[^{}]*\}/, ''),
    expectGate: 'rendered-selector',
    legacyMustPass: true,
  },
  {
    // 这一对的负对照：交换两条规则的位置。两端都是「元素 + 状态」、零类名，
    // 因此旧逻辑（只查 16 个类名出现过）在交换后必然仍然通过。
    name: 'C-源序颠倒（textarea:focus 与 textarea[aria-invalid=true] 调换）',
    mutate: (css) => {
      const focus = /textarea:focus\{[^{}]*\}/.exec(css);
      const invalid = /textarea\[aria-invalid=true\]\{[^{}]*\}/.exec(css);
      if (focus === null || invalid === null || focus.index > invalid.index) return css;
      return (
        css.slice(0, focus.index) +
        invalid[0] +
        css.slice(focus.index + focus[0].length, invalid.index) +
        focus[0] +
        css.slice(invalid.index + invalid[0].length)
      );
    },
    expectGate: 'source-order',
    legacyMustPass: true,
  },
];

/**
 * 自检模式：对每个变异体跑「新闸门」与「旧逻辑」，双向断言。
 *
 * 另跑一次**恒真对照**：把产物 CSS 整个换成空串——旧逻辑与 canary 都必须失败，
 * 证明「通过」不是来自「什么都没查」。
 */
async function selfTest(baselineCss) {
  let failures = 0;
  const lines = [];
  const record = (ok, text) => {
    lines.push(`${ok ? '  ✓' : '  ✗'} ${text}`);
    if (!ok) failures += 1;
  };

  lines.push('## 0. 基线（未变异）');
  const base = runGates(baselineCss);
  record(base.violations.length === 0, `加固后闸门在基线上通过（违规 ${String(base.violations.length)} 条）`);
  const baseLegacy = legacyGate(baselineCss);
  record(baseLegacy.ok, `旧逻辑在基线上通过（${baseLegacy.reason}）`);

  lines.push('');
  lines.push('## 1. 逐变异体：新闸门必须抓到，旧逻辑必须放过');
  for (const mutation of MUTATIONS) {
    const mutated = mutation.mutate(baselineCss);
    if (mutated === baselineCss) {
      record(false, `${mutation.name} —— **变异未生效**（变异体与基线逐字节相同，这条负对照是空的）`);
      continue;
    }
    const result = runGates(mutated);
    const caught = result.violations.filter((v) => v.code === mutation.expectGate);
    record(caught.length > 0, `${mutation.name} → 新闸门 \`${mutation.expectGate}\` 报出 ${String(caught.length)} 条`);
    if (caught.length > 0) lines.push(`      ${caught[0].selector}：${caught[0].detail}`);
    const legacy = legacyGate(mutated);
    if (mutation.legacyMustPass) {
      record(legacy.ok, `${mutation.name} → **旧逻辑仍然通过**（${legacy.reason}）⇒ 加固确有必要`);
    } else {
      record(!legacy.ok, `${mutation.name} → 旧逻辑也失败（${legacy.reason}）`);
    }
  }

  lines.push('');
  lines.push('## 2. 恒真对照：空 CSS 上两条路径都必须失败');
  const empty = runGates('');
  record(empty.violations.length > 0, `空 CSS → 新闸门报出 ${String(empty.violations.length)} 条违规`);
  const emptyLegacy = legacyGate('');
  record(!emptyLegacy.ok, `空 CSS → 旧逻辑失败（${emptyLegacy.reason}）`);

  lines.push('');
  lines.push('## 3. 判据承重性：ORDER_CONTRACTS 里不得有「不可观测」的对局');
  // 契约读取失败时这里只能跳过：自检允许在无契约的机器上跑，但会明确标注「未校验」。
  const contractPathForSelfTest = resolve(repoRoot, 'docs', 'design', 'components.html');
  const contractHtmlForSelfTest = await readFile(contractPathForSelfTest, 'utf8').catch(() => null);
  if (contractHtmlForSelfTest === null) {
    lines.push('  ⚠ 读不到契约真源，跳过承重性校验（**这不是通过**：本项未校验）');
  } else {
    const styleBlock = /<style>([\s\S]*?)<\/style>/.exec(contractHtmlForSelfTest);
    if (styleBlock === null) {
      record(false, '契约真源里没有 <style> 块');
    } else {
      const contractRulesForSelfTest = scanRules(styleBlock[1]);
      // 正向：现清单必须全部承重。
      const problems = assertOrderContractsAreLoadBearing(contractRulesForSelfTest);
      record(problems.length === 0, `现清单 ${String(ORDER_CONTRACTS.length)} 条全部承重（问题 ${String(problems.length)} 条）`);
      for (const p of problems) lines.push(`      ${p}`);
      // 负对照：把 `.tag` / `.meta` 这类退化对局塞回去，承重性校验必须变红。
      //
      // 前后顺序按契约实际先后写（`.meta` 173 在 `.tag` 174 前）：写反了会让这条对照
      // 因「判据写反」变红，于是「值相同 ⇒ 不可观测」那一条分支就再也没被验证过——
      // 负对照必须只在它要证明的那条理由上变红。
      const degenerate = ORDER_CONTRACTS.concat([
        { before: '.meta', after: '.tag', property: 'color', contractLines: [173, 174], note: '负对照：值相同，不可观测' },
      ]);
      const original = ORDER_CONTRACTS.splice(0, ORDER_CONTRACTS.length, ...degenerate);
      const degenerateProblems = assertOrderContractsAreLoadBearing(contractRulesForSelfTest);
      ORDER_CONTRACTS.splice(0, ORDER_CONTRACTS.length, ...original);
      record(
        degenerateProblems.some((p) => p.includes('.meta / .tag')),
        `负对照：把退化对局 .meta / .tag 塞进清单 → 承重性校验报出 ${String(degenerateProblems.length)} 条`,
      );
      for (const p of degenerateProblems) lines.push(`      ${p}`);
    }
  }

  lines.push('');
  lines.push(failures === 0 ? `结论：负对照全部成立（0 条失败）` : `结论：**${String(failures)} 条负对照失败**`);
  console.log(lines.join('\n'));
  return failures === 0;
}

// ── 主流程 ──────────────────────────────────────────────────────────────

const selfTestMode = process.argv.includes('--self-test');
const distArg = process.argv.slice(2).find((arg) => !arg.startsWith('--'));

if (selfTestMode) {
  // 自检的基线 = 当前产物；找不到产物时用 --baseline 指定的文件。
  const baselineArg = process.argv.includes('--baseline') ? process.argv[process.argv.indexOf('--baseline') + 1] : null;
  const distDir = resolve(webRoot, baselineArg ?? distArg ?? 'dist');
  const files = await collectCss(distDir);
  if (files.length === 0) {
    console.error(`[契约样式断言] 自检失败：${relative(webRoot, distDir)} 下没有 CSS 产物可作基线（先跑 vite build）`);
    process.exit(1);
  }
  const css = (await Promise.all(files.map((file) => readFile(file, 'utf8')))).join('\n');
  const ok = await selfTest(css);
  process.exit(ok ? 0 : 1);
}

const distDir = resolve(webRoot, distArg ?? 'dist');
const cssFiles = await collectCss(distDir);

if (cssFiles.length === 0) {
  console.error(`[契约样式断言] 失败：${relative(webRoot, distDir)} 下没有 CSS 产物，无法判定（先跑 vite build）`);
  process.exit(1);
}

const css = (await Promise.all(cssFiles.map((file) => readFile(file, 'utf8')))).join('\n');

const canaryMissing = CANARY_CLASSES.filter((name) => !hasClass(css, name));
if (canaryMissing.length > 0) {
  console.error(
    `[契约样式断言] 通道自检失败：canary 类名未命中 ${canaryMissing.map((name) => `.${name}`).join(' / ')}；` +
      '读到的产物 CSS 不可信，本次不判定契约类名（否则会把通道故障误报成接线遗漏）',
  );
  process.exit(1);
}

// 契约真源（顺序守卫与规则级断言的比对对象）。读不到就失败——不许在「没有契约」时假装通过。
const contractPath = resolve(repoRoot, 'docs', 'design', 'components.html');
const contractHtml = await readFile(contractPath, 'utf8').catch(() => null);
if (contractHtml === null) {
  console.error(`[契约样式断言] 失败：读不到契约真源 ${relative(repoRoot, contractPath)}，无法判定源序与规则声明`);
  process.exit(1);
}
const contractStyle = /<style>([\s\S]*?)<\/style>/.exec(contractHtml);
if (contractStyle === null) {
  console.error(`[契约样式断言] 失败：${relative(repoRoot, contractPath)} 里找不到 <style> 块`);
  process.exit(1);
}
const contractRules = scanRules(contractStyle[1]);

// 契约自身的源序必须先成立：否则断言会拿一个「契约自己就不满足」的判据去卡实现。
const contractOrderViolations = checkOrder(contractRules, ORDER_CONTRACTS, 'contract-source-order');
if (contractOrderViolations.length > 0) {
  console.error(
    `[契约样式断言] 失败：**契约自身**的源序与 ORDER_CONTRACTS 声明不符——判据过期了，先更新本脚本的常量\n` +
      contractOrderViolations.map((v) => `  ${v.selector}：${v.detail}`).join('\n'),
  );
  process.exit(1);
}

// 判据前提：登记的每一对都必须真的「靠源序决胜且可观测」，否则守卫是在空转。
const loadBearingProblems = assertOrderContractsAreLoadBearing(contractRules);
if (loadBearingProblems.length > 0) {
  console.error(
    `[契约样式断言] 失败：ORDER_CONTRACTS 里 ${String(loadBearingProblems.length)} 条判据不承重（不可观测或写反了）\n` +
      loadBearingProblems.map((p) => `  ${p}`).join('\n'),
  );
  process.exit(1);
}

const { violations } = runGates(css);

const missing = CONSULT_CLASSES.filter((name) => !hasClass(css, name));
if (missing.length > 0) {
  console.error(
    `[契约样式断言] 失败：产物 CSS 缺 ${String(missing.length)} 个对话面契约类名——${missing.map((name) => `.${name}`).join(' / ')}\n` +
      '  最可能的原因：消费它的页面模块漏了 import（对话面契约样式是全局类名表，必须被 import 才会进产物）。\n' +
      '  检查 features/consult/view/{ChatPage,EmergencyFormPage}.tsx 的 import 与 features/consult/view/consultComponents.css。',
  );
  process.exit(1);
}

if (violations.length > 0) {
  console.error(
    `[契约样式断言] 失败：${String(violations.length)} 条规则级违规（类名都在，但规则本身不对）：\n` +
      violations.map((v) => `  [${v.code}] ${v.selector}：${v.detail}`).join('\n') +
      '\n  这几道闸门是 2026-10-03（T05）加固的：改前只查类名出现过，拦不住「类名在、声明不在」与源序颠倒。\n' +
      '  每道闸门的负对照见 `node scripts/check-contract-css.mjs --self-test`。',
  );
  process.exit(1);
}

console.log(
  `契约样式断言通过：${String(CONSULT_CLASSES.length)} 个对话面契约类名全部在产物 CSS 中；` +
    `${String(ELEMENT_RULE_CONTRACTS.length)} 条元素级规则 + ${String(COMPOUND_RULE_CONTRACTS.length)} 条复合选择器规则与契约逐条一致；` +
    `${String(ORDER_CONTRACTS.length)} 组源序守卫保持契约先后` +
    `（${cssFiles.map((file) => relative(webRoot, file)).join(', ')}）`,
);
