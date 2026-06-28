import type { AnchorHTMLAttributes, ReactNode } from 'react';

export interface CardProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  variant?: 'default' | 'emergency';
  children: ReactNode;
}

/**
 * 通用卡片容器 — default (毛玻璃) / emergency (暖光渐变)。
 * 默认为 <a> 标签，点击跳转。
 */
export default function Card({
  variant = 'default',
  className = '',
  children,
  ...rest
}: CardProps) {
  const cls = `cf-card${variant === 'emergency' ? ' cf-card--emergency' : ''}${className ? ` ${className}` : ''}`;

  return (
    <a className={cls} {...rest}>
      {children}
    </a>
  );
}
