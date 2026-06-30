import { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useConsult } from '@/logics/consult';
import type { ConsultationHistoryDetail } from '@/logics/consult';
import { CARD_STATUS_MAP } from '@/logics/cases';
import PageContent from '@/views/_shared/layout/PageContent';
import './ConsultDetailPage.css';

const CRISIS_LABELS: Record<string, string> = {
  mild: '轻度危机', moderate: '中度危机', severe: '重度危机',
};

function getSectionClass(title: string): string {
  if (title.includes('安全') || title.includes('即时')) return 'action';
  if (title.includes('安抚') || title.includes('话术') || title.includes('情绪')) return 'soothe';
  if (title.includes('就医') || title.includes('医疗') || title.includes('判断')) return 'medical';
  if (title.includes('观察')) return 'observe';
  return '';
}

function formatFinishReason(reason?: string): string {
  if (!reason) return '已完成';
  if (reason === 'COMPLETE') return '完整生成';
  if (reason === 'PARTIAL') return '部分生成';
  if (reason === 'BLOCKED') return '安全拦截';
  return reason;
}

function formatConsultTime(isoString?: string): string {
  if (!isoString) return '';
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return isoString;

  const now = new Date();
  const timeStr = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });

  const isSameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();

  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);

  if (isSameDay(date, now)) return `今天 ${timeStr}`;
  if (isSameDay(date, yesterday)) return `昨天 ${timeStr}`;

  const weekdayStr = date.toLocaleDateString('zh-CN', { weekday: 'short' });
  if (date.getFullYear() === now.getFullYear()) {
    const dateStr = date.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' });
    return `${dateStr} ${weekdayStr} ${timeStr}`;
  }

  const dateStr = date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
  return `${dateStr} ${weekdayStr} ${timeStr}`;
}

export default function ConsultDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const consult = useConsult();
  const [detail, setDetail] = useState<ConsultationHistoryDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true); setError(null);
    try {
      const res = await consult.fetchHistoryDetail(id);
      setDetail(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally { setLoading(false); }
  }, [id, consult]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <PageContent><div className="glow-loading" /></PageContent>;
  if (error || !detail) {
    return (
      <PageContent>
        <div className="error-state">
          <div className="err-graphic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></div>
          <h2>加载失败</h2>
          <p>{error ?? '无法加载咨询详情，请稍后重试'}</p>
          <div className="error-acts"><button className="btn-s" onClick={load}>重试</button></div>
        </div>
      </PageContent>
    );
  }

  const crisisClass = detail.crisis_level ?? 'moderate';
  const planSections = Object.entries(detail.plan_sections ?? {});
  const referencedCases = detail.referenced_cases ?? [];
  const genSeconds = detail.generation_time_ms ? (detail.generation_time_ms / 1000).toFixed(1) : null;

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
            <span className="crisis-time" title={detail.consultation_time}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                <line x1="16" y1="2" x2="16" y2="6" />
                <line x1="8" y1="2" x2="8" y2="6" />
                <line x1="3" y1="10" x2="21" y2="10" />
              </svg>
              {formatConsultTime(detail.consultation_time)}
            </span>
          </div>
          <div className="crisis-desc">{detail.behavior_description}</div>
        </div>

        {detail.is_partial && (
          <div className="partial-warning">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
            以下方案未完整生成，仅供参考
          </div>
        )}

        <div className="plan-card">
          <h3>干预建议大纲</h3>
          {planSections.length > 0 ? (
            planSections.map(([title, contents], i) => (
              <div key={i} className={`plan-section ${getSectionClass(title)}`}>
                <div className="plan-section-head"><span>{title}</span></div>
                <div className="plan-section-body">
                  {contents.map((line, idx) => (
                    <p key={idx}>{line}</p>
                  ))}
                </div>
              </div>
            ))
          ) : detail.generated_plan ? (
            <div className="plan-section">
              <div className="plan-section-body raw-plan">
                {detail.generated_plan.split(/\n|。/).filter(Boolean).map((line, idx) => (
                  <p key={idx}>{line.trim()}</p>
                ))}
              </div>
            </div>
          ) : (
            <div className="plan-section empty">
              <div className="plan-section-body">暂无干预建议内容</div>
            </div>
          )}
          <div className="plan-footer">
            <span className="case-count">基于 {detail.referenced_slice_ids.length} 个相似案例</span>
            {genSeconds && <span className="gen-time">生成耗时 {genSeconds}s</span>}
          </div>
        </div>

        {referencedCases.length > 0 && (
          <details className="ref-cases" open>
            <summary>参考案例（{referencedCases.length}）</summary>
            {referencedCases.map((c, idx) => (
              <Link key={idx} className="ref-case-item" to={`/cases/${c.case_id}`}>
                <div className="case-id">{c.case_id}</div>
                <div>{c.slice_text || c.case_title}</div>
              </Link>
            ))}
          </details>
        )}

        {(detail.associated_cards ?? []).length > 0 && (
          <div className="associated-cards">
            <h3>关联卡片 <span className="count">({(detail.associated_cards ?? []).length})</span></h3>
            {(detail.associated_cards ?? []).map((card) => {
              const status = CARD_STATUS_MAP[card.review_status] ?? { text: card.review_status, cls: card.review_status };
              return (
                <button
                  key={card.card_id}
                  type="button"
                  className="assoc-card-item"
                  onClick={() => navigate(`/cases/card/${card.card_id}`)}
                >
                  <h4>{card.title}</h4>
                  <div className="assoc-card-tags">
                    <span className="assoc-card-tag">{card.behavior_type}</span>
                    <span className="assoc-card-tag">{card.severity}</span>
                    <span className="assoc-card-tag">{card.scene}</span>
                  </div>
                  <span className={`assoc-card-status ${status.cls}`}>{status.text}</span>
                </button>
              );
            })}
          </div>
        )}

        <div className="disclaimer-block">基于归档案例的 AI 生成建议，不构成医疗诊断。严重情况请咨询专业医生。</div>

        <div className="meta-footer">
          {genSeconds && <span className="meta-tag">⚡ 生成耗时 {genSeconds}s</span>}
          <span className="meta-tag finish">✓ {formatFinishReason(detail.finish_reason)}</span>
        </div>
      </PageContent>

      <div className="action-bar">
        <Link className="btn" to="/consult/select">开始新咨询</Link>
      </div>
    </>
  );
}
