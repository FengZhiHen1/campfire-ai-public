import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {C, CANVAS, FONT_BODY, FONT_DISPLAY} from '../lib/tokens';
import {easeOutCubic} from '../lib/ease';
import {PhoneFrame} from '../components/PhoneFrame';
import {InfoSide} from '../components/InfoSide';
import {HomeScreen} from '../placeholders/HomeScreen';

// ② 产品定位(18-30s):构图 A 首亮相——设备框居左(首页占位屏),
// 右侧要点「情境支持 · 可溯源 · 可纠正」;品牌定位文字压底。
// 旁白:「篝火智答,一个装在口袋里的照护伙伴。/ 它记得你孩子的档案,
// 读得懂专业资料,需要的时候,它就在。」(40 字 ≈ 9s)

const CAPTION1 = '篝火智答,一个装在口袋里的照护伙伴。';
const CAPTION2 = '它记得你孩子的档案,读得懂专业资料,需要的时候,它就在。';

export const S2Positioning: React.FC = () => {
  const frame = useCurrentFrame();

  const phoneIn = interpolate(frame, [0, 25], [-60, 0], {
    extrapolateRight: 'clamp',
    easing: easeOutCubic,
  });
  const itemIn = (i: number) =>
    interpolate(frame, [50 + i * 10, 64 + i * 10], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: easeOutCubic,
    });
  const cap1 = interpolate(frame, [20, 40], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: easeOutCubic,
  });
  const cap2 = interpolate(frame, [110, 130], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: easeOutCubic,
  });
  const fadeOut = interpolate(frame, [330, 360], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{backgroundColor: C.bg, opacity: fadeOut}}>
      <InfoSide
        items={[
          {title: '情境支持', desc: '应急与日常,两条入口同构'},
          {title: '可溯源', desc: '每条建议都能点开出处'},
          {title: '可纠正', desc: '推断待确认,不冒充事实'},
        ]}
        appearAt={itemIn}
      />
      <PhoneFrame translateX={phoneIn}>
        <HomeScreen />
      </PhoneFrame>

      {/* 定位文字压底,逐句入场 */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 64,
          textAlign: 'center',
          fontFamily: FONT_DISPLAY,
        }}
      >
        <div
          style={{
            opacity: cap1,
            transform: `translateY(${(1 - cap1) * 14}px)`,
            fontSize: 34,
            fontWeight: 500,
            color: C.fg,
            letterSpacing: '0.03em',
          }}
        >
          {CAPTION1}
        </div>
        <div
          style={{
            opacity: cap2,
            transform: `translateY(${(1 - cap2) * 14}px)`,
            fontSize: 22,
            color: C.muted,
            marginTop: 16,
            fontFamily: FONT_BODY,
          }}
        >
          {CAPTION2}
        </div>
      </div>

      {/* 画布宽引用,防布局漂移时静默错位 */}
      <div style={{position: 'absolute', width: CANVAS.width, height: 0, left: 0, top: 0}} />
    </AbsoluteFill>
  );
};
