export interface GlowLoadingProps {
  height?: number;
}

/**
 * 暖光加载占位 — 替代传统灰色骨架屏。
 * OD 规格：surface-variant 背景 + 火焰色脉冲光晕。
 */
export default function GlowLoading({ height = 80 }: GlowLoadingProps) {
  return (
    <div
      className="cf-glow-loading"
      style={{ height: `${height}px` }}
      aria-busy="true"
      role="progressbar"
    />
  );
}
