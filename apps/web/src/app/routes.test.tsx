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

import { describe, expect, it } from 'vitest';
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

    expect(screen.getByRole('heading', { name: '登录篝火智答' })).toBeDefined();
    expect(screen.queryByText('首页：应急入口与日常咨询的起点。')).toBeNull();
  });

  it('P0 未登录访问 /profile 同样转到登录页', () => {
    setSession('anonymous');
    renderAt('/profile');

    expect(screen.getByRole('heading', { name: '登录篝火智答' })).toBeDefined();
  });

  it('P1 已登录访问 /profile 渲染档案占位页', () => {
    setSession('authenticated');
    renderAt('/profile');

    expect(screen.getByRole('heading', { name: '档案' })).toBeDefined();
    expect(screen.getByText('支持对象档案：当前认识、待确认候选与补充。')).toBeDefined();
  });

  it('P1 unknown 态不跳登录页，显示等待态', () => {
    setSession('unknown');
    renderAt('/profile');

    expect(screen.getByText('正在确认登录状态…')).toBeDefined();
    expect(screen.queryByRole('heading', { name: '登录篝火智答' })).toBeNull();
  });

  it('P2 未匹配路径渲染「页面不存在」而不是空白', () => {
    setSession('authenticated');
    renderAt('/nope');

    expect(screen.getByRole('heading', { name: '页面不存在' })).toBeDefined();
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

    expect(screen.getByRole('heading', { name: '登录篝火智答' })).toBeDefined();
  });
});
