import {C} from './tokens';

// 品牌图形,源文件 docs/design/assets/brand-mark.svg,此处内联同一组 path。
// 视频内需要按帧控制透明度与缩放,走组件而不走静态图片。
export const BrandMark: React.FC<{size: number; color?: string}> = ({
  size,
  color = C.accent,
}) => (
  <svg width={size} height={size} viewBox="0 0 128 128" role="img">
    <g fill={color}>
      <path d="M69 9c11 9 19 22 19 35 0 13-7 22-19 31-10 8-15 15-14 24 1 5 4 9 9 14-8-6-15-8-23-12-12-6-17-15-15-27 2-13 11-21 22-30C64 31 73 23 69 9Z" />
      <path d="M89 61c2 8 10 15 13 23 6 14-4 22-25 26 10-10 12-16 8-23-5-8-3-17 4-26Z" />
      <path d="M16 103c16-4 33 1 48 13 16-12 33-17 48-13-1 8-5 13-13 12-15-2-26 2-35 9-9-7-20-11-35-9-8 1-12-4-13-12Z" />
    </g>
  </svg>
);

// 篝火呼吸点,契约组件 flame-dot 的视频版:2s 周期(60 帧 @30fps),透明度呼吸。
// DESIGN.md 规定它是全片唯一循环动效,用作「火光仍在」的心理锚点。
export const FlameDot: React.FC<{frame: number; size?: number}> = ({
  frame,
  size = 14,
}) => {
  const breath = 0.55 + 0.45 * Math.sin((frame / 60) * Math.PI * 2 - Math.PI / 2);
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: 9999,
        backgroundColor: C.accent,
        opacity: breath,
        boxShadow: `0 0 ${size}px ${C.accent}`,
        flexShrink: 0,
      }}
    />
  );
};
