/**
 * 登录页——手机号 + 密码（ADR-013：登录标识统一为手机号）。
 * 纯 UI + useAuth 编排；登录成功按角色收敛跳转。
 */

import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { homePathForRole, needsReviewStatusPage } from '@/domain/auth';
import { useAuth } from '@/viewModel/auth';
import Button from '@/views/_shared/components/Button';
import './auth.css';

export default function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setError('');
    setSubmitting(true);
    try {
      const user = await login(phone.trim(), password);
      // pending_review/rejected → 状态页；其余按角色收敛导航
      navigate(needsReviewStatusPage(user) ? '/review-status' : homePathForRole(user.role), { replace: true });
    } catch (err) {
      setError((err as Error).message || '登录失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-card__title">篝火智答</h1>
        <p className="auth-card__subtitle">孤独症家庭应急支持平台</p>
        <form className="auth-form" onSubmit={handleSubmit}>
          <div className="auth-field">
            <label className="auth-field__label" htmlFor="login-phone">手机号</label>
            <input
              id="login-phone"
              className="auth-field__input"
              type="tel"
              inputMode="numeric"
              maxLength={11}
              placeholder="请输入 11 位手机号"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              required
            />
          </div>
          <div className="auth-field">
            <label className="auth-field__label" htmlFor="login-password">密码</label>
            <input
              id="login-password"
              className="auth-field__input"
              type="password"
              placeholder="请输入密码"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error && <div className="auth-error" role="alert">{error}</div>}
          <Button type="submit" disabled={submitting}>
            {submitting ? '登录中…' : '登录'}
          </Button>
        </form>
        <div className="auth-links">
          <Link to="/register">邀请码注册</Link>
        </div>
      </div>
    </div>
  );
}
