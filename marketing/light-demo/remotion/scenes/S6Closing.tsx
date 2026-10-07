import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_BODY, FONT_DISPLAY} from '../lib/tokens';
import {easeOutCubic} from '../lib/ease';
import {BrandMark} from '../lib/brand';

// ⑥ 边界与收尾(144-175s):shot-list Motion 段——边界文字居中,
// 末尾火焰橙 logo + slogan「不是替你判断,是陪你看见」,logo 留 ~5s。

const BOUNDARY1 = '篝火智答不替代医生、不替代专业服务——';
const BOUNDARY2 = '它做的,是把散落的专业知识,和你们的经验,聚成一堆篝火。';
const SLOGAN = '不是替你判断,是陪你看见。';

export const S6Closing: React.FC = () => {
  const frame = useCurrentFrame();

  // 帧窗口 @30fps(段长 930):边界 0.7-8s,logo+slogan 8.5s 起,之后 Hold 至尾
  const b1 = interpolate(frame, [20, 50], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: easeOutCubic,
  });
  const b2 = interpolate(frame, [110, 140], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: easeOutCubic,
  });
  const brand = interpolate(frame, [260, 300], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: easeOutCubic,
  });
  const slogan = interpolate(frame, [330, 365], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: easeOutCubic,
  });
  // 边界文字在 logo 入场时退位
  const boundaryOut = interpolate(frame, [255, 300], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{backgroundColor: C.bg}}>
      {/* 边界声明,居中偏上 */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 0,
          bottom: 0,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          opacity: boundaryOut,
        }}
      >
        <p
          style={{
            opacity: b1,
            transform: `translateY(${(1 - b1) * 16}px)`,
            fontSize: 34,
            color: C.fg,
            fontFamily: FONT_DISPLAY,
            fontWeight: 500,
            margin: 0,
            letterSpacing: '0.02em',
          }}
        >
          {BOUNDARY1}
        </p>
        <p
          style={{
            opacity: b2,
            transform: `translateY(${(1 - b2) * 16}px)`,
            fontSize: 28,
            color: C.fg2,
            fontFamily: FONT_BODY,
            margin: '40px 0 0',
            maxWidth: 1100,
            textAlign: 'center',
            lineHeight: 1.8,
          }}
        >
          {BOUNDARY2}
        </p>
      </div>

      {/* logo + slogan 收束,Hold 至片尾 */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 0,
          bottom: 0,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
        }}
      >
        <div
          style={{
            opacity: brand,
            transform: `translateY(${(1 - brand) * 20}px) scale(${0.92 + brand * 0.08})`,
            filter: `drop-shadow(0 0 48px rgba(194, 65, 12, ${0.3 * brand}))`,
          }}
        >
          <BrandMark size={120} />
        </div>
        <div
          style={{
            opacity: slogan,
            transform: `translateY(${(1 - slogan) * 16}px)`,
            fontSize: 44,
            color: C.fg,
            fontFamily: FONT_DISPLAY,
            fontWeight: 500,
            marginTop: 48,
            letterSpacing: '0.04em',
          }}
        >
          {SLOGAN}
        </div>
        <div
          style={{
            opacity: slogan,
            fontSize: 22,
            color: C.muted,
            fontFamily: FONT_BODY,
            marginTop: 28,
            letterSpacing: '0.3em',
          }}
        >
          篝火智答 · Campfire-AI
        </div>
      </div>
    </AbsoluteFill>
  );
};
