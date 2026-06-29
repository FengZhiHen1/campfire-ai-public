export interface ErrorPanelProps {
  variant: 'submit_failed' | 'stream_failed';
  errorMessage: string;
  onRetry: () => void;
  onBack: () => void;
}

export default function ErrorPanel({ variant, errorMessage, onRetry, onBack }: ErrorPanelProps) {
  const isSubmit = variant === 'submit_failed';
  const title = isSubmit ? '提交失败' : '生成中断';
  const retryLabel = isSubmit ? '重试提交' : '重新生成';

  return (
    <div className="state-panel active" data-testid="consult-error">
      <div className="error-area">
        <div className="error-graphic">
          {isSubmit ? (
            <svg viewBox="0 0 36 36" fill="none">
              <circle cx="18" cy="18" r="14" stroke="var(--cf-danger)" strokeWidth="2.2" />
              <line x1="18" y1="10" x2="18" y2="21" stroke="var(--cf-danger)" strokeWidth="2.2" strokeLinecap="round" />
              <circle cx="18" cy="25" r="1.5" fill="var(--cf-danger)" />
            </svg>
          ) : (
            <svg viewBox="0 0 36 36" fill="none">
              <circle cx="18" cy="18" r="14" stroke="var(--cf-danger)" strokeWidth="2.2" />
              <path d="M12 12l12 12M24 12l-12 12" stroke="var(--cf-danger)" strokeWidth="2.2" strokeLinecap="round" />
            </svg>
          )}
        </div>
        <h2 className="error-title">{title}</h2>
        <p className="error-desc" style={{ whiteSpace: 'pre-line' }}>{errorMessage}</p>
        <div className="error-actions">
          <button className="btn btn-primary" data-testid="consult-error-retry-btn" onClick={onRetry}>{retryLabel}</button>
          <button className="btn btn-secondary" data-testid="consult-error-back-btn" onClick={onBack}>返回修改</button>
        </div>
      </div>
      <div className="disclaimer" data-testid="consult-disclaimer">基于归档案例的 AI 生成建议，不构成医疗诊断。严重情况请咨询专业医生。</div>
    </div>
  );
}
