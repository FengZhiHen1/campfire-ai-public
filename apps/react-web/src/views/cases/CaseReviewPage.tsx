import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import PageContent from '@/views/_shared/layout/PageContent';
import './CaseReviewPage.css';

const FILTERS = ['全部', '自伤', '攻击', '逃跑', '服药', '情绪'];
const MOCK_ITEMS = [
  { id: 1, title: '商场听觉超载自伤案例', tags: ['自伤行为', '公共场合', '待审核'], aiScore: 75 },
  { id: 2, title: '学校转换困难逃跑干预', tags: ['出走/逃跑', '学校', '待审核'], aiScore: 100 },
  { id: 3, title: '拒绝服药大哭大闹案例', tags: ['用药相关', '家庭', '待审核'], aiScore: 25 },
];

export default function CaseReviewPage() {
  const navigate = useNavigate();
  const [activeFilter, setActiveFilter] = useState('全部');
  const [items, setItems] = useState(MOCK_ITEMS);

  const handleAction = (id: number) => setItems((prev) => prev.filter((i) => i.id !== id));

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
        {items.map((item) => (
          <div key={item.id} className="rev-card" onClick={() => navigate(`/cases/${item.id}`)}>
            <h4>{item.title}</h4>
            <div className="r-tags">{item.tags.map((t) => <span key={t} className="r-tag">{t}</span>)}</div>
            <div className="ai-bar"><span>AI 预审</span><div className="ai-progress"><div className="ai-fill" style={{ width: `${item.aiScore}%` }} /></div><span>{Math.round(item.aiScore / 25)}/4</span></div>
            <div className="r-acts">
              <button className="btn-approve" onClick={(e) => { e.stopPropagation(); handleAction(item.id); }}>通过</button>
              <button className="btn-reject" onClick={(e) => { e.stopPropagation(); handleAction(item.id); }}>退回</button>
            </div>
          </div>
        ))}
      </PageContent>
    </>
  );
}
