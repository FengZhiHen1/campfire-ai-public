import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_BODY, FONT_DISPLAY} from '../lib/tokens';
import {easeOutCubic} from '../lib/ease';

// ① 痛点开场(0-18s):shot-list Motion 段——暖米纸底转暗的静谧版,
// 三行情境文字逐行浮现,末行「没人商量」单独强调。

const LINE1 = ['超市里,孩子突然蹲下捂住耳朵,', '周围全是目光。'];
const LINE2 = ['你不知道这是感官过载,还是哪里疼——', '而能回答你的人,都不在现场。'];
const LINE4A = '照护一个孤独症孩子,最难的不是辛苦,';
const LINE4B = '是没人商量。';

// 帧窗口 @30fps:入场带 0-6s,末行 10-13.5s,17s 起整体淡出
const lineIn = (frame: number, start: number) =>
  interpolate(frame, [start, start + 30], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: easeOutCubic,
  });

export const S1PainPoint: React.FC = () => {
  const frame = useCurrentFrame();

  const t1 = lineIn(frame, 30);
  const t2 = lineIn(frame, 105);
  const t3 = lineIn(frame, 300);
  const t4 = lineIn(frame, 375);

  // 底:前 12s 从暖米纸缓慢转暗,之后保持
  const dim = interpolate(frame, [0, 360], [0, 1], {extrapolateRight: 'clamp'});
  const bg = `color-mix(in srgb, ${C.bg} ${(1 - dim) * 100}%, #17110c)`;
  const ink = `color-mix(in srgb, ${C.fg} ${(1 - dim) * 100}%, #f5ead9)`;
  const inkSoft = `color-mix(in srgb, ${C.fg2} ${(1 - dim) * 100}%, #cbb89f)`;

  const fadeOut = interpolate(frame, [510, 540], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const lineStyle = (
    t: number,
    color: string,
    size: number,
    display = false,
  ): React.CSSProperties => ({
    opacity: t,
    transform: `translateY(${(1 - t) * 18}px)`,
    color,
    fontSize: size,
    lineHeight: 1.7,
    fontFamily: display ? FONT_DISPLAY : FONT_BODY,
    fontWeight: display ? 500 : 400,
    margin: 0,
    textAlign: 'center',
  });

  return (
    <AbsoluteFill
      style={{background: bg, justifyContent: 'center', alignItems: 'center', opacity: fadeOut}}
    >
      <div style={{maxWidth: 1200}}>
        <p style={lineStyle(t1, ink, 40, true)}>{LINE1[0]}</p>
        <p style={lineStyle(t1, ink, 40, true)}>{LINE1[1]}</p>
        <div style={{height: 56}} />
        <p style={lineStyle(t2, inkSoft, 30)}>{LINE2[0]}</p>
        <p style={lineStyle(t2, inkSoft, 30)}>{LINE2[1]}</p>
        <div style={{height: 88}} />
        <p style={lineStyle(t3, ink, 38, true)}>{LINE4A}</p>
        <p
          style={{
            ...lineStyle(t4, C.accent, 62, true),
            // 末行强调:轻微放大落定
            transform: `translateY(${(1 - t4) * 18}px) scale(${0.96 + t4 * 0.04})`,
            letterSpacing: '0.04em',
            textShadow: `0 0 60px rgba(194, 65, 12, ${0.35 * t4})`,
          }}
        >
          {LINE4B}
        </p>
      </div>
    </AbsoluteFill>
  );
};
