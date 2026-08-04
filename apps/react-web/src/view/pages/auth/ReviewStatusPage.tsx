/**
 * 准入状态页——pending_review / rejected 用户登录后唯一可见页面。
 * pending_review：审核中提示（轮询状态）；rejected：显示驳回原因 + 补交材料重提。
 */

import { useState } from 'react';
import type { FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { AccountStatus, homePathForRole } from '@/domain/auth';
import { useAuth } from '@/viewModel/auth';
import Button from '@/views/_shared/components/Button';
import './auth.css';

export default function ReviewStatusPage() {
  const navigate = useNavigate();
  const { user, logout, refreshUser, resubmitReview } = useAuth();
  const [realName, setRealName] = useState(user?.realName ?? '');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [checking, setChecking] = useState(false);

  if (!user) return null;

  const isPending = user.status === AccountStatus.PENDING_REVIEW;
  const isRejected = user.status === AccountStatus.REJECTED;

  /** 刷新状态：审核通过 → 进入角色首页 */
  async function handleRefresh() {
    setChecking(true);
    try {
      const latest = await refreshUser();
      if (latest.status === AccountStatus.ACTIVE) {
        navigate(homePathForRole(latest.role), { replace: true });
      }
    } finally {
      setChecking(false);
    }
  }

  async function handleResubmit(e: FormEvent) {
    e.preventDefault();
    if (submitting || !user) return;
    setError('');
    setSubmitting(true);
    try {
      await resubmitReview(realName.trim() || null);
    } catch (err) {
      setError((err as Error).message || '提交失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  }

  async function handleLogout() {
    await logout();
    navigate('/login', { replace: true });
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        {isPending && (
          <>
            <h1 className="auth-card__title">审核中</h1>
            <p className="auth-card__subtitle">
              您的{user.role === 'teacher' ? '老师' : '专家'}账号已提交审核，请等待管理员处理。
            </p>
            <Button onClick={handleRefresh} disabled={checking}>
              {checking ? '查询中…' : '刷新审核状态'}
            </Button>
          </>
        )}
        {isRejected && (
          <>
            <h1 className="auth-card__title">审核未通过</h1>
            <p className="auth-card__subtitle">
              {user.rejectReason ? `驳回原因：${user.rejectReason}` : '请补充材料后重新提交审核'}
            </p>
            <form className="auth-form" onSubmit={handleResubmit}>
              <div className="auth-field">
                <label className="auth-field__label" htmlFor="resubmit-name">真实姓名</label>
                <input
                  id="resubmit-name"
                  className="auth-field__input"
                  type="text"
                  maxLength={20}
                  value={realName}
                  onChange={(e) => setRealName(e.target.value)}
                  required
                />
              </div>
              {error && <div className="auth-error" role="alert">{error}</div>}
              <Button type="submit" disabled={submitting}>
                {submitting ? '提交中…' : '重新提交审核'}
              </Button>
            </form>
          </>
        )}
        <div className="auth-links">
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              void handleLogout();
            }}
          >
            退出登录
          </a>
        </div>
      </div>
    </div>
  );
}
