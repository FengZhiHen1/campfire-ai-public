export interface StreamCursorProps {
  active: boolean;
}

/**
 * 打字机光标 — 2px 宽 accent 色竖线，pulsing 闪烁。
 * OD 规格：1.4s ease-in-out infinite，opacity 1↔0.35。
 */
export default function StreamCursor({ active }: StreamCursorProps) {
  if (!active) return null;
  return <span className="cf-stream-cursor" aria-hidden="true" />;
}
