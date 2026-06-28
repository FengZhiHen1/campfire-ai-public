import type { ReactNode } from 'react';

export interface PageContentProps {
  children: ReactNode;
  className?: string;
}

/**
 * 可滚动页面内容容器。
 * OD 规格：flex: 1, overflow-y: auto, 自定义 3px 滚动条。
 */
export default function PageContent({ children, className }: PageContentProps) {
  return (
    <div className={`cf-page-content${className ? ` ${className}` : ''}`}>
      {children}
    </div>
  );
}
