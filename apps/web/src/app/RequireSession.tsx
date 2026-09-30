/**
 * 模块: app/RequireSession
 * 职责: 登录守卫的体验层——未登录或未查证时决定渲染内容或转登录页
 * 数据来源:
 *   - docs/项目结构设计.md: MUST — 第 9 节（前端守卫只负责体验，不构成权限证明）
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 6 节
 * 边界:
 *   - 依赖: features/accounts/viewModel/sessionStore
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止把本组件当作权限判定（真正的判定在服务端；它只避免让未登录用户看到空壳页面）
 *   - 禁止在 unknown 态直接判定为未登录而跳转（会把冷启动的已登录用户弹走）
 */

import type { ReactNode } from 'react';
import { Navigate } from 'react-router';

import { useSessionStore } from '../features/accounts/viewModel/sessionStore';

/** 守卫 props：被保护的子树，以及是否启用守卫。 */
export interface RequireSessionProps {
  children: ReactNode;
  /** 关掉守卫时直接渲染 children；/login 之外的路由表默认全开。 */
  enabled?: boolean;
}

/**
 * 渲染受保护子树，或在未登录时转登录页。
 *
 * 前置: 无
 * 后置: enabled 为假时直接渲染 children；authenticated 渲染 children；
 *       anonymous 转 /login；unknown 渲染等待态
 * 异常: 无
 *
 * 这里的判断只影响「用户看到什么」，不影响任何数据可达性——后端逐请求查证会话
 * （认证与账号第 6 节），因此绕过本组件不会获得任何越权能力。
 */
export function RequireSession({ children, enabled = true }: RequireSessionProps) {
  const status = useSessionStore((state) => state.session.status);

  if (!enabled || status === 'authenticated') {
    return <>{children}</>;
  }

  if (status === 'anonymous') {
    return <Navigate to="/login" replace />;
  }

  return (
    <section className="page" aria-live="polite">
      <p className="status-note">正在确认登录状态…</p>
    </section>
  );
}
