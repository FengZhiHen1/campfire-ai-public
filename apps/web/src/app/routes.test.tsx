/**
 * 模块: src/app/routes.test
 * 职责: 路由守卫的对抗用例——未登录访问业务路由转登录页，已登录可达
 * 数据来源:
 *   - docs/项目结构设计.md: MUST — 第 9 节（前端守卫只负责体验，不构成权限证明）
 * 边界:
 *   - 依赖: app/routes、features/accounts/viewModel/sessionStore、react-router 的内存路由
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言「守卫等于授权」（本用例只断言体验层行为）
 */

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, useRoutes } from 'react-router';

import { buildRouteObjects } from './routes';
import { useSessionStore } from '../features/accounts/viewModel/sessionStore';

/** 用内存路由渲染指定路径，返回渲染结果供断言。 */
function renderAt(path: string) {
  function ProbedRoutes() {
    return useRoutes(buildRouteObjects());
  }

  return render(
    <MemoryRouter initialEntries={[path]}>
      <ProbedRoutes />
    </MemoryRouter>,
  );
}

/** 直接写会话状态，避免用例经过 SDK。 */
function setSession(status: 'unknown' | 'authenticated' | 'anonymous'): void {
  useSessionStore.setState({ session: { status } });
}

describe('路由守卫', () => {
  it('P0 未登录访问首页转到登录页', () => {
    setSession('anonymous');
    renderAt('/');

    expect(screen.getByRole('heading', { name: '篝火智答', level: 1 })).toBeDefined();
    expect(screen.queryByRole('heading', { name: '现在需要帮助' })).toBeNull();
  });

  it('P0 未登录访问 /profile 同样转到登录页', () => {
    setSession('anonymous');
    renderAt('/profile');

    expect(screen.getByRole('heading', { name: '篝火智答', level: 1 })).toBeDefined();
  });

  it('P1 已登录访问 /profile 渲染档案页而不是占位', async () => {
    setSession('authenticated');
    // 档案页在挂载时经端口取对象列表；这里把 fetch 替成空列表，
    // 让页面确定性地停在「还没有记录」而不是去连真实后端。
    const fetchStub = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ items: [] }) }));
    vi.stubGlobal('fetch', fetchStub);
    try {
      renderAt('/profile');

      expect(screen.getByRole('heading', { name: '档案' })).toBeDefined();
      // 等对象列表请求完成并进入页面空态，避免请求的状态更新落在用例结束之后。
      await screen.findByText('还没有记录');
      // 对象切换器是真实页面的结构，占位页没有它——这条才是「不是占位」的判据。
      expect(screen.getByRole('group', { name: '支持对象' })).toBeDefined();
      expect(screen.queryByText('支持对象档案：当前认识、待确认候选与补充。')).toBeNull();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('P1 已登录访问 / 渲染首页的真实内容而不是占位', () => {
    setSession('authenticated');
    renderAt('/');

    expect(screen.getByRole('heading', { name: '现在需要帮助' })).toBeDefined();
    expect(screen.queryByText('本页尚在建设中。')).toBeNull();
  });

  it('P1 已登录访问 /settings 渲染设置页真实内容，且无建设中占位', () => {
    setSession('authenticated');
    renderAt('/settings');

    expect(screen.getByRole('heading', { name: '我的', level: 1 })).toBeDefined();
    expect(screen.getByText('个人账号 · 邀请码注册')).toBeDefined();
    expect(screen.queryByText('本页尚在建设中。')).toBeNull();
  });

  it('P1 已登录访问 /guide 渲染使用说明页真实内容，且无 tab 栏（次级页）', () => {
    setSession('authenticated');
    renderAt('/guide');

    expect(screen.getByText('应急咨询')).toBeDefined();
    // 次级页面不渲染 tab 栏（首页页设计的契约修订节：全局唯一，次级页不渲染）。
    expect(screen.queryByRole('navigation', { name: '一级导航' })).toBeNull();
  });

  it('P1 一级页面渲染 tab 栏且当前项标为当前页', () => {
    setSession('authenticated');
    renderAt('/');

    const nav = screen.getByRole('navigation', { name: '一级导航' });
    expect(nav).toBeDefined();
    expect(screen.getByRole('link', { name: '首页' }).getAttribute('aria-current')).toBe('page');
    expect(screen.getByRole('link', { name: '我的' }).getAttribute('aria-current')).toBeNull();
  });

  it('P1 unknown 态不跳登录页，显示等待态', () => {
    setSession('unknown');
    renderAt('/profile');

    expect(screen.getByText('正在确认登录状态…')).toBeDefined();
    expect(screen.queryByRole('heading', { name: '篝火智答', level: 1 })).toBeNull();
  });

  it('P2 未匹配路径渲染「页面不存在」而不是空白', () => {
    setSession('authenticated');
    renderAt('/nope');

    expect(screen.getByRole('heading', { name: '页面不存在' })).toBeDefined();
  });

  it('P2 未匹配路径不再自相矛盾：说了「页面不存在」就不再说「建设中」', () => {
    setSession('authenticated');
    renderAt('/nope');

    // 正方向：标题与说明必须仍在（404 不许因为修矛盾而丢失信息）。
    expect(screen.getByRole('heading', { name: '页面不存在' })).toBeDefined();
    expect(screen.getByText('这个地址没有对应页面，请从首页重新进入。')).toBeDefined();
    // 反方向：路径不存在与「本页尚在建设中」不能并置——前者说没有这个页面，
    // 后者说这个页面有、只是没做完。两句话同时出现会让使用者不知道该不该重试。
    expect(screen.queryByText('本页尚在建设中。')).toBeNull();
  });

  it('P3 任务裁决的十个路径都在路由表里', () => {
    const paths = buildRouteObjects().map((route) => route.path);
    for (const expected of [
      '/login',
      '/',
      '/consult',
      '/consult/sessions/:sessionId',
      '/consult/emergency',
      '/profile',
      '/cases',
      '/settings',
      '/settings/memory',
      '/guide',
    ]) {
      expect(paths).toContain(expected);
    }
  });

  it('P3 /login 自身不受守卫保护（否则自转死循环）', () => {
    setSession('anonymous');
    renderAt('/login');

    expect(screen.getByRole('heading', { name: '篝火智答', level: 1 })).toBeDefined();
  });
});
