import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_BODY, FONT_DISPLAY} from '../lib/tokens';
import {easeOutCubic} from '../lib/ease';
import {BrandMark} from '../lib/brand';

// 工程自检用标题卡:真实品牌 logo + 产品名,验证 token 与品牌组件在渲染链中正常。
// 不属于成片时间线,只挂独立 Composition 供静帧抽查。
export const TitleCard: React.FC = () => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 15], [0, 1], {extrapolateRight: 'clamp'});
  const rise = interpolate(frame, [0, 20], [24, 0], {
    extrapolateRight: 'clamp',
    easing: easeOutCubic,
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: C.bg,
        justifyContent: 'center',
        alignItems: 'center',
        fontFamily: FONT_DISPLAY,
      }}
    >
      <div style={{opacity, transform: `translateY(${rise}px)`, textAlign: 'center'}}>
        <div style={{margin: '0 auto 40px', width: 120}}>
          <BrandMark size={120} />
        </div>
        <h1
          style={{
            fontSize: 96,
            color: C.fg,
            margin: 0,
            fontWeight: 500,
            letterSpacing: '0.06em',
          }}
        >
          篝火智答
        </h1>
        <p
          style={{
            fontSize: 30,
            color: C.muted,
            margin: '28px 0 0',
            letterSpacing: '0.2em',
            fontFamily: FONT_BODY,
          }}
        >
          Campfire-AI
        </p>
      </div>
    </AbsoluteFill>
  );
};
