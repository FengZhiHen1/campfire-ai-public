/**
 * 注册页——手机号 + 密码 + 邀请码 + 角色选择（认证与访问 §4.2）。
 * 角色选项受邀请码渠道约束由后端校验；teacher/expert 显示 real_name 必填。
 * 注册成功不自动登录，引导至登录页。
 */

import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { REVIEW_REQUIRED_ROLES, UserRole } from '@campfire/ts-shared/auth';
import { useAuth } from '@/viewModel/auth';
import Button from '@/views/_shared/components/Button';
import './auth.css';

const ROLE_OPTIONS: Array<{ value: UserRole; label: string }> = [
  { value: UserRole.FAMILY, label: '家属' },
  { value: UserRole.VOLUNTEER, label: '志愿者' },
  { value: UserRole.TEACHER, label: '老师' },
  { value: UserRole.EXPERT, label: '专家' },
];

export default function RegisterPage() {
  const navigate = useNavigate();
  const { register } = useAuth();
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [inviteCode, setInviteCode] = useState('');
  const [role, setRole] = useState<UserRole>(UserRole.FAMILY);
  const [realName, setRealName] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const needsRealName = REVIEW_REQUIRED_ROLES.includes(role);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setError('');
    setSubmitting(true);
    try {
      const result = await register({
        phone: phone.trim(),
        password,
        invite_code: inviteCode.trim(),
        role,
        real_name: realName.trim() || null,
      });
      // 注册成功 → 引导登录（pending_review 提示审核语义）
      navigate('/login', {
        replace: true,
        state: { message: result.message },
      });
    } catch (err) {
      setError((err as Error).message || '注册失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-card__title">邀请码注册</h1>
        <p className="auth-card__subtitle">内测期凭邀请码注册</p>
        <form className="auth-form" onSubmit={handleSubmit}>
          <div className="auth-field">
            <label className="auth-field__label" htmlFor="reg-invite">邀请码</label>
            <input
              id="reg-invite"
              className="auth-field__input"
              type="text"
              maxLength={12}
              placeholder="8-12 位邀请码"
              value={inviteCode}
              onChange={(e) => setInviteCode(e.target.value)}
              required
            />
            <span className="auth-field__hint">需求侧码可注册家属/志愿者；供给侧码可注册老师/专家</span>
          </div>
          <div className="auth-field">
            <label className="auth-field__label" htmlFor="reg-role">角色</label>
            <select
              id="reg-role"
              className="auth-field__select"
              value={role}
              onChange={(e) => setRole(e.target.value as UserRole)}
            >
              {ROLE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          <div className="auth-field">
            <label className="auth-field__label" htmlFor="reg-phone">手机号</label>
            <input
              id="reg-phone"
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
            <label className="auth-field__label" htmlFor="reg-password">密码</label>
            <input
              id="reg-password"
              className="auth-field__input"
              type="password"
              placeholder="至少 8 位，含大小写字母和数字"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {needsRealName && (
            <div className="auth-field">
              <label className="auth-field__label" htmlFor="reg-realname">真实姓名</label>
              <input
                id="reg-realname"
                className="auth-field__input"
                type="text"
                maxLength={20}
                placeholder="老师/专家必填，用于准入审核"
                value={realName}
                onChange={(e) => setRealName(e.target.value)}
                required
              />
              <span className="auth-field__hint">老师/专家注册后需管理员审核，审核通过后可使用全部功能</span>
            </div>
          )}
          {error && <div className="auth-error" role="alert">{error}</div>}
          <Button type="submit" disabled={submitting}>
            {submitting ? '注册中…' : '注册'}
          </Button>
        </form>
        <div className="auth-links">
          <Link to="/login">已有账号，去登录</Link>
        </div>
      </div>
    </div>
  );
}
