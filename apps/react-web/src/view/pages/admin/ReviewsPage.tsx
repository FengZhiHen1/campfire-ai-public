/**
 * 准入审核页（admin）——待审列表 / 通过 / 驳回（含原因）。
 */

import { useState } from 'react';
import { UserRole } from '@campfire/ts-shared/auth';
import { useReviews } from '@/viewModel/auth';
import Button from '@/views/_shared/components/Button';
import '../auth/auth.css';

export default function ReviewsPage() {
  const { items, loading, error, approve, reject } = useReviews();
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [actionError, setActionError] = useState('');

  async function handleApprove(userId: string) {
    setActionError('');
    try {
      await approve(userId);
    } catch (err) {
      setActionError((err as Error).message || '操作失败');
    }
  }

  async function handleRejectSubmit(userId: string) {
    if (!rejectReason.trim()) {
      setActionError('请填写驳回原因');
      return;
    }
    setActionError('');
    try {
      await reject(userId, rejectReason.trim());
      setRejectingId(null);
      setRejectReason('');
    } catch (err) {
      setActionError((err as Error).message || '操作失败');
    }
  }

  return (
    <div className="admin-page">
      <h1 className="admin-page__title">准入审核</h1>
      <p className="admin-page__desc">老师/专家注册审核——通过后账号激活，驳回需填写面向用户的原因</p>

      <section className="admin-section">
        <h2 className="admin-section__title">待审核（{items.length}）</h2>
        {loading && <p className="auth-field__hint">加载中…</p>}
        {error && <div className="auth-error">{error}</div>}
        {actionError && <div className="auth-error">{actionError}</div>}
        {!loading && items.length === 0 && <p className="auth-field__hint">暂无待审核账号</p>}
        <div className="admin-list">
          {items.map((item) => (
            <div key={item.user_id} className="admin-list__item" style={{ alignItems: 'flex-start' }}>
              <div className="admin-list__meta">
                <span className="admin-list__primary">
                  {item.real_name || '（未填写姓名）'}{' '}
                  <span className="admin-tag">{item.role === UserRole.TEACHER ? '老师' : '专家'}</span>
                </span>
                <span className="admin-list__secondary">
                  {item.phone} · 申请于 {new Date(item.created_at).toLocaleString('zh-CN')}
                </span>
                {rejectingId === item.user_id && (
                  <div className="auth-field" style={{ marginTop: 8 }}>
                    <input
                      className="auth-field__input"
                      type="text"
                      maxLength={200}
                      placeholder="驳回原因（将展示给用户）"
                      value={rejectReason}
                      onChange={(e) => setRejectReason(e.target.value)}
                    />
                  </div>
                )}
              </div>
              <div className="admin-list__actions">
                {rejectingId === item.user_id ? (
                  <>
                    <Button variant="secondary" onClick={() => void handleRejectSubmit(item.user_id)}>确认驳回</Button>
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setRejectingId(null);
                        setRejectReason('');
                      }}
                    >
                      取消
                    </Button>
                  </>
                ) : (
                  <>
                    <Button variant="secondary" onClick={() => void handleApprove(item.user_id)}>通过</Button>
                    <Button variant="ghost" onClick={() => setRejectingId(item.user_id)}>驳回</Button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
