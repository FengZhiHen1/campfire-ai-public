export default function SubmittingPanel() {
  return (
    <div className="state-panel active">
      <div className="submitting-area">
        <div className="glow-circle">
          <div className="glow-orbit" />
        </div>
        <div className="progress-dots">
          <div className="progress-dot" />
          <div className="progress-dot" />
          <div className="progress-dot" />
          <div className="progress-dot" />
        </div>
        <p className="submit-status">正在分析案例库…</p>
        <p className="submit-hint">匹配最相似的历史案例</p>
      </div>
      <div className="disclaimer">基于归档案例的 AI 生成建议，不构成医疗诊断。严重情况请咨询专业医生。</div>
    </div>
  );
}
