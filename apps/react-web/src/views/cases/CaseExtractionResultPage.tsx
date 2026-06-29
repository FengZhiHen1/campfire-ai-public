import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import PageContent from '@/views/_shared/layout/PageContent';
import {
  useExtractionResult,
  BEHAVIOR_TYPE_OPTIONS,
  BEHAVIOR_TYPE_VALUES,
  SEVERITY_OPTIONS,
  SEVERITY_VALUES,
  SCENE_OPTIONS,
  SCENE_VALUES,
  FAMILY_CATEGORY_OPTIONS,
} from '@/logics/cases';
import './CaseExtractionResultPage.css';

const QUARTET = [
  { key: 'immediate_action', label: '即时安全干预动作', accent: 'action' },
  { key: 'comforting_phrase', label: '情绪安抚话术', accent: 'soothe' },
  { key: 'observation_metrics', label: '观察指标', accent: 'observe' },
  { key: 'medical_criteria', label: '就医判断标准', accent: 'medical' },
] as const;

export default function CaseExtractionResultPage() {
  const navigate = useNavigate();
  const [infOpen, setInfOpen] = useState(false);
  const {
    cards,
    activeTab,
    editing,
    loading,
    isSaving,
    isSubmittingAll,
    extracting,
    extractFailed,
    setActiveTab,
    updateField,
    saveCard,
    submitAll,
    retryExtraction,
  } = useExtractionResult();

  if (extracting) {
    return (
      <>
        <div className="nav">
          <button className="nav-back" onClick={() => navigate(-1)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
          </button>
          <span className="nav-title">提取结果</span>
        </div>
        <div className="extracting active">
          <div className="ext-ring" />
          <h3>AI 正在分析叙事内容…</h3>
          <p>预计需要 10–30 秒</p>
          <div className="ext-progress" />
        </div>
      </>
    );
  }

  if (extractFailed) {
    return (
      <>
        <div className="nav">
          <button className="nav-back" onClick={() => navigate(-1)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
          </button>
          <span className="nav-title">提取结果</span>
        </div>
        <div className="error-state active">
          <div className="err-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          </div>
          <h3>提取失败</h3>
          <p>AI 处理过程中出现异常，请返回重试</p>
          <div className="error-actions">
            <button className="btn btn-p" onClick={retryExtraction}>重试</button>
            <button className="btn btn-s" onClick={() => navigate(-1)}>返回修改叙事</button>
          </div>
        </div>
      </>
    );
  }

  if (loading || !editing) {
    return (
      <>
        <div className="nav">
          <button className="nav-back" onClick={() => navigate(-1)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
          </button>
          <span className="nav-title">提取结果</span>
        </div>
        <div className="extracting active">
          <div className="ext-ring" />
          <h3>正在加载提取结果…</h3>
        </div>
      </>
    );
  }

  const behaviorIndex = BEHAVIOR_TYPE_VALUES.indexOf(editing.behavior_type ?? '');
  const severityIndex = SEVERITY_VALUES.indexOf(editing.severity ?? '');
  const sceneIndex = SCENE_VALUES.indexOf(editing.scene ?? '');

  return (
    <>
      <div className="nav">
        <button className="nav-back" onClick={() => navigate(-1)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
        </button>
        <span className="nav-title">提取结果</span>
      </div>
      <PageContent>
        <div className="banner">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          AI 从叙事中提取了 <strong>{cards.length}</strong> 张干预卡片
        </div>
        <div className="tab-scroll">
          {cards.map((c, i) => (
            <button
              key={c.card_id}
              className={`tab-chip${i === activeTab ? ' active' : ''}`}
              onClick={() => setActiveTab(i)}
            >
              卡片 {i + 1}
            </button>
          ))}
        </div>
        <div className="form-wrap">
          <div className="field">
            <div className="field-label">卡片标题</div>
            <input
              value={editing.title ?? ''}
              onChange={(e) => updateField('title', e.target.value)}
            />
          </div>
          <div className="field">
            <div className="field-label">适用场景</div>
            <textarea
              value={editing.scenario ?? ''}
              onChange={(e) => updateField('scenario', e.target.value)}
            />
          </div>
          <div className="field">
            <div className="field-label">行为类型</div>
            <div className="chip-grid">
              {BEHAVIOR_TYPE_OPTIONS.map((b, i) => (
                <button
                  key={b}
                  className={`chip-btn${i === behaviorIndex ? ' selected' : ''}`}
                  onClick={() => updateField('behavior_type', BEHAVIOR_TYPE_VALUES[i])}
                >
                  {b}
                </button>
              ))}
            </div>
          </div>
          <div className="field">
            <div className="field-label">严重程度</div>
            <div className="chip-grid">
              {SEVERITY_OPTIONS.map((s, i) => (
                <button
                  key={s}
                  className={`chip-btn${i === severityIndex ? ' selected' : ''}`}
                  onClick={() => updateField('severity', SEVERITY_VALUES[i])}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
          <div className="field">
            <div className="field-label">发生场景</div>
            <div className="chip-grid">
              {SCENE_OPTIONS.map((s, i) => (
                <button
                  key={s}
                  className={`chip-btn${i === sceneIndex ? ' selected' : ''}`}
                  onClick={() => updateField('scene', SCENE_VALUES[i])}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
          <div className="field">
            <div className="field-label">家属展示大类</div>
            <div className="chip-grid">
              {FAMILY_CATEGORY_OPTIONS.map((c) => (
                <button
                  key={c}
                  className={`chip-btn${editing.family_category === c ? ' selected' : ''}`}
                  onClick={() => updateField('family_category', c)}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>
          <div className="qrt-section">
            {QUARTET.map((s) => (
              <div key={s.key} className={`qrt-card ${s.accent}`}>
                <h5>{s.label}</h5>
                <textarea
                  value={((editing as unknown) as Record<string, string>)[s.key] ?? ''}
                  onChange={(e) => updateField(s.key, e.target.value)}
                />
              </div>
            ))}
          </div>
        </div>
        <div className="inf-panel">
          <button className={`inf-toggle${infOpen ? ' open' : ''}`} onClick={() => setInfOpen(!infOpen)}>AI 推断说明</button>
          <div className={`inf-body${infOpen ? ' open' : ''}`}>
            {editing.inferred_fields && Object.keys(editing.inferred_fields).length > 0 ? (
              Object.entries(editing.inferred_fields).map(([k, v]) => (
                <div key={k} className="inf-item">
                  <span className="inf-field">{k}</span>
                  <span className="inf-reason">{v}</span>
                </div>
              ))
            ) : (
              <div className="inf-item"><span className="inf-reason">AI 基于叙事内容自动提取，未记录额外推断字段。</span></div>
            )}
          </div>
        </div>
      </PageContent>
      <div className="footer-bar">
        <button className="btn btn-p" onClick={saveCard} disabled={isSaving}>{isSaving ? '保存中…' : '保存当前卡片'}</button>
        <button className="btn btn-outline" onClick={submitAll} disabled={isSubmittingAll}>{isSubmittingAll ? '提交中…' : '全部提交审核'}</button>
      </div>
    </>
  );
}
