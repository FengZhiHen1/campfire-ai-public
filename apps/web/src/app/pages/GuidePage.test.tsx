/**
 * 模块: src/app/pages/GuidePage.test
 * 职责: 使用说明页的用例——四条路的文案逐字、硬文案、入口链接与非入口卡、零 accent
 * 数据来源:
 *   - docs/design/pages/使用说明.md: MUST — 全文（四条路、硬文案、响应式节的可点性、动效与 token）
 * 边界:
 *   - 依赖: app/pages/GuidePage、react-router 的内存路由
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止把说明卡断言成可点入口（说明卡不是入口卡）
 */

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

import { GuidePage } from './GuidePage';

/** 渲染使用说明页。 */
function renderGuide() {
  return render(
    <MemoryRouter initialEntries={['/guide']}>
      <GuidePage />
    </MemoryRouter>,
  );
}

describe('使用说明 · 页头', () => {
  it('P0 次级页面页头：返回 + 标题，且不渲染 tab 栏', () => {
    renderGuide();

    expect(screen.getByRole('link', { name: '← 返回' })).toBeDefined();
    expect(screen.getByText('使用说明')).toBeDefined();
    expect(screen.queryByRole('navigation', { name: '一级导航' })).toBeNull();
  });

  it('P0 返回指向设置页（本页从设置页常驻可达）', () => {
    renderGuide();

    expect(screen.getByRole('link', { name: '← 返回' }).getAttribute('href')).toBe('/settings');
  });
});

describe('使用说明 · 四条路', () => {
  it('P0 应急咨询小节的文案逐字，含硬文案', () => {
    renderGuide();

    expect(screen.getByRole('heading', { name: '应急咨询' })).toBeDefined();
    expect(screen.getByText('正在现场、正在发生时用；回答几个问题，马上给你可行动的建议')).toBeDefined();
    expect(screen.getByText('紧急医疗情况请直接就医或拨打急救电话')).toBeDefined();
  });

  it('P0 日常咨询小节文案逐字', () => {
    renderGuide();

    expect(screen.getByRole('heading', { name: '日常咨询' })).toBeDefined();
    expect(screen.getByText('想聊聊正在准备或刚发生的事，随时开始')).toBeDefined();
  });

  it('P0 档案与记忆小节文案逐字（RQ-MEM-02/RQ-MEM-04 的用户语）', () => {
    renderGuide();

    expect(screen.getByRole('heading', { name: '档案与记忆' })).toBeDefined();
    expect(screen.getByText('你说的话会累积成档案；系统整理的推断要经你确认才算数')).toBeDefined();
  });

  it('P0 数据与隐私小节有一句话摘要与指向设置页的内联链接', () => {
    renderGuide();

    expect(screen.getByRole('heading', { name: '数据与隐私' })).toBeDefined();
    expect(screen.getByText('你的咨询内容会发送给模型服务处理后返回。')).toBeDefined();
    expect(screen.getByRole('link', { name: '设置页 · 关于你的数据' }).getAttribute('href')).toBe('/settings');
  });

  it('P0 尾部边界说明行与设置页同一口径', () => {
    renderGuide();

    expect(screen.getByText('本应用尚未经专业审阅，不能替代专业服务')).toBeDefined();
  });

  it('P0 不出现专业认可、临床效果与「零幻觉」类表述（AC-10）', () => {
    const { container } = renderGuide();

    expect(container.textContent).not.toMatch(/专业认可|临床效果|零幻觉/);
  });

  it('P0 无版本号、反馈入口与「关于我们」（一期无此能力，不做空壳区块）', () => {
    renderGuide();

    expect(screen.queryByText(/版本/)).toBeNull();
    expect(screen.queryByText(/反馈/)).toBeNull();
    expect(screen.queryByText('关于我们')).toBeNull();
  });
});

describe('使用说明 · 响应式与懒性', () => {
  it('P0 小节卡不可点跳转（说明卡不是入口卡；入口在首页与对话页）', () => {
    const { container } = renderGuide();

    // 全页只有两个链接：返回与设置页内联链接。
    expect(container.querySelectorAll('a')).toHaveLength(2);
  });

  it('P0 页面级零动效、零 accent', () => {
    const { container } = renderGuide();

    expect(container.querySelectorAll('.btn-primary')).toHaveLength(0);
    expect(container.querySelectorAll('.flame-dot')).toHaveLength(0);
    for (const tile of container.querySelectorAll('.tile')) {
      expect(tile.className).not.toMatch(/anim|fade|stagger/i);
    }
  });

  it('P0 静态内容直接渲染：无骨架、无空态、无错误卡', () => {
    const { container } = renderGuide();

    expect(container.querySelectorAll('.skeleton')).toHaveLength(0);
    expect(container.querySelectorAll('.empty-state')).toHaveLength(0);
    expect(container.querySelectorAll('.error-card')).toHaveLength(0);
  });
});
