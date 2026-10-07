// 类名保真检查:影片的**手写复刻**组件里,凡是用 `className="..."` 写字符串类名的,
// 那个类名必须在**产品 CSS 里真的有定义**(或在影片自己的样式里定义)。
//
// ── 为什么需要这个检查 ──────────────────────────────────────────────
// skill 的 final-review D3 要求「表现真实产品页面时使用真实截图,而非低质量手搓复刻」。
// 本片由于**帧驱动**的技术约束无法直接用真实页面(实测:EmergencyFormPage 的
// index/handled 是 useState,不同帧渲染出逐字节相同的画面),因此对手写复刻走的是
// 「复用产品契约类名 + 产品 CSS」的路线。
//
// 这条路线的**特有失效模式**是:写一个「看起来像产品类名」但产品里不存在的字符串。
// 它不会报错、不会警告,元素静默退回浏览器默认外观 —— 也就是**静默错版**。
//
// 本项目已经踩过两次:
//   ① `step-forward` / `handled-note`  —— 产品用的是 CSS Module 的
//      `.stepForward` / `.handledNote`,编译后带哈希,kebab 形式永远命中不了;
//      连带丢掉了 `display:block`、题间滑入动画、以及 handledNote 的
//      `color: var(--meta)` 与 `margin-top: var(--space-4)`。
//   ② 更早一次:`ports.ts` 自造领域标签(与产品 domains.ts 四个键全部不一致)。
//
// 所以把它变成**机械检查**,而不是靠「我看着一样」。
//
// ── 检查口径 ────────────────────────────────────────────────────────
// 只检查 src/lib 下的**复刻组件**(EmergencyFormView / ChatScreen / ActionCardScreen),
// 它们是「模仿产品某一页」的组件,因此其类名应当来自产品。
// 镜头的版式类名(NoteKicker 之类)和影片自有的 film-* 前缀不在此列。
//
// 例外清单:`phone-shell` 由产品 global.css 定义(选择器是 `.phone-shell`,
//   我的抽取正则漏了它),脚本对「产品 CSS 里真实存在」的类名一律放行 ——
//   所以它不需要进例外清单,只要正则是按 CSS 文件全文匹配即可。

import {readFileSync, readdirSync, statSync} from 'node:fs';
import {join} from 'node:path';

// 脚本从 marketing/promo-shotcraft 运行:上两级到仓库根。
const WEB_SRC = '../../apps/web/src';
const FILM_SRC = 'src';

/** 需要检查的复刻组件(模仿产品页面的那些)。 */
const RECON_COMPONENTS = [
  'EmergencyFormView.tsx',
  'ChatScreen.tsx',
  'ActionCardScreen.tsx',
];

interface Finding {
  file: string;
  cls: string;
  reason: string;
}

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

/**
 * 收集所有「被定义过」的类名。
 *
 * 两个来源缺一不可:
 *   ① 产品 CSS 文件 —— 契约类名(subpage-head / selection / check-box …)
 *   ② 影片自己的样式 —— 它们**不在 .css 文件里**,而是写在 .tsx 的
 *      `<style>{`...`}</style>` 模板串里(见 lib/DeviceStage.tsx)。
 *      只扫 .css 会漏掉全部 film-* 类,从而把影片自有的版式误报成自造类名。
 */
function collectDefinedClasses(): Set<string> {
  const names = new Set<string>();

  // ① 产品 + 影片的 .css
  for (const root of [WEB_SRC, FILM_SRC]) {
    let files: string[];
    try {
      files = walk(root).filter((f) => f.endsWith('.css'));
    } catch {
      continue;
    }
    for (const f of files) {
      for (const m of readFileSync(f, 'utf8').matchAll(/\.([a-zA-Z][\w-]*)/g)) {
        names.add(m[1]);
      }
    }
  }

  // ② 影片源码里的内联样式块(TS/TSX 中形如 `.foo {` 或 `.foo,` 的选择器)
  let filmFiles: string[];
  try {
    filmFiles = walk(FILM_SRC).filter((f) => /\.tsx?$/.test(f));
  } catch {
    filmFiles = [];
  }
  for (const f of filmFiles) {
    const text = readFileSync(f, 'utf8');
    for (const m of text.matchAll(/\.([a-zA-Z][\w-]*)\s*(?=[,{])/g)) {
      names.add(m[1]);
    }
  }

  return names;
}

/** 去掉注释 —— 否则注释里举例写的 `className="foo"` 会被当成真实用法误报。 */
function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, ' ')        // 块注释
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1 ');   // 行注释(避开 URL 里的 //)
}

/** 抽出 `className="a b c"` 里的字面量类名(模板串里的插值忽略)。 */
function literalClasses(src: string): string[] {
  const out: string[] = [];
  for (const m of stripComments(src).matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/g)) {
    const raw = (m[1] ?? m[2] ?? '').replace(/\$\{[^}]*\}/g, ' ');
    for (const tok of raw.split(/\s+/)) {
      if (tok && !tok.includes('.')) out.push(tok);
    }
  }
  return out;
}

const cssClasses = collectDefinedClasses();
const findings: Finding[] = [];

for (const file of RECON_COMPONENTS) {
  let src: string;
  try {
    src = readFileSync(join(FILM_SRC, 'lib', file), 'utf8');
  } catch {
    findings.push({file, cls: '(读不到文件)', reason: '文件不存在'});
    continue;
  }
  for (const cls of literalClasses(src)) {
    if (cssClasses.has(cls)) continue;
    findings.push({
      file,
      cls,
      reason: '产品与影片的 CSS 里都没有这个类名 —— 元素会退回浏览器默认外观(静默错版)',
    });
  }
}

console.log('类名保真检查:影片复刻组件 vs 产品 CSS');
console.log(`  已定义的类名(产品 CSS + 影片样式): ${cssClasses.size} 个`);
console.log(`  检查的复刻组件            : ${RECON_COMPONENTS.join(', ')}`);
console.log('');

if (findings.length === 0) {
  console.log('✓ 全部类名都能在产品或影片 CSS 里找到定义');
  process.exit(0);
}

console.log(`✗ 发现 ${findings.length} 个无处定义的类名:`);
for (const f of findings) console.log(`  ${f.file}: ${f.cls}\n      ${f.reason}`);
console.log('');
console.log('修法二选一:');
console.log('  · 若产品确有该样式 → 写成产品**实际**的类名(注意 CSS Module 是哈希的,影片里命中不了,');
console.log('    应改为照产品原值写行内样式);');
console.log('  · 若本是影片自有版式 → 加 film- 前缀并在影片自己的样式里定义。');
process.exit(1);
