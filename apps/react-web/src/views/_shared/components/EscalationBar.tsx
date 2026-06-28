export interface EscalationBarProps {
  onClick: () => void;
}

/**
 * 人工升级粘性底栏 — danger 背景，56px 高。
 * 出现方式：slide-up 动画，无确认弹窗。
 */
export default function EscalationBar({ onClick }: EscalationBarProps) {
  return (
    <button type="button" className="cf-escalation-bar" onClick={onClick}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
      </svg>
      立即联系人工专家
    </button>
  );
}
