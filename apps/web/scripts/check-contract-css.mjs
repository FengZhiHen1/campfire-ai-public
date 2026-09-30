/**
 * 模块: scripts/check-contract-css
 * 职责: 构建后断言——对话面契约样式表（consultComponents.css）真的进了产物 CSS
 * 数据来源:
 *   - src/features/consult/view/consultComponents.css: MUST — 被断言的契约类名清单来源
 *   - docs/design/pages/{对话页,应急表单页}.md: MUST — 这些类名承载的视觉契约
 * 边界:
 *   - 依赖: node:fs/promises、node:path
 *   - 被依赖: apps/web 的 build 脚本（vite build 之后）
 * 禁止行为:
 *   - 禁止在产物缺失或读不到 CSS 时静默通过（看不清就失败，不假装成功）
 *   - 禁止只查契约类名而不查通道 canary（读不到文件时两边都 0 命中，会误判成「表没接线」）
 *
 * 为什么需要它：类名表是全局类名（不是 CSS Modules），组件里漏写 import 时构建照样成功、
 * 单测照样全绿（vitest 默认 css: false，组件用例只断言 class 字符串），
 * 只有产物里到底有没有这些规则能发现「接线遗漏」。vitest 看不到产物，故断言放在构建后。
 */

import { readdir, readFile } from 'node:fs/promises';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(scriptDir, '..');

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

const distDir = resolve(webRoot, process.argv[2] ?? 'dist');
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

const missing = CONSULT_CLASSES.filter((name) => !hasClass(css, name));
if (missing.length > 0) {
  console.error(
    `[契约样式断言] 失败：产物 CSS 缺 ${String(missing.length)} 个对话面契约类名——${missing.map((name) => `.${name}`).join(' / ')}\n` +
      '  最可能的原因：消费它的页面模块漏了 import（对话面契约样式是全局类名表，必须被 import 才会进产物）。\n' +
      '  检查 features/consult/view/{ChatPage,EmergencyFormPage}.tsx 的 import 与 features/consult/view/consultComponents.css。',
  );
  process.exit(1);
}

console.log(
  `契约样式断言通过：${String(CONSULT_CLASSES.length)} 个对话面契约类名全部在产物 CSS 中` +
    `（${cssFiles.map((file) => relative(webRoot, file)).join(', ')}）`,
);
