import { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { consultApi } from '@/logics/consult';
import type { ConsultationHistoryDetail } from '@/logics/consult';
import PageContent from '@/views/_shared/layout/PageContent';
import './ConsultDetailPage.css';

const CRISIS_LABELS: Record<string, string> = {
  mild: '轻度危机', moderate: '中度危机', severe: '重度危机',
};

export default function ConsultDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ConsultationHistoryDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true); setError(false);
    try {
      const res = await consultApi.fetchHistoryDetail(id);
      setDetail(res);
    } catch { setError(true); }
    finally { setLoading(false); }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <PageContent><div className="glow-loading" /></PageContent>;
  if (error || !detail) {
    return (
      <PageContent>
        <div className="error-state">
          <div className="err-graphic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></div>
          <h2>加载失败</h2>
          <p>无法加载咨询详情，请稍后重试</p>
          <div className="error-acts"><button className="btn-s" onClick={load}>重试</button></div>
        </div>
      </PageContent>
    );
  }

  const crisisClass = detail.crisis_level ?? 'moderate';
  const planSections = detail.plan_sections ?? [];

  return (
    <>
      <div className="nav">
        <button className="nav-back" onClick={() => navigate(-1)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
        </button>
        <span className="nav-title">咨询详情</span>
      </div>
      <PageContent>
        <div className="crisis-header">
          <div className="crisis-badge-row">
            <span className={`crisis-badge ${crisisClass}`}>{CRISIS_LABELS[crisisClass] ?? crisisClass}</span>
            <span className="crisis-time">{detail.consultation_time}</span>
          </div>
          <div className="crisis-desc">{detail.behavior_description}</div>
        </div>

        <div className="plan-card">
          <h3>干预建议大纲</h3>
          {planSections.map((s, i) => (
            <div key={i} className={`plan-section ${s.type ?? 'action'}`}>
              <div className="plan-section-head"><span>{s.title ?? `段落 ${i + 1}`}</span></div>
              <div className="plan-section-body" dangerouslySetInnerHTML={{ __html: s.content ?? '' }} />
            </div>
          ))}
          <div className="plan-footer">
            <span className="case-count">基于 {detail.referenced_case_count ?? 0} 个相似案例</span>
          </div>
        </div>

        <div className="disclaimer-block">基于归档案例的 AI 生成建议，不构成医疗诊断。严重情况请咨询专业医生。</div>

        <div className="meta-footer">
          <span className="meta-tag finish">✓ 已完成</span>
        </div>
      </PageContent>

      <div className="action-bar">
        <Link className="btn" to="/consult/select">开始新咨询</Link>
      </div>
    </>
  );
}
