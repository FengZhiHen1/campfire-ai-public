import { useNavigate } from 'react-router-dom';
import { useCaseDetailPage } from '@/logics/cases';
import { MarkdownRenderer } from '@/logics/shared';
import PageContent from '@/views/_shared/layout/PageContent';
import './CaseDetailPage.css';

export default function CaseDetailPage() {
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

  const statusCls = data ? (statusClassMap[data.status] ?? data.status) : '';

  return (
    <>
      <div className="nav">
        <button type="button" className="nav-back" onClick={() => navigate(-1)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <span className="nav-title">案例详情</span>
      </div>
      <PageContent>
        {loading && <div className="glow-loading" />}

        {error && !data && (
          <div className="error-state">
            <h2>加载失败</h2>
            <p>{error}</p>
            <div className="error-acts">
              <button type="button" className="btn btn-s" onClick={handleRetry}>重试</button>
              <button type="button" className="btn btn-s" onClick={() => navigate(-1)}>返回</button>
            </div>
          </div>
        )}

        {!loading && !error && !data && (
          <div className="error-state">
            <h2>未找到案例</h2>
            <p>该案例不存在或已被删除</p>
            <button type="button" className="btn btn-s" onClick={() => navigate(-1)}>返回</button>
          </div>
        )}

        {data && (
          <>
            <div className="overview">
              <h2>{data.title}</h2>
              <div className="o-tags">
                <span className="o-tag">{sourceLabelMap[data.source_type] ?? data.source_type}</span>
              </div>
              <div className="o-meta">
                <span className={`o-dot ${statusCls}`} />
                <span>{statusTextMap[data.status] ?? data.status} · {data.cards.length} 张卡片</span>
              </div>
            </div>

            <div className="section">
              <h3>叙事原文</h3>
              <div className="narrative">
                <MarkdownRenderer content={data.narrative} />
              </div>
            </div>

            {data.cards.length > 0 && (
              <div className="section">
                <h3>关联卡片 <span className="count">({data.cards.length})</span></h3>
                {data.cards.map((card) => {
                  const cardStatus = cardStatusMap[card.review_status] ?? { text: card.review_status, cls: card.review_status };
                  return (
                    <button
                      key={card.card_id}
                      type="button"
                      className="card-item"
                      onClick={() => handleCardClick(card.card_id)}
                    >
                      <h4>{card.title}</h4>
                      <div className="c-tags">
                        <span className="c-tag">{card.behavior_type}</span>
                        <span className="c-tag">{card.severity}</span>
                        <span className="c-tag">{card.scene}</span>
                      </div>
                      <span className={`c-status ${cardStatus.cls}`}>{cardStatus.text}</span>
                    </button>
                  );
                })}
              </div>
            )}

            {data.status === 'approved' ? (
              <div className="approved-badge">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                该案例已通过审核
              </div>
            ) : data.extraction_status === 'extracting' ? (
              <div className="extracting-hint">
                <div className="ext-dot" />
                <span>AI 正在提取干预卡片，内容较长时可能需要 1–3 分钟。你可以先去别处，稍后回来查看结果。</span>
              </div>
            ) : data.extraction_status === 'extracted' && data.cards.length > 0 ? (
              <div className="actions">
                <button type="button" className="btn btn-p" onClick={handleGoExtract}>查看提取结果</button>
                <button type="button" className="btn btn-s" onClick={handleEditNarrative}>编辑原文</button>
              </div>
            ) : data.extraction_status === 'failed' ? (
              <div className="actions">
                <button type="button" className="btn btn-p" onClick={handleGoExtract}>重新提取</button>
                <button type="button" className="btn btn-s" onClick={handleEditNarrative}>编辑原文</button>
                {data.extraction_error && (
                  <div className="extract-error-hint">{data.extraction_error}</div>
                )}
              </div>
            ) : (
              <div className="actions">
                <button type="button" className="btn btn-p" onClick={handleGoExtract}>提取卡片</button>
                <button type="button" className="btn btn-s" onClick={handleEditNarrative}>编辑原文</button>
              </div>
            )}
          </>
        )}
      </PageContent>
    </>
  );
}
