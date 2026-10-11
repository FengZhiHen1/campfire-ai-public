/**
 * 模块: src/main
 * 职责: 前端入口——挂载样式与根组件
 * 数据来源:
 *   - docs/项目结构设计.md: MUST — 第 9 节
 * 边界:
 *   - 依赖: app/App、shared/styles（tokens 与 global）
 *   - 被依赖: index.html
 * 禁止行为:
 *   - 禁止在入口做业务逻辑（装配归 app/App）
 */

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

/* 样式先于 App 导入：Vite/Rollup 按模块图的求值顺序收集 CSS，`import { App }` 会让
 * App 子树（ChatPage（`features/consult/view/ChatPage.tsx`）与
 * EmergencyFormPage（`features/consult/view/EmergencyFormPage.tsx`）各有一句
 * `import './consultComponents.css'`）的 CSS 先于本处进产物，于是特性表排在基线表之前。
 *
 * 为什么这是缺陷而不是风格问题：契约页（`docs/design/components.html`）的顺序是
 * 「基线表在前、特性表在后」，而契约里靠源序决胜的同特异性规则对会因此翻转胜负。
 * 实测的一例：`QuestionCard.tsx:45`/`:56` 渲染的元素同时带 `tile` 与 `question-card`
 * 两个类，两条规则特异性相同（都是单类）且都设 `padding`——
 *   契约：`.tile`（20px）在前、`.question-card`（0）在后 ⇒ 0 胜；
 *   改前产物：`.question-card`@7120 在前、`.tile`@19836 在后 ⇒ 20px 胜 ⇒ 卡片四周多 20px 内缩。
 *
 * 顺序守卫见 `scripts/check-contract-css.mjs`（断言产物里 `.tile{` 的偏移小于
 * `.question-card{` 的偏移）——改回本块顺序会立刻让 build 失败，不会静默复发。
 *
 * 为什么不用 `@layer`：那是站点级层叠语义变更，会同时改变全部规则的优先级语义，
 * 超出本处修复的授权范围（见 tasks/T05.md 第一节的裁决）。 */
import './shared/styles/tokens.css';
import './shared/styles/components.css';
import './shared/styles/global.css';

import { App } from './app/App';

const container = document.getElementById('root');
if (container === null) {
  throw new Error('缺少 #root 容器，index.html 与入口不匹配');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
