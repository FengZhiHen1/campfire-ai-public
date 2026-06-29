import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import PageContent from '@/views/_shared/layout/PageContent';
import { useNarrativeSubmit } from '@/logics/cases';
import './CaseNarrativeSubmitPage.css';

export default function CaseNarrativeSubmitPage() {
  const navigate = useNavigate();
  const {
    title,
    setTitle,
    sourceType,
    setSourceType,
    narrative,
    setNarrative,
    submitting,
    extracting,
    tipsExpanded,
    setTipsExpanded,
    titleCount,
    bodyCount,
    canSubmit,
    handleSaveDraft,
    handleSubmit,
    sourceOptions,
    writingTips,
    bodyPlaceholder,
  } = useNarrativeSubmit();

  const [openDD, setOpenDD] = useState(false);

  if (submitting || extracting) {
    return (
      <>
        <div className="nav">
          <button className="nav-back" onClick={() => navigate(-1)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
          </button>
          <span className="nav-title">AI 正在提取</span>
        </div>
        <div className="extract-state active">
          <div className="glow" />
          <h2>正在分析叙事…</h2>
          <p>AI 正在提取干预卡片，预计需要 10-30 秒</p>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="nav">
        <button className="nav-back" onClick={() => navigate(-1)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
        </button>
        <span className="nav-title">提交叙事</span>
      </div>
      <PageContent>
        <div className="field">
          <label>案例标题</label>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="为这个案例起一个标题" maxLength={50} />
          <div className="counter">{titleCount}/50</div>
        </div>
        <div className="field">
          <label>来源类型</label>
          <div className={`dd-wrap${openDD ? ' open' : ''}`}>
            <button className="dd-btn" onClick={() => setOpenDD(!openDD)}>{sourceType}</button>
            <div className="dd-menu">
              {sourceOptions.map((s) => (
                <button
                  key={s}
                  className={`dd-opt${sourceType === s ? ' selected' : ''}`}
                  onClick={() => { setSourceType(s); setOpenDD(false); }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="field">
          <label>叙事正文</label>
          <textarea
            value={narrative}
            onChange={(e) => setNarrative(e.target.value)}
            placeholder={bodyPlaceholder}
          />
          <div className="counter">{bodyCount}/2000</div>
        </div>

        <div className="field">
          <button
            className={`inf-toggle${tipsExpanded ? ' open' : ''}`}
            onClick={() => setTipsExpanded(!tipsExpanded)}
            style={{ margin: 0 }}
          >
            写作提示
          </button>
          {tipsExpanded && (
            <div className="inf-body open" style={{ marginTop: 8 }}>
              {writingTips.map((tip, idx) => (
                <div key={idx} className="inf-item"><span className="inf-reason">• {tip}</span></div>
              ))}
            </div>
          )}
        </div>

        <button className="btn" onClick={handleSubmit} disabled={!canSubmit}>提交并提取卡片</button>
        <button className="btn btn-s" onClick={handleSaveDraft}>保存草稿</button>
      </PageContent>
    </>
  );
}
