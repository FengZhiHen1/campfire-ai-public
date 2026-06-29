import { useParams, useNavigate } from 'react-router-dom';
import { useCaseDetailPage } from '@/logics/cases';
import MarkdownRenderer from '@/logics/shared/components/MarkdownRenderer';
import PageContent from '@/views/_shared/layout/PageContent';
import './CaseDetailPage.css';

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('zh-CN');
  } catch {
    return iso;
  }
}

export default function CaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const {
    data,
    loading,
    error,
    handleGoExtract,
    handleEditNarrative,
    handleCardClick,
    handleRetry,
    statusTextMap,
    statusClassMap,
    sourceLabelMap,
    cardStatusMap,
  } = useCaseDetailPage();

  return (
    <>
      <div className="nav">
        <button type="button" className="nav-back" onClick={() => navigate(-1)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <span className="nav-title">案例详情</span>
      </div>
      <PageContent>
        {loading && <div className="glow-loading" />}

        {error && (
          <div className="error-state">
            <h2>加载失败</h2>
            <p>{error}</p>
            <div className="error-acts">
              <button type="button" className="btn-s" onClick={handleRetry}>重试</button>
              <button type="button" className="btn-s" onClick={() => navigate(-1)}>返回</button>
            </div>
          </div>
        )}

        {!loading && !error && !data && (
          <div className="error-state">
            <h2>未找到案例</h2>
            <p>该案例不存在或已被删除</p>
            <button type="button" className="btn-s" onClick={() => navigate(-1)}>返回</button>
          </div>
        )}

        {data && (
          <>
            <div className="detail-overview">
              <h1 className="detail-title">{data.title}</h1>
              <div className="detail-meta">
                <span className={`detail-status ${statusClassMap[data.status] ?? data.status}`}>
                  {statusTextMap[data.status] ?? data.status}
                </span>
                <span className="detail-source">{sourceLabelMap[data.source_type] ?? data.source_type}</span>
                <span className="detail-time">{formatDate(data.created_at)}</span>
              </div>
            </div>

            <div className="detail-section">
              <h3>叙事原文</h3>
              <div className="detail-narrative">
                <MarkdownRenderer content={data.narrative} />
              </div>
            </div>

            {data.cards.length > 0 && (
              <div className="detail-section">
                <h3>关联卡片（{data.cards.length}）</h3>
                <div className="detail-card-list">
                  {data.cards.map((card) => (
                    <button
                      key={card.card_id}
                      type="button"
                      className="detail-card-item"
                      onClick={() => handleCardClick(card.card_id)}
                    >
                      <div className="detail-card-head">
                        <span className="detail-card-title">{card.title}</span>
                        <span className={`detail-card-status ${cardStatusMap[card.review_status]?.cls ?? card.review_status}`}>
                          {cardStatusMap[card.review_status]?.text ?? card.review_status}
                        </span>
                      </div>
                      <div className="detail-card-tags">
                        <span>{card.behavior_type}</span>
                        <span>{card.severity}</span>
                        <span>{card.scene}</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="detail-actions">
              {data.status === 'draft' ? (
                <>
                  <button type="button" className="btn btn-p" onClick={handleGoExtract}>提取卡片</button>
                  <button type="button" className="btn btn-s" onClick={handleEditNarrative}>编辑原文</button>
                </>
              ) : (
                <span className="detail-approved-tip">该案例已通过审核</span>
              )}
            </div>
          </>
        )}
      </PageContent>
    </>
  );
}
