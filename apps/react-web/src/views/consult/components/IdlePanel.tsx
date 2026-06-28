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
    <div className="state-panel active">
      <div className="idle-area">
        <div className="idle-flame">
          <div className="flame-glow" />
          <div className="flame-ring" />
          <div className="flame-particle" />
          <div className="flame-particle" />
          <div className="flame-particle" />
          <svg viewBox="0 0 64 64" fill="none">
            <circle cx="32" cy="42" r="16" stroke="var(--cf-accent)" strokeWidth="2" opacity="0.4" />
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
        <button className="btn btn-primary" onClick={handleStart}>开始咨询</button>
      </div>
      <div className="disclaimer">基于归档案例的 AI 生成建议，不构成医疗诊断。严重情况请咨询专业医生。</div>
    </div>
  );
}
