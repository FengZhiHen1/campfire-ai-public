/**
 * 咨询历史页——新会话模型（行为桶/阶段/轮次数/时间）。
 */

import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { consultApi } from '@/logics/consult';
import type { ConsultHistoryItem } from '@/logics/consult';
import PageContent from '@/views/_shared/layout/PageContent';
import './ConsultHistoryPage.css';

const BUCKET_LABELS: Record<string, string> = {
  情绪崩溃: '情绪哭闹',
  刻板行为: '刻板升级',
  自伤: '自伤',
  攻击: '攻击',
  走失: '走失',
  用药相关: '用药',
  社交退缩: '社交退缩',
  多动: '多动',
  其他: '其他',
};

const REDLINE_SET = new Set(['自伤', '攻击', '走失', '用药相关']);

export default function ConsultHistoryPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<ConsultHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await consultApi.fetchHistoryList(1, 50);
      setItems(result.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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
        {error && (
          <div className="empty">
            <h3>加载失败</h3>
            <p>{error}</p>
            <button type="button" className="btn btn-p" onClick={() => void load()}>重新加载</button>
          </div>
        )}

        {loading ? (
          <div className="glow-loading" />
        ) : items.length === 0 ? (
          <div className="empty">
            <h3>暂无咨询记录</h3>
            <p>当需要应急建议时，前往应急咨询页面发起对话</p>
            <Link className="btn btn-p" to="/consult">前往咨询</Link>
          </div>
        ) : (
          <>
            {items.map((item) => (
              <Link key={item.id} className="card" to={`/consult/session/${item.id}`}>
                <div className="card-head">
                  <span className="card-level">
                    <span className={`dot ${REDLINE_SET.has(item.bucket) ? 'severe' : 'mild'}`} />
                    {BUCKET_LABELS[item.bucket] ?? item.bucket}
                  </span>
                  <span className="card-time">{new Date(item.created_at).toLocaleString('zh-CN')}</span>
                </div>
                <p className="summary">
                  {item.crisis_stage ? `阶段：${item.crisis_stage} · ` : ''}共 {item.turn_count} 轮
                </p>
              </Link>
            ))}
            <div className="load-more end">已加载全部记录</div>
          </>
        )}
      </PageContent>
    </>
  );
}
