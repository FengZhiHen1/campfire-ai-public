/**
 * 模块: src/test/contractCss
 * 职责: 把真实契约样式表注入 jsdom——供需要读 computed style 的用例使用
 * 数据来源:
 *   - shared/styles/components.css: MUST — 契约组件表（被测对象）
 * 边界:
 *   - 依赖: node:fs、jsdom 的 document.styleSheets
 *   - 被依赖: 断言层级/计算样式的用例
 * 禁止行为:
 *   - 禁止在本模块伪造样式值（只注入真实文件，不改写内容）
 *
 * 为什么需要它：vitest 默认 `css: false`，会把 `import './x.css'` 桩成空对象，
 * 因此组件里 import 的样式在 jsdom 里完全不生效（实测 computed 全为初始值）。
 * 想让 z-index 这类断言真的测到契约表，只能把文件读进来手动注入 <style>。
 * 本包实测：注入后 `.tab-bar` 的 computed z-index 读得到 "40"，证明通道有效。
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { expect } from 'vitest';

/** 注入过的标记属性；重复调用不会堆叠样式表。 */
const INJECTED_ATTR = 'data-contract-css';

/**
 * 注入契约样式（tokens + components）。
 *
 * tokens 必须先注入：components.css 大量使用 var()，而 jsdom 的 computed style
 * 会把未解析的 var() 原样返回（实测 `border-radius: "var(--radius-lg) ..."`），
 * 先注入 tokens 才能让需要变量解析的断言拿到像素值。
 *
 * 幂等：同一测试文件里多次调用只注入一次。
 */
export function injectContractCss(): void {
  if (document.head.querySelector(`style[${INJECTED_ATTR}]`) !== null) return;

  const read = (name: string): string =>
    readFileSync(resolve(process.cwd(), 'src', 'shared', 'styles', name), 'utf8');

  const style = document.createElement('style');
  style.setAttribute(INJECTED_ATTR, '');
  style.textContent = `${read('tokens.css')}\n${read('components.css')}`;
  document.head.append(style);
}

/**
 * 断言「注入通道确实生效」的 canary。
 *
 * 没有它，一个注入失败的用例会读到初始值（z-index: auto）而不是期望值，
 * 「sheet 高于 tab 栏」这类比较可能因为两边都读到 auto 而意外通过。
 * 这里用一个契约表里确定存在的字面量（.tab-bar 的 z-index: 40）验证通道。
 */
export function expectContractCssActive(): void {
  const probe = document.createElement('div');
  probe.className = 'tab-bar';
  document.body.append(probe);
  const zIndex = getComputedStyle(probe).zIndex;
  probe.remove();

  expect(
    zIndex,
    '契约样式未注入成功（读到初始值）：computed z-index 断言会失去判别力，请检查 injectContractCss 的调用',
  ).toBe('40');
}
