import type { ReactNode } from 'react';

export interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  hint?: string;
  children?: ReactNode;
}

/**
 * 空态占位 — 图标 + 标题 + 提示文字 + 可选操作入口。
 */
export default function EmptyState({ icon, title, hint, children }: EmptyStateProps) {
  return (
    <div className="cf-empty">
      {icon && <div className="cf-empty__icon">{icon}</div>}
      <p className="cf-empty__title">{title}</p>
      {hint && <p className="cf-empty__hint">{hint}</p>}
      {children}
    </div>
  );
}
