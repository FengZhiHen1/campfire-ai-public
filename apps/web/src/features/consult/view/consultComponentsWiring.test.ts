/**
 * 模块: features/consult/view/consultComponentsWiring.test
 * 职责: 装配守卫——对话面契约样式表必须被页面模块真实 import
 * 数据来源:
 *   - src/features/consult/view/consultComponents.css: MUST — 被断言的样式表
 *   - docs/design/pages/{对话页,应急表单页}.md: MUST — 这些规则承载的视觉契约
 * 边界:
 *   - 依赖: node:fs、typescript（只用来解析 import 语句）
 *   - 被依赖: 无（装配守卫）
 * 禁止行为:
 *   - 禁止用整文件子串匹配当断言（注释里的同一句话会让守卫恒真）
 *
 * 为什么需要它：类名表是全局类名（不是 CSS Modules），组件用例只断言 class 字符串、
 * vitest 又把 CSS 桩成空对象，所以「漏 import」在 283 条用例里结构性不可见；
 * 这里断言真实的 import 语句存在。产物层面的同一件事由 scripts/check-contract-css.mjs 把关。
 */

import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

import ts from 'typescript';
import { describe, expect, it } from 'vitest';

/** 对话面 view 目录。 */
const VIEW_DIR = resolve(process.cwd(), 'src', 'features', 'consult', 'view');
/** 被断言的样式表绝对路径。 */
const SHEET = resolve(VIEW_DIR, 'consultComponents.css');

/**
 * 取模块源码里真实 import 的目标绝对路径。
 *
 * 用 TS 扫描器而不是正则/子串：注释里的 `import './consultComponents.css'` 不能算数，
 * 而这正是本次缺陷的形态（全仓只有两处注释提到该文件名，没有一处 import）。
 */
function importTargets(file: string): string[] {
  const source = readFileSync(file, 'utf8');
  const dir = dirname(file);
  return ts.preProcessFile(source, true, true).importedFiles.map((entry) => resolve(dir, entry.fileName));
}

describe('对话面契约样式表接线', () => {
  // ChatPage 渲染该表的消息流类名（骨架气泡、Citatio/Question/ActionCard 等的共享外观）。
  // 会话列表页只用 shared/styles/components.css 的 .list-row/.tile 等，故不在名单内。
  //
  // 应急表单页于 2026-11-18 角色化重做后**不再消费**该表：它的选中/按压/进度/当前题/
  // 提交中都在自己的 emergencyForm.module.css 里，行动卡的局部排版在 actionCard.module.css。
  // 因此它从本名单移出，改由下一条用例断言「消费了全局组件表 shared/styles/components.css
  // （确认单的 .btn/.button-row 来自这里）但没有再悄悄 import 对话面特性表」。
  it('ChatPage.tsx 真实 import 了 consultComponents.css', () => {
    expect(importTargets(resolve(VIEW_DIR, 'ChatPage.tsx'))).toContain(SHEET);
  });
  it('EmergencyFormPage.tsx 依赖全局组件表，且不再用对话面特性表', () => {
    const components = resolve(VIEW_DIR, '..', '..', '..', 'shared', 'styles', 'components.css');
    const targets = importTargets(resolve(VIEW_DIR, 'EmergencyFormPage.tsx'));
    expect(targets).toContain(components);
    expect(targets).not.toContain(SHEET);
  });
});
