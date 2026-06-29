import { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useConsult } from '@/logics/consult';
import type { ConsultationHistoryListItem } from '@/logics/consult';
import PageContent from '@/views/_shared/layout/PageContent';
import './ConsultHistoryPage.css';

const CRISIS_LABELS: Record<string, string> = {
  mild: '轻度', moderate: '中度', severe: '重度',
};

function getTrust(item: ConsultationHistoryListItem): [string, string] {
  if (item.crisis_level === 'mild') return ['高可信', 'high'];
  if (item.crisis_level === 'severe') return ['需复核', 'low'];
  return ['中可信', 'medium'];
}

export default function ConsultHistoryPage() {
  const navigate = useNavigate();
  const consult = useConsult();
  const [items, setItems] = useState<ConsultationHistoryListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await consult.fetchHistoryList(1, 50);
      setItems(list ?? []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally { setLoading(false); }
  }, [consult]);

  useEffect(() => { load(); }, [load]);

  const filtered = search
    ? items.filter((i) => {
        const q = search.toLowerCase();
        const inDesc = i.behavior_description?.toLowerCase().includes(q);
        const inTags = i.tags?.some((t) => t.toLowerCase().includes(q));
        return inDesc || inTags;
      })
    : items;

  return (
    <>
      <div className="nav">
        <button className="nav-back" onClick={() => navigate(-1)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <span className="nav-title">咨询历史</span>
      </div>
      <PageContent>
        <div className="search">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.6" y2="16.6" />
          </svg>
          <input placeholder="搜索历史咨询记录…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>

        {error && (
          <div className="empty">
            <div className="emp-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
            <h3>加载失败</h3>
            <p>{error}</p>
            <button type="button" className="btn btn-p" onClick={load}>重新加载</button>
          </div>
        )}

        {loading ? (
          <div className="glow-loading" />
        ) : filtered.length === 0 ? (
          <div className="empty">
            <div className="emp-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
              </svg>
            </div>
            <h3>暂无咨询记录</h3>
            <p>当需要应急建议时，前往应急咨询页面发起对话</p>
            <Link className="btn btn-p" to="/consult/select">前往咨询</Link>
          </div>
        ) : (
          <>
            {filtered.map((item, idx) => {
              const [trustLabel, trustClass] = getTrust(item);
              return (
                <Link key={item.id} className="card" to={`/consult/${item.id}`}>
                  <div className="card-head">
                    <span className="card-level">
                      <span className={`dot ${item.crisis_level}`} />
                      {CRISIS_LABELS[item.crisis_level] ?? item.crisis_level}
                    </span>
                    {item.has_feedback && (
                      <span className="feedback-mark">
                        <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="10 3 5 8 2 5" /></svg>
                        已反馈
                      </span>
                    )}
                    <span className="card-time">{item.consultation_time}</span>
                    <span className={`trust ${trustClass}`}>{trustLabel}</span>
                  </div>
                  {item.tags && item.tags.length > 0 && (
                    <div className="tags">
                      {item.tags.map((tag, tidx) => (
                        <span key={tidx} className="tag">{tag}</span>
                      ))}
                    </div>
                  )}
                  <p className="summary">{item.behavior_description}</p>
                </Link>
              );
            })}
            <div className="load-more end">已加载全部记录</div>
          </>
        )}
      </PageContent>
    </>
  );
}
