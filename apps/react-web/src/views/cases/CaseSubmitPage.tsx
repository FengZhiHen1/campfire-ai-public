import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import PageContent from '@/views/_shared/layout/PageContent';
import { useCaseSubmit } from '@/logics/cases';
import './CaseSubmitPage.css';

export default function CaseSubmitPage() {
  const navigate = useNavigate();
  const [openDD, setOpenDD] = useState<string | null>(null);
  const toggle = (id: string) => setOpenDD((p) => (p === id ? null : id));

  const {
    title,
    setTitle,
    behaviorTypeIdx,
    setBehaviorTypeIdx,
    severityIdx,
    setSeverityIdx,
    sceneIdx,
    setSceneIdx,
    evidenceLevelIdx,
    setEvidenceLevelIdx,
    quartetValues,
    quartetSetter,
    isSubmitting,
    handleSubmit,
    behaviorTypeOptions,
    severityOptions,
    sceneOptions,
    evidenceLevelOptions,
    quartetConfig,
  } = useCaseSubmit();

  const renderDropdown = (
    id: string,
    label: string,
    required: boolean,
    value: string,
    options: readonly string[],
    onSelect: (idx: number) => void,
    currentIdx: number,
  ) => (
    <div className="field">
      <label>{required && <span className="req">*</span>} {label}</label>
      <div className={`dd-wrap${openDD === id ? ' open' : ''}`}>
        <button className="dd-btn" onClick={() => toggle(id)}>{value}</button>
        <div className="dd-menu">
          {options.map((opt, idx) => (
            <button
              key={opt}
              className={`dd-opt${idx === currentIdx ? ' selected' : ''}`}
              onClick={() => { onSelect(idx); setOpenDD(null); }}
            >
              {opt}
            </button>
          ))}
        </div>
      </div>
    </div>
  );

  return (
    <>
      <div className="nav">
        <button className="nav-cancel" onClick={() => navigate(-1)}>取消</button>
        <span className="nav-title">提交案例</span>
        <button className="nav-submit" onClick={() => void handleSubmit()} disabled={isSubmitting}>
          {isSubmitting ? '提交中…' : '提交'}
        </button>
      </div>
      <PageContent>
        <div className="cover">
          <svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <rect x="2" y="6" width="28" height="20" rx="2"/><circle cx="11" cy="14" r="2"/><path d="M2 22l8-6 6 4 6-6 8 8"/>
          </svg>
          <span>点击上传封面图（可选）</span>
        </div>
        <div className="field">
          <label><span className="req">*</span> 案例标题</label>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="请输入案例标题" />
        </div>
        <div className="row">
          {renderDropdown('type', '行为类型', true, behaviorTypeOptions[behaviorTypeIdx], behaviorTypeOptions, setBehaviorTypeIdx, behaviorTypeIdx)}
          {renderDropdown('severity', '严重程度', true, severityOptions[severityIdx], severityOptions, setSeverityIdx, severityIdx)}
        </div>
        <div className="row">
          {renderDropdown('scene', '发生场景', true, sceneOptions[sceneIdx], sceneOptions, setSceneIdx, sceneIdx)}
          {renderDropdown('evidence', '证据等级', false, evidenceLevelOptions[evidenceLevelIdx], evidenceLevelOptions, setEvidenceLevelIdx, evidenceLevelIdx)}
        </div>

        <div className="quartet-wrap">
          {quartetConfig.map((cfg) => (
            <div key={cfg.key} className={`qrt-group ${cfg.accent}`}>
              <label><span className="req">*</span> {cfg.title}</label>
              <span className="qrt-hint">{cfg.hint}</span>
              <textarea
                value={quartetValues[cfg.key] ?? ''}
                onChange={(e) => quartetSetter(cfg.key, e.target.value)}
                placeholder={`请输入${cfg.title}…`}
              />
            </div>
          ))}
        </div>
      </PageContent>
    </>
  );
}
