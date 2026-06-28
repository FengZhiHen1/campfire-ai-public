import { Link } from 'react-router-dom';
import { useProfile } from '@/logics/profiles';
import PageContent from '@/views/_shared/layout/PageContent';
import './ProfileListPage.css';

export default function ProfileListPage() {
  const { profiles, isLoading, fetchProfiles } = useProfile();
  const list = profiles ?? [];

  return (
    <>
      <div className="nav">
        <div className="nav-brand"><span>个人档案</span></div>
        <Link className="nav-edit" to="/profiles/edit">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M11 2l3 3-9 9H2v-3l9-9z"/></svg>
          编辑
        </Link>
      </div>
      <PageContent>
        {list.length > 0 && (
          <div className="chip-scroll">
            {list.map((p, i) => (
              <button key={p.profile_id} className={`chip${i === 0 ? ' active' : ''}`}>
                <div className="chip-avatar">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="9" r="4"/><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8"/></svg>
                </div>
                <span className="chip-name">{p.nickname}</span>
              </button>
            ))}
            <Link className="chip chip-add" to="/profiles/edit">
              <div className="chip-avatar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></div>
              <span className="chip-name">添加</span>
            </Link>
          </div>
        )}

        {isLoading ? (
          <div className="glow-loading" />
        ) : list.length === 0 ? (
          <div className="cold">
            <div className="cold-illust">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="9" r="4"/><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8"/></svg>
            </div>
            <h2>创建孩子的第一份档案</h2>
            <p>完善的档案能帮助 AI 更精准地匹配案例</p>
            <Link className="btn btn-p" to="/profiles/edit">创建档案</Link>
          </div>
        ) : (
          <>
            <div className="info-card">
              <div className="info-head">
                <div className="info-avatar">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="9" r="4"/><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8"/></svg>
                </div>
                <div className="info-meta"><h3>{list[0].nickname}</h3><span>{list[0].age_range}</span></div>
              </div>
              <div className="info-tags">
                <span className="info-tag p">{list[0].diagnosis_type}</span>
                {list[0].primary_behavior && <span className="info-tag r">{list[0].primary_behavior}</span>}
              </div>
            </div>
            <div className="tl-head"><h4>事件记录</h4></div>
            <div className="empty"><div className="emp-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg></div><h3>暂无事件记录</h3><p>记录行为事件以追踪变化趋势</p></div>
          </>
        )}
      </PageContent>
    </>
  );
}
