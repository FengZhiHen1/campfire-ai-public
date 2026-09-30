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

import { App } from './app/App';
import './shared/styles/tokens.css';
import './shared/styles/components.css';
import './shared/styles/global.css';

const container = document.getElementById('root');
if (container === null) {
  throw new Error('缺少 #root 容器，index.html 与入口不匹配');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
