import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useCaseList } from '@/logics/cases/hooks/useCaseList';
import PageContent from '@/views/_shared/layout/PageContent';
import './CaseListPage.css';

export default function CaseListPage() {
  const [tab, setTab] = useState<'public' | 'my'>('public');
  const { list, loading, search, setSearch } = useCaseList({});

  return (
    <>
      <div className="nav">
        <span className="nav-title">真实案例库</span>
        <Link className="nav-act" to="/cases/review">审核台</Link>
      </div>
      <PageContent>
        <div className="tabs">
          <button className={`tab${tab === 'public' ? ' active' : ''}`} onClick={() => setTab('public')}>公共案例库</button>
          <button className={`tab${tab === 'my' ? ' active' : ''}`} onClick={() => setTab('my')}>我的提交</button>
        </div>
        <div className="search">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.6" y2="16.6"/></svg>
          <input placeholder="搜索案例库…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        {loading ? <div className="glow-loading" /> : list.map((item) => (
          <Link key={item.id} className="case-card" to={`/cases/${item.id}`}>
            <div className="card-head"><span className="card-title">{item.title}</span><span className="card-badge">{item.source}</span></div>
            <div className="card-tags">{item.tags?.map((t: string) => <span key={t} className="card-tag">{t}</span>)}</div>
            <div className="card-foot"><span className="card-dot approved" /><span className="card-status">{item.status}</span><span className="card-time">{item.date}</span></div>
          </Link>
        ))}
        <div className="no-more">—— 已展示全部案例 ——</div>
      </PageContent>
      <Link className="fab" to="/cases/narrative">+</Link>
    </>
  );
}
