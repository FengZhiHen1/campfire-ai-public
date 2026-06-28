import type { ReactNode } from 'react';

export interface NavBarProps {
  title: string;
  showBack?: boolean;
  onBack?: () => void;
  rightSlot?: ReactNode;
}

/**
 * 页面导航栏。
 * OD 规格：44px 高度，毛玻璃背景，标题居中。
 */
export default function NavBar({ title, showBack = false, onBack, rightSlot }: NavBarProps) {
  return (
    <div className="cf-nav-bar">
      <div className="cf-nav-bar__side">
        {showBack && (
          <button
            type="button"
            className="cf-nav-bar__back"
            onClick={onBack ?? (() => window.history.back())}
            aria-label="返回"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
              width="20" height="20"
            >
              <path d="M15 18l-6-6 6-6" />
            </svg>
          </button>
        )}
      </div>
      <span className="cf-nav-bar__title">{title}</span>
      <div className="cf-nav-bar__side cf-nav-bar__side--right">
        {rightSlot}
      </div>
    </div>
  );
}
