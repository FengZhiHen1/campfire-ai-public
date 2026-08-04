/**
 * 登录守卫布局（认证与访问 §3.2 / §六）：
 * - 应用启动恢复会话（localStorage token → /me）
 * - 未登录 → /login
 * - pending_review/rejected → 仅见 /review-status
 * - /admin/* 仅 admin；maintainer 无业务能力 → /no-access
 */

import { useEffect, useRef } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { needsReviewStatusPage, UserRole } from '@/domain/auth';
import { useAuth } from '@/viewModel/auth';

export default function AuthGuardLayout() {
  const { user, sessionState, restoreSession } = useAuth();
  const location = useLocation();
  const restoredRef = useRef(false);

  useEffect(() => {
    if (!restoredRef.current) {
      restoredRef.current = true;
      void restoreSession();
    }
  }, [restoreSession]);

  if (sessionState === 'loading') {
    return (
      <div className="auth-page">
        <p style={{ color: 'var(--cf-muted)' }}>加载中…</p>
      </div>
    );
  }

  if (sessionState === 'unauthenticated') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  if (user && needsReviewStatusPage(user)) {
    // 审核中/已驳回：仅见状态页
    if (location.pathname !== '/review-status') {
      return <Navigate to="/review-status" replace />;
    }
    return <Outlet />;
  }

  if (user) {
    // /admin/* 仅 admin
    if (location.pathname.startsWith('/admin') && user.role !== UserRole.ADMIN) {
      return <Navigate to="/no-access" replace />;
    }
    // maintainer 无业务能力（系统运维走健康/监控通道，无 Web 业务页）
    if (user.role === UserRole.MAINTAINER && location.pathname !== '/no-access') {
      return <Navigate to="/no-access" replace />;
    }
  }

  return <Outlet />;
}
