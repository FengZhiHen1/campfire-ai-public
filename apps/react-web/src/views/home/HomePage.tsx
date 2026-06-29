import { Link } from 'react-router-dom';
import { useHomePage, formatRelativeTime } from '@/logics/shared';
import PageContent from '@/views/_shared/layout/PageContent';
import './HomePage.css';

/* ── Time-based greeting (OD home.html L499-503) ── */
function getGreeting(): string {
  const h = new Date().getHours();
  return h >= 5 && h < 12 ? '早上好' : h >= 12 && h < 18 ? '下午好' : '晚上好';
}

export default function HomePage() {
  const { loading, hasError, consultHistory, profiles, profilesLoading, load } =
    useHomePage();
  const profilesSafe = profiles ?? [];
  const hasProfiles = profilesSafe.length > 0;
  const latestConsult = consultHistory?.[0];

  return (
    <PageContent>
      {/* ═══ Greeting ═══ */}
      <div className="greeting">
        <div className="greeting-brand">
          <div className="greeting-flame">
            <svg viewBox="0 0 28 28" fill="none">
              <path d="M14 2 C8 10 6 14 6 18 A8 8 0 0 0 22 18 C22 14 20 10 14 2Z" fill="var(--cf-accent)" opacity="0.25" />
              <path d="M14 7 C10 12 9 15 9 18 A5 5 0 0 0 19 18 C19 15 18 12 14 7Z" fill="var(--cf-accent)" opacity="0.45" />
              <circle cx="14" cy="18" r="2.5" fill="var(--cf-accent)" />
            </svg>
          </div>
          <span className="greeting-brand-name">篝火智答</span>
        </div>
        <h1 className="greeting-title">{getGreeting()}</h1>
        <p className="greeting-subtitle">
          {hasProfiles ? '今天孩子状态怎么样？' : '欢迎开始使用篝火智答'}
        </p>
      </div>

      {/* ═══ Error Banner（仅 hasError 时显示） ═══ */}
      {hasError && (
        <div className="error-banner">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <span>数据加载失败</span>
          <button type="button" onClick={load}>重试</button>
        </div>
      )}

      {/* ═══ Emergency Card ═══ */}
      <Link className="card-emergency" to="/consult">
        <div className="card-emergency-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M12 9v5" />
            <circle cx="12" cy="16" r="1" fill="currentColor" stroke="none" />
            <circle cx="12" cy="12" r="9" />
          </svg>
        </div>
        <h2>应急咨询</h2>
        <p>遇到紧急情况？描述当前状况，AI 将在几秒内生成个性化建议</p>
        <span className="btn-consult">
          <svg className="btn-mic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <rect x="9" y="1" width="6" height="11" rx="3" />
            <path d="M5 11a7 7 0 0 0 14 0" />
            <line x1="12" y1="18" x2="12" y2="23" />
            <line x1="8" y1="23" x2="16" y2="23" />
          </svg>
          立即咨询
        </span>
      </Link>

      {/* ═══ Recent Consults ═══ */}
      <div className="section-header">
        <h3>最近咨询</h3>
        <Link to="/consult/history">查看全部 →</Link>
      </div>

      {loading ? (
        <div className="glow-loading" />
      ) : latestConsult ? (
        <Link className="consult-card" to={`/consult/${latestConsult.id}`}>
          <div className="consult-card-header">
            <span className="consult-level">
              <span className="consult-dot" /> 咨询记录
            </span>
            <span className="consult-time">
              {formatRelativeTime(latestConsult.consultation_time)}
            </span>
          </div>
          <p className="consult-summary">{latestConsult.behavior_description}</p>
          <div className="consult-meta">
            <span className="consult-tag">{latestConsult.crisis_level}</span>
          </div>
        </Link>
      ) : (
        <div className="empty-state">
          <div className="empty-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
              <circle cx="12" cy="12" r="10" />
              <line x1="8" y1="12" x2="16" y2="12" />
            </svg>
          </div>
          <p>暂无咨询记录</p>
          <p className="empty-hint">点击上方「立即咨询」开始第一次对话</p>
        </div>
      )}

      {/* ═══ Personal Profile ═══ */}
      <div className="section-header">
        <h3>个人档案</h3>
        <Link to="/profiles">查看全部 →</Link>
      </div>

      {profilesLoading ? (
        <div className="glow-loading" />
      ) : hasProfiles ? (
        <Link className="profile-card" to="/profiles">
          <div className="profile-avatar">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
              <circle cx="12" cy="9" r="4" />
              <path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" />
            </svg>
          </div>
          <div className="profile-info">
            <div className="profile-name-row">
              <span className="profile-name">{profilesSafe[0].nickname}</span>
              <span className="profile-tag age">{profilesSafe[0].age_range}</span>
              <span className="profile-tag diag">{profilesSafe[0].diagnosis_type}</span>
              {profilesSafe[0].primary_behavior && (
                <span className="profile-tag behavior">{profilesSafe[0].primary_behavior}</span>
              )}
            </div>
            <div className="profile-stats">
              <span className="profile-stat">档案已建立</span>
            </div>
          </div>
          <span className="profile-link">查看</span>
        </Link>
      ) : (
        <Link className="create-card" to="/profiles/edit">
          <div className="create-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="12" y1="18" x2="12" y2="12" />
              <line x1="9" y1="15" x2="15" y2="15" />
            </svg>
          </div>
          <div className="create-info">
            <h4>创建孩子的第一份档案</h4>
            <p>完善的档案能帮助 AI 更精准地匹配案例</p>
          </div>
          <span className="create-link">创建档案 →</span>
        </Link>
      )}
    </PageContent>
  );
}
