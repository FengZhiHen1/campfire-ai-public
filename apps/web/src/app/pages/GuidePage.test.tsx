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

  it('P0 标题走次级页头结构 .subpage-head + .sp-title（返回控件与吸顶头由契约提供）', () => {
    const { container } = renderGuide();

    // 设计原文此处写 .page-head，但该页声明自己是次级页、契约把返回控件定义在
    // .subpage-head 上，其余四个次级页设计也均写 .subpage-head（编排器裁决为原文笔误）。
    // 这条断言把这个裁决钉住：谁改回 .page-head，这里就会红——返回控件的定位会一起坏掉。
    const head = container.querySelector('header.subpage-head');
    expect(head).not.toBeNull();
    expect(head?.querySelector('.sp-back')).not.toBeNull();
    expect(head?.querySelector('.sp-title')?.textContent).toBe('使用说明');
    expect(container.querySelector('.page-head')).toBeNull();
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

describe('使用说明 · 小节图标', () => {
  /** 四小节的标题（顺序即页面自上而下的顺序）。 */
  const TITLES = ['应急咨询', '日常咨询', '档案与记忆', '数据与隐私'] as const;

  it('P0 四个小节各有一枚图标（设计把「图标 + 标题」列为该页不靠颜色的层次手段）', () => {
    const { container } = renderGuide();

    const tiles = [...container.querySelectorAll('.tile')];
    expect(tiles).toHaveLength(TITLES.length);
    for (const tile of tiles) {
      expect(tile.querySelector('svg')).not.toBeNull();
    }
  });

  it('P0 四枚图标均带图标容器、1.6px 描边且不参与可访问树', () => {
    const { container } = renderGuide();

    // CSS Modules 会给类名加哈希（实测形如 `_sectionIcon_2d552b`），因此按子串匹配；
    // 直接写 `.sectionIcon` 在 jsdom 里恒不命中（本包踩过：断言会假红）。
    const icons = [...container.querySelectorAll('[class*="sectionIcon"] svg')];
    expect(icons).toHaveLength(TITLES.length);
    for (const svg of icons) {
      expect(svg.getAttribute('stroke-width')).toBe('1.6');
      // 图标是装饰：语义由标题承担，故不进可访问树（避免标题被读两遍）。
      expect(svg.getAttribute('aria-hidden')).toBe('true');
      // 契约要求描边用 currentColor 上色（颜色由 .sectionIcon 给 --fg-2）。
      expect(svg.getAttribute('stroke')).toBe('currentColor');
      expect(svg.getAttribute('fill')).toBe('none');
    }
  });

  it('P0 四枚图标形状互不相同（同形会让「不靠颜色」的区分退化成装饰）', () => {
    const { container } = renderGuide();

    const paths = [...container.querySelectorAll('[class*="sectionIcon"] svg')].map((svg) =>
      [...svg.querySelectorAll('path, circle, ellipse, rect')]
        .map((shape) => shape.getAttribute('d') ?? shape.getAttribute('cx') ?? '')
        .join('|'),
    );

    expect(paths).toHaveLength(TITLES.length);
    // 形状串两两不同；canary 是下面那条「拿同一形状复制四份必然相等」的对照。
    expect(new Set(paths).size).toBe(TITLES.length);

    const duplicated = [paths[0], paths[0], paths[0], paths[0]];
    expect(new Set(duplicated).size).toBe(1);
  });
});

describe('使用说明 · 响应式与懒性', () => {
  it('P0 小节卡不可点跳转（说明卡不是入口卡；入口在首页与对话页）', () => {
    const { container } = renderGuide();

    // 全页只有两个链接：返回与设置页内联链接。
    expect(container.querySelectorAll('a')).toHaveLength(2);
  });

  it('P0 数据与隐私的链接行是 44px 热区（裸 a 无 min-height，实现侧就地补）', () => {
    const { container } = renderGuide();

    // 类名带 CSS Modules 哈希，故按子串匹配。
    const row = container.querySelector('[class*="privacyRow"]');
    expect(row).not.toBeNull();
    expect(row?.querySelector('a')).not.toBeNull();
    // 实际像素高度由 CSS 决定，而 jsdom 不解析 CSS Modules（vitest 默认 css:false），
    // 因此这里断言的是「承载热区的结构存在」；真实高度由视觉走查量测（见报告返工记录）。
    expect(container.querySelectorAll('[class*="privacyRow"]')).toHaveLength(1);
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
