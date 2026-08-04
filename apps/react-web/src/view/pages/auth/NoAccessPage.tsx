/**
 * 无业务能力提示页——maintainer（系统运维无 Web 业务权限）与越权访问的落点。
 */

import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/viewModel/auth';
import Button from '@/views/_shared/components/Button';
import './auth.css';

export default function NoAccessPage() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  async function handleLogout() {
    await logout();
    navigate('/login', { replace: true });
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-card__title">无可用功能</h1>
        <p className="auth-card__subtitle">
          {user?.role === 'maintainer'
            ? '维护人员账号无业务数据权限，请使用运维通道（健康检查/监控）。'
            : '当前角色无权访问该功能。'}
        </p>
        <Button variant="secondary" onClick={() => void handleLogout()}>退出登录</Button>
      </div>
    </div>
  );
}
