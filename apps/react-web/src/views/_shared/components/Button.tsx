import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { useButtonGlow } from '../hooks/useButtonGlow';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost';
  children: ReactNode;
}

/**
 * 通用按钮 — primary/secondary/ghost 三种变体。
 * 内置光晕追踪。OD 规格见 components.html 按钮系统。
 */
export default function Button({
  variant = 'primary',
  className = '',
  children,
  ...rest
}: ButtonProps) {
  const glow = useButtonGlow();
  const cls = `cf-btn cf-btn--${variant}${className ? ` ${className}` : ''}`;

  return (
    <button type="button" className={cls} {...glow} {...rest}>
      {children}
    </button>
  );
}
