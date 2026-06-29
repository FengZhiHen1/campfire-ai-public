import { useNavigate } from 'react-router-dom';

export interface IdlePanelProps {
  onStartConsult: () => void;
}

export default function IdlePanel({ onStartConsult }: IdlePanelProps) {
  const navigate = useNavigate();

  const handleStart = () => {
    onStartConsult();
    navigate('/consult/select');
  };

  return (
    <div className="state-panel active" data-testid="consult-idle">
      <div className="idle-area" data-testid="consult-idle-entry">
        <div className="idle-flame" data-testid="consult-idle-graphic">
          <div className="flame-glow" />
          <div className="flame-ring" />
          <div className="flame-particle" />
          <div className="flame-particle" />
          <div className="flame-particle" />
          <svg viewBox="0 0 64 64" fill="none">
            <defs>
              <radialGradient id="flameGrad" cx="50%" cy="60%" r="50%">
                <stop offset="0%" stopColor="var(--cf-accent)" stopOpacity="0.6" />
                <stop offset="60%" stopColor="var(--cf-accent)" stopOpacity="0.25" />
                <stop offset="100%" stopColor="var(--cf-accent)" stopOpacity="0.08" />
              </radialGradient>
            </defs>
            <circle cx="32" cy="42" r="16" stroke="var(--cf-accent)" strokeWidth="2" fill="url(#flameGrad)" opacity="0.4" />
            <circle cx="32" cy="42" r="12" stroke="var(--cf-accent)" strokeWidth="1.2" fill="none" opacity="0.2" />
            <path d="M32 6 C18 22 16 30 16 38 A16 16 0 0 0 48 38 C48 30 46 22 32 6Z" fill="var(--cf-accent)" opacity="0.22" />
            <path d="M32 14 C22 26 20 32 20 38 A12 12 0 0 0 44 38 C44 32 42 26 32 14Z" fill="var(--cf-accent)" opacity="0.38" />
            <path d="M32 22 C26 30 25 34 25 38 A7 7 0 0 0 39 38 C39 34 38 30 32 22Z" fill="var(--cf-accent)" opacity="0.58" />
            <circle cx="32" cy="38" r="3.5" fill="var(--cf-accent)" />
            <circle cx="32" cy="37" r="1.5" fill="var(--cf-accent-glow)" opacity="0.9" />
          </svg>
        </div>
        <h2 className="idle-title">应急咨询</h2>
        <p className="idle-subtitle">描述孩子当前的行为表现<br />获取基于真实案例的应急建议</p>
      </div>
      <div className="idle-btn-wrap">
        <button className="btn btn-primary" data-testid="consult-idle-cta" onClick={handleStart}>开始咨询</button>
      </div>
      <div className="disclaimer" data-testid="consult-disclaimer">基于归档案例的 AI 生成建议，不构成医疗诊断。严重情况请咨询专业医生。</div>
    </div>
  );
}
