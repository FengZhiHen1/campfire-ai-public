export interface ErrorBannerProps {
  message: string;
  onRetry: () => void;
}

/**
 * 错误通知条 — 常驻页面顶部，含重试按钮。
 * OD 规格：danger-container 背景 + danger 文字。
 */
export default function ErrorBanner({ message, onRetry }: ErrorBannerProps) {
  return (
    <div className="cf-error-banner">
      <svg className="cf-error-banner__icon" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
      <span className="cf-error-banner__text">{message}</span>
      <button type="button" className="cf-error-banner__retry" onClick={onRetry}>
        重试
      </button>
    </div>
  );
}
