/**
 * 模块: src/features/accounts/AboutPage.test
 * 职责: 「关于篝火智答」页的用例——数据用途三项告知逐字、一期边界硬文案逐字、次级页头、零 accent
 * 数据来源:
 *   - docs/design/pages/设置页.md: MUST — 数据与文案（三项告知成稿）、RQ-LIM-03/RQ-LIM-04 硬文案
 * 边界:
 *   - 依赖: features/accounts/view/AboutPage、react-router 的内存路由
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止弱化一期边界硬文案（断言逐字，含 AC-10 反向声明）
 */

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

import { AboutPage } from './AboutPage';

/** 一期边界硬文案（页面设计成稿，逐字；AC-10 的反向如实声明）。 */
const BOUNDARY_COPY =
  '本应用尚未经专业审阅，不能替代专业服务；遇到紧急医疗情况请直接就医或拨打急救电话';

/** 渲染关于页。 */
function renderAbout() {
  return render(
    <MemoryRouter initialEntries={['/settings/about']}>
      <AboutPage />
    </MemoryRouter>,
  );
}

describe('关于篝火智答 · 页头', () => {
  it('P0 次级页头：返回 + 标题，返回指向设置页，且不渲染 tab 栏', () => {
    const { container } = renderAbout();

    expect(screen.getByRole('link', { name: '返回' }).getAttribute('href')).toBe('/settings');
    const head = container.querySelector('header.subpage-head');
    expect(head).not.toBeNull();
    expect(head?.querySelector('.sp-title')?.textContent).toBe('关于篝火智答');
    expect(screen.queryByRole('navigation', { name: '一级导航' })).toBeNull();
  });
});

describe('关于篝火智答 · 数据与边界', () => {
  it('P0 「关于你的数据」三行要点逐字', () => {
    renderAbout();

    expect(screen.getByText('咨询记录怎么用')).toBeDefined();
    expect(screen.getByText('本次输入的内容用于生成回答，并按你的确认累积到档案与记忆')).toBeDefined();
    expect(screen.getByText('谁可见')).toBeDefined();
    expect(screen.getByText('只有你的账号可以看到；登录才能使用全部功能')).toBeDefined();
    expect(screen.getByText('会送去外部模型吗')).toBeDefined();
    expect(screen.getByText('咨询内容会发送给模型服务处理后返回')).toBeDefined();
  });

  it('P0 一期边界硬文案逐字呈现（AC-10 反向声明不得弱化）', () => {
    renderAbout();

    expect(screen.getByText(BOUNDARY_COPY)).toBeDefined();
  });

  it('P0 不出现专业认可或临床效果类表述', () => {
    const { container } = renderAbout();

    expect(container.textContent).not.toMatch(/专业认可|临床效果|零幻觉/);
  });

  it('P0 页面刻意零 accent（告知页不是行动页）', () => {
    const { container } = renderAbout();

    expect(container.querySelectorAll('.btn-primary')).toHaveLength(0);
    expect(container.querySelectorAll('.flame-dot')).toHaveLength(0);
  });
});
