import { useCallback } from 'react';
import type { MouseEvent } from 'react';

export interface ButtonGlowHandlers {
  onMouseMove: (e: MouseEvent<HTMLButtonElement>) => void;
}

/**
 * 按钮光晕追踪 — mousemove 时更新 CSS 变量驱动径向渐变位置。
 * OD 设计所有 .btn 均需此效果。
 */
export function useButtonGlow(): ButtonGlowHandlers {
  const onMouseMove = useCallback((e: MouseEvent<HTMLButtonElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width * 100).toFixed(1);
    const y = ((e.clientY - rect.top) / rect.height * 100).toFixed(1);
    e.currentTarget.style.setProperty('--cf-glow-x', `${x}%`);
    e.currentTarget.style.setProperty('--cf-glow-y', `${y}%`);
  }, []);

  return { onMouseMove };
}
