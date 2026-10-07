import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_BODY} from '../lib/tokens';
import {easeOutCubic} from '../lib/ease';
import {PhoneFrame} from '../components/PhoneFrame';
import {CaseLibraryScreen} from '../placeholders/CaseLibraryScreen';

// ⑤ 案例库(132-144s,对应 shot-list ⑤-a~⑤-b)。
// 占位版:列表滚过,镜头在「虚构样例」标注上停留 2s(AC-06 同屏可辨)。

export const S5CaseLibrary: React.FC = () => {
  const frame = useCurrentFrame();

  // 前 4s 列表缓慢上移(滚动感),之后 zoom 到首行「虚构样例」标注并 Hold
  const scroll = interpolate(frame, [0, 120], [0, 60], {
    extrapolateRight: 'clamp',
    easing: easeOutCubic,
  });
  const zoom = interpolate(frame, [120, 210], [1, 1.15], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: easeOutCubic,
  });
  const pan = interpolate(frame, [120, 210], [0, 200], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: easeOutCubic,
  });

  const cap1 = interpolate(frame, [20, 45], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  }) * interpolate(frame, [180, 205], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const cap2 = interpolate(frame, [220, 250], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const fadeOut = interpolate(frame, [330, 360], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{backgroundColor: C.bg, opacity: fadeOut}}>
      <PhoneFrame scale={zoom}>
        <div style={{transform: `translateY(${-(scroll + pan)}px)`, height: '100%'}}>
          <CaseLibraryScreen />
        </div>
      </PhoneFrame>

      <div
        style={{
          position: 'absolute',
          right: 120,
          top: 200,
          width: 560,
          fontFamily: FONT_BODY,
        }}
      >
        <div style={{fontSize: 20, color: C.muted, letterSpacing: '0.25em'}}>案例库</div>
        <div style={{marginTop: 20, height: 2, width: 120, backgroundColor: C.accent}} />
      </div>

      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 72,
          textAlign: 'center',
          opacity: cap1,
          fontSize: 30,
          color: C.fg,
          fontFamily: FONT_BODY,
          letterSpacing: '0.04em',
        }}
      >
        遇到没经历过的事,还可以翻案例库
      </div>
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 72,
          textAlign: 'center',
          opacity: cap2,
          fontSize: 30,
          color: C.fg,
          fontFamily: FONT_BODY,
          letterSpacing: '0.04em',
        }}
      >
        虚构样例和真实案例,一眼可辨
      </div>
    </AbsoluteFill>
  );
};
