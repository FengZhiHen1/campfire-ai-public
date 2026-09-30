/**
 * 模块: src/app/pages/HomePage.test
 * 职责: 首页的组件用例——入口可达性、文案逐字、静态区块无三态与 tab 栏当前态
 * 数据来源:
 *   - docs/design/pages/首页.md: MUST — 布局结构、数据与文案、状态覆盖表、响应式与平台（tab 栏）
 * 边界:
 *   - 依赖: app/pages/HomePage、shared/ui/AppShell、react-router 的内存路由
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言「最近会话预览」有加载态或空态（设计明确不渲染该区块）
 */

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

import { HomePage } from './HomePage';

/** 渲染首页。 */
function renderHome() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <HomePage />
    </MemoryRouter>,
  );
}

describe('首页 · 布局与入口', () => {
  it('P0 页头是宋体标题「篝火智答」且无账号名入口（账号归「我的」tab）', () => {
    renderHome();

    expect(screen.getByRole('heading', { name: '篝火智答', level: 1 })).toBeDefined();
    expect(screen.queryByText(/账号/)).toBeNull();
  });

  it('P0 应急入口标题与说明逐字呈现，且带呼吸点与主按钮', () => {
    renderHome();

    expect(screen.getByRole('heading', { name: '现在需要帮助' })).toBeDefined();
    expect(
      screen.getByText('在现场遇到正在发生的情况？回答几个问题，马上给你可行动的建议'),
    ).toBeDefined();
    expect(screen.getByRole('link', { name: '开始应急咨询' }).getAttribute('href')).toBe('/consult/emergency');
  });

  it('P0 应急入口是唯一带呼吸点的强调单元（.flame-dot）', () => {
    const { container } = renderHome();

    expect(container.querySelectorAll('.flame-dot')).toHaveLength(1);
    expect(container.querySelector('.emergency-entry')).not.toBeNull();
  });

  it('P0 日常咨询入口整卡可点，且不是与应急等宽的孪生卡（差异驱动）', () => {
    const { container } = renderHome();

    const daily = screen.getByRole('link', { name: /日常咨询/ });
    expect(daily.getAttribute('href')).toBe('/consult');
    expect(daily.className).toContain('tile');
    // 应急是 .panel + 描边，日常是 .tile；两者类名不同即层级不同。
    expect(container.querySelector('.emergency-entry')?.className).toContain('panel');
  });

  it('P0 次级入口行两张 mini-card，各指向案例库与资料分区', () => {
    const { container } = renderHome();

    expect(container.querySelectorAll('.mini-card')).toHaveLength(2);
    expect(screen.getByRole('link', { name: /案例库/ }).getAttribute('href')).toBe('/cases');
    expect(screen.getByRole('link', { name: /资料库说明/ }).getAttribute('href')).toBe('/cases?section=library');
  });

  it('P0 次级入口文案逐字', () => {
    renderHome();

    expect(screen.getByText('看看别的家庭怎么处理类似情况')).toBeDefined();
    expect(screen.getByText('每条建议都标来源与适用范围')).toBeDefined();
  });
});

describe('首页 · 状态覆盖', () => {
  it('P0 静态区块直接渲染：页面内没有任何骨架/空态/错误卡', () => {
    const { container } = renderHome();

    expect(container.querySelectorAll('.skeleton')).toHaveLength(0);
    expect(container.querySelectorAll('.empty-state')).toHaveLength(0);
    expect(container.querySelectorAll('.error-card')).toHaveLength(0);
  });

  it('P0 无「最近会话预览」区块，也没有为它造空态（首页没有空语义）', () => {
    const { container } = renderHome();

    expect(container.querySelectorAll('.list-row')).toHaveLength(0);
    expect(screen.queryByText(/最近/)).toBeNull();
  });
});

describe('首页 · tab 栏', () => {
  it('P0 渲染四项 tab 栏，当前项是首页', () => {
    renderHome();

    const nav = screen.getByRole('navigation', { name: '一级导航' });
    expect(nav.querySelectorAll('.tab-item')).toHaveLength(4);
    expect(screen.getByRole('link', { name: '首页' }).getAttribute('aria-current')).toBe('page');
  });

  it('P0 tab 项图标与文字双通道（不是只靠颜色区分当前项）', () => {
    renderHome();

    const home = screen.getByRole('link', { name: '首页' });
    expect(home.querySelector('svg')).not.toBeNull();
    expect(home.textContent).toContain('首页');
  });

  it('P1 一级页面容器为固定 tab 栏预留底部高度', () => {
    const { container } = renderHome();

    expect(container.querySelector('.phone-shell')?.className).toContain('has-tab-bar');
  });
});
