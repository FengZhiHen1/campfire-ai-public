import { Link } from 'react-router-dom';
import { useCaseListPage } from '@/logics/cases';
import PageContent from '@/views/_shared/layout/PageContent';
import './CaseListPage.css';

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('zh-CN');
  } catch {
    return iso;
  }
}

export default function CaseListPage() {
  const {
    activeTab,
    searchKeyword,
    loading,
    error,
    filteredItems,
    hasMore,
    canSeeReviewBtn,
    emptyState,
    statusTextMap,
    statusClassMap,
    sourceLabelMap,
    setSearchKeyword,
    setActiveTab,
    goDetail,
    goSubmit,
    goReview,
    refresh,
    loadMore,
  } = useCaseListPage();

  return (
    <>
      <div className="nav">
        <span className="nav-title">真实案例库</span>
        {canSeeReviewBtn && (
          <button type="button" className="nav-act" onClick={goReview}>
            审核台
          </button>
        )}
      </div>
      <PageContent>
        <div className="tabs">
          <button
            type="button"
            className={`tab${activeTab === 'public' ? ' active' : ''}`}
            onClick={() => setActiveTab('public')}
          >
            公共案例库
          </button>
          <button
            type="button"
            className={`tab${activeTab === 'my' ? ' active' : ''}`}
            onClick={() => setActiveTab('my')}
          >
            我的提交
          </button>
        </div>

        <div className="search">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" />
            <line x1="21" y1="21" x2="16.6" y2="16.6" />
          </svg>
          <input
            placeholder="搜索案例库…"
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
          />
        </div>

        {loading && filteredItems.length === 0 && <div className="glow-loading" />}

        {error && filteredItems.length === 0 && (
          <div className="empty">
            <div className="emp-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            </div>
            <h3>加载失败</h3>
            <p>{error}</p>
            <button type="button" className="btn btn-p" onClick={refresh}>重试</button>
          </div>
        )}

        {!loading && !error && filteredItems.length === 0 && (
          <div className="empty">
            <div className="emp-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><line x1="8" y1="12" x2="16" y2="12"/></svg>
            </div>
            <h3>{emptyState.title}</h3>
            <p>{emptyState.subtitle}</p>
            {emptyState.showClearBtn && (
              <button type="button" className="btn btn-p" onClick={() => setSearchKeyword('')}>
                清除搜索
              </button>
            )}
          </div>
        )}

        {filteredItems.map((item, index) => {
          const statusCls = statusClassMap[item.status] ?? item.status;
          const tags = item.tags?.length ? item.tags : [sourceLabelMap[item.source_type] ?? item.source_type];
          // 所有卡片都参与进场动画，按索引递增错开，避免批量出现时“突然出现”
          const animationDelay = `${Math.min(index, 12) * 50}ms`;
          return (
            <Link
              key={item.narrative_id}
              to={`/cases/${item.narrative_id}`}
              className={`case-card ${statusCls}`}
              style={{ animationDelay }}
            >
              <div className="card-head">
                <span className="card-title">{item.title}</span>
                <span className="card-badge">{sourceLabelMap[item.source_type] ?? item.source_type}</span>
              </div>
              <div className="card-tags">
                {tags.map((t) => (
                  <span key={t} className="card-tag">{t}</span>
                ))}
              </div>
              <div className="card-foot">
                <span className={`card-dot ${statusCls}`} />
                <span className="card-status">{statusTextMap[item.status] ?? item.status}</span>
                <span className="card-time">{formatDate(item.created_at)}</span>
              </div>
            </Link>
          );
        })}

        {filteredItems.length > 0 && (
          <div className="no-more">
            {loading ? '加载中…' : hasMore ? (
              <button type="button" className="load-more-btn" onClick={loadMore}>加载更多</button>
            ) : '—— 已展示全部案例 ——'}
          </div>
        )}
      </PageContent>
      <button type="button" className="fab" onClick={goSubmit}>+</button>
    </>
  );
}
