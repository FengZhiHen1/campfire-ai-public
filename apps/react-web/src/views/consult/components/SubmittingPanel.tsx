import { useEffect, useState } from 'react';

export default function SubmittingPanel() {
  const [activeDot, setActiveDot] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setActiveDot((prev) => (prev + 1) % 4);
    }, 400);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="state-panel active" data-testid="consult-submitting">
      <div className="submitting-area">
        <div className="glow-circle" data-testid="consult-submitting-glow">
          <div className="glow-orbit" />
        </div>
        <div className="progress-dots" data-testid="consult-submitting-dots">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className={`progress-dot${activeDot === i ? ' on' : ''}`} />
          ))}
        </div>
        <p className="submit-status" data-testid="consult-submitting-text">正在分析案例库…</p>
        <p className="submit-hint">匹配最相似的历史案例</p>
      </div>
      <div className="disclaimer" data-testid="consult-disclaimer">基于归档案例的 AI 生成建议，不构成医疗诊断。严重情况请咨询专业医生。</div>
    </div>
  );
}
