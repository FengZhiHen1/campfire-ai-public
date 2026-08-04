/**
 * 邀请码管理页（admin）——生成（含批量）/ 列表 / 停用。
 */

import { useState } from 'react';
import type { FormEvent } from 'react';
import { InviteChannel, InviteCodeStatus } from '@campfire/ts-shared/auth';
import { useInviteCodes } from '@/viewModel/auth';
import Button from '@/views/_shared/components/Button';
import '../auth/auth.css';

export default function InviteCodesPage() {
  const { items, loading, error, create, revoke } = useInviteCodes();
  const [channel, setChannel] = useState<InviteChannel>(InviteChannel.DEMAND);
  const [maxUses, setMaxUses] = useState(1);
  const [count, setCount] = useState(1);
  const [expiresAt, setExpiresAt] = useState('');
  const [generatedCodes, setGeneratedCodes] = useState<string[]>([]);
  const [submitError, setSubmitError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setSubmitError('');
    setGeneratedCodes([]);
    if (!expiresAt) {
      setSubmitError('请选择过期时间');
      return;
    }
    setSubmitting(true);
    try {
      const codes = await create({
        channel,
        max_uses: maxUses,
        count,
        expires_at: new Date(expiresAt).toISOString(),
      });
      setGeneratedCodes(codes);
    } catch (err) {
      setSubmitError((err as Error).message || '生成失败');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="admin-page">
      <h1 className="admin-page__title">邀请码管理</h1>
      <p className="admin-page__desc">内测期注册准入：需求侧码（家属/志愿者）、供给侧码（老师/专家）</p>

      <section className="admin-section">
        <h2 className="admin-section__title">生成邀请码</h2>
        <form className="auth-form" onSubmit={handleCreate}>
          <div className="auth-field">
            <label className="auth-field__label" htmlFor="ic-channel">渠道</label>
            <select
              id="ic-channel"
              className="auth-field__select"
              value={channel}
              onChange={(e) => setChannel(e.target.value as InviteChannel)}
            >
              <option value={InviteChannel.DEMAND}>需求侧（家属/志愿者）</option>
              <option value={InviteChannel.SUPPLY}>供给侧（老师/专家）</option>
            </select>
          </div>
          <div className="auth-field">
            <label className="auth-field__label" htmlFor="ic-maxuses">单码可用次数</label>
            <input
              id="ic-maxuses"
              className="auth-field__input"
              type="number"
              min={1}
              max={1000}
              value={maxUses}
              onChange={(e) => setMaxUses(Number(e.target.value) || 1)}
            />
          </div>
          <div className="auth-field">
            <label className="auth-field__label" htmlFor="ic-count">生成数量</label>
            <input
              id="ic-count"
              className="auth-field__input"
              type="number"
              min={1}
              max={100}
              value={count}
              onChange={(e) => setCount(Number(e.target.value) || 1)}
            />
            <span className="auth-field__hint">机构批量邀请：按人数生成单次码</span>
          </div>
          <div className="auth-field">
            <label className="auth-field__label" htmlFor="ic-expires">过期时间</label>
            <input
              id="ic-expires"
              className="auth-field__input"
              type="datetime-local"
              value={expiresAt}
              onChange={(e) => setExpiresAt(e.target.value)}
              required
            />
          </div>
          {submitError && <div className="auth-error" role="alert">{submitError}</div>}
          <Button type="submit" disabled={submitting}>
            {submitting ? '生成中…' : '生成'}
          </Button>
        </form>
        {generatedCodes.length > 0 && (
          <div className="admin-code-list">
            {generatedCodes.map((c) => (
              <span key={c} className="admin-code-chip">{c}</span>
            ))}
          </div>
        )}
      </section>

      <section className="admin-section">
        <h2 className="admin-section__title">已生成（{items.length}）</h2>
        {loading && <p className="auth-field__hint">加载中…</p>}
        {error && <div className="auth-error">{error}</div>}
        {!loading && !error && items.length === 0 && <p className="auth-field__hint">暂无邀请码</p>}
        <div className="admin-list">
          {items.map((item) => (
            <div key={item.code} className="admin-list__item">
              <div className="admin-list__meta">
                <span className="admin-list__primary">
                  {item.code}{' '}
                  <span className={item.status === InviteCodeStatus.ACTIVE ? 'admin-tag' : 'admin-tag admin-tag--muted'}>
                    {item.status === InviteCodeStatus.ACTIVE ? '有效' : '已停用'}
                  </span>
                </span>
                <span className="admin-list__secondary">
                  {item.channel === InviteChannel.DEMAND ? '需求侧' : '供给侧'} · 已用 {item.used_count}/{item.max_uses} ·{' '}
                  {new Date(item.expires_at).toLocaleString('zh-CN')} 过期
                </span>
              </div>
              {item.status === InviteCodeStatus.ACTIVE && (
                <div className="admin-list__actions">
                  <Button variant="ghost" onClick={() => void revoke(item.code)}>停用</Button>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
