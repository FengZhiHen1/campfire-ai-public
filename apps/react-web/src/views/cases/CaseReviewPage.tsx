import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import PageContent from '@/views/_shared/layout/PageContent';
import {
  useReviewPage,
  BEHAVIOR_FILTER_OPTIONS,
  BEHAVIOR_DISPLAY_MAP,
} from '@/logics/cases';
import './CaseReviewPage.css';

const FILTERS = ['全部', ...BEHAVIOR_FILTER_OPTIONS.map((o) => o.label)];

const FILTER_VALUE_MAP: Record<string, string> = BEHAVIOR_FILTER_OPTIONS.reduce(
  (acc, { label, value }) => ({ ...acc, [label]: value }),
  {},
);

const AI_SCORE_MAP: Record<string, number> = {
  pass: 100,
  annotated: 75,
  hard_block: 25,
};

export default function CaseReviewPage() {
  const navigate = useNavigate();
  const [activeFilter, setActiveFilter] = useState('全部');
  const {
    queue,
    isLoading,
    error,
    total,
    hasMore,
    actionState,
    handleApprove,
    handleReject,
    loadMore,
  } = useReviewPage();

  const filteredQueue = activeFilter === '全部'
    ? queue
    : queue.filter((item) => item.behavior_type === FILTER_VALUE_MAP[activeFilter]);

  const onReject = (id: string) => {
    const comment = window.prompt('请输入驳回意见（必填）');
    if (comment === null) return;
    void handleReject(id, comment);
  };

  return (
    <>
      <div className="nav">
        <button className="nav-back" onClick={() => navigate(-1)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
        </button>
        <span className="nav-title">审核工作台</span>
      </div>
      <PageContent>
        <div className="filters">
          {FILTERS.map((f) => (
            <button key={f} className={`f-chip${activeFilter === f ? ' active' : ''}`} onClick={() => setActiveFilter(f)}>{f}</button>
          ))}
        </div>

        {error && (
          <div className="error-state active" style={{ padding: '20px 0' }}>
            <p>{error}</p>
          </div>
        )}

        {filteredQueue.map((item) => {
          const aiScore = AI_SCORE_MAP[item.ai_review_overall] ?? 50;
          const busy = actionState.isSubmitting;
          return (
            <div key={item.narrative_id} className="rev-card" onClick={() => navigate(`/cases/${item.narrative_id}`)}>
              <h4>{item.title}</h4>
              <div className="r-tags">
                <span className="r-tag">{BEHAVIOR_DISPLAY_MAP[item.behavior_type] ?? item.behavior_type}</span>
                <span className="r-tag">待审核</span>
              </div>
              <div className="ai-bar">
                <span>AI 预审</span>
                <div className="ai-progress"><div className="ai-fill" style={{ width: `${aiScore}%` }} /></div>
                <span>{Math.round(aiScore / 25)}/4</span>
              </div>
              <div className="r-acts">
                <button
                  className="btn-approve"
                  disabled={busy}
                  onClick={(e) => { e.stopPropagation(); void handleApprove(item.narrative_id); }}
                >
                  通过
                </button>
                <button
                  className="btn-reject"
                  disabled={busy}
                  onClick={(e) => { e.stopPropagation(); onReject(item.narrative_id); }}
                >
                  退回
                </button>
              </div>
            </div>
          );
        })}

        {isLoading && <div style={{ textAlign: 'center', padding: 16, color: 'var(--cf-muted)' }}>加载中…</div>}

        {hasMore && !isLoading && (
          <button className="btn btn-s" onClick={() => void loadMore()} style={{ marginTop: 8 }}>
            加载更多 ({queue.length}/{total})
          </button>
        )}

        {!isLoading && filteredQueue.length === 0 && !error && (
          <div style={{ textAlign: 'center', padding: 40, color: 'var(--cf-muted)' }}>暂无待审核案例</div>
        )}
      </PageContent>
    </>
  );
}
