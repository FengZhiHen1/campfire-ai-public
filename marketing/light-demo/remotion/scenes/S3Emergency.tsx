import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_BODY} from '../lib/tokens';
import {easeOutCubic} from '../lib/ease';
import {PhoneFrame} from '../components/PhoneFrame';
import {HomeScreen} from '../placeholders/HomeScreen';
import {IntakeScreen} from '../placeholders/IntakeScreen';
import {FollowupScreen} from '../placeholders/FollowupScreen';
import {ActionCardScreen} from '../placeholders/ActionCardScreen';

// ③ 应急咨询(30-92s,核心段,四个子场景对应 shot-list ③-a~③-d)。
// 占位版:用风格化近似屏代替 Playwright 真实录屏,镜头运动(zoom/Hold)保持设计。
// 屏幕替换由 timeline 帧窗口驱动,真实素材到位后以 OffthreadVideo 逐段替换。

// 子镜头帧窗口 @30fps(段长 1860):
// a 首页+zoom 入口 0-360 | b 八项采集 360-780 | c 追问 780-1050 | d 行动卡 1050-1860
const SUB = {a: [0, 360], b: [360, 780], c: [780, 1050], d: [1050, 1860]} as const;

const CAPTIONS: {at: [number, number]; text: string}[] = [
  {at: [40, 330], text: '首页按下「应急咨询」'},
  {at: [400, 740], text: '八件现场的事,每一项都可以跳过'},
  {at: [810, 1020], text: '真正会改变判断的,它才追问'},
  {at: [1100, 1440], text: '先排除医疗危险,再给行动建议'},
  {at: [1500, 1830], text: '每一条建议,都能点开看到它的出处'},
];

const captionOpacity = (frame: number, at: readonly [number, number]) => {
  const fade = 20;
  return Math.min(
    interpolate(frame, [at[0], at[0] + fade], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    }),
    interpolate(frame, [at[1] - fade, at[1]], [1, 0], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    }),
  );
};

export const S3Emergency: React.FC = () => {
  const frame = useCurrentFrame();

  // ③-a:首页轻微 zoom(1.0→1.06),焦点在应急入口卡(屏幕高约 1/4 处)
  const zoomA = interpolate(frame, [SUB.a[0] + 30, SUB.a[1] - 30], [1, 1.06], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: easeOutCubic,
  });
  // ③-d:行动卡段缓慢 zoom 到医疗风险三档标注行(屏幕高约 1/5 处),随后 Hold
  const zoomD = interpolate(frame, [SUB.d[0] + 90, SUB.d[0] + 240], [1, 1.15], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: easeOutCubic,
  });

  const inSub = (sub: readonly [number, number]) => frame >= sub[0] && frame < sub[1];
  const crossFade = (sub: readonly [number, number]) =>
    Math.min(
      interpolate(frame, [sub[0], sub[0] + 15], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      }),
      interpolate(frame, [sub[1] - 15, sub[1]], [1, 0], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      }),
    );

  const screens: {
    sub: readonly [number, number];
    node: React.ReactNode;
    scale: number;
    focusY: number;
  }[] = [
    {sub: SUB.a, node: <HomeScreen />, scale: zoomA, focusY: 25},
    {sub: SUB.b, node: <IntakeScreen />, scale: 1, focusY: 50},
    {sub: SUB.c, node: <FollowupScreen />, scale: 1, focusY: 50},
    {sub: SUB.d, node: <ActionCardScreen />, scale: zoomD, focusY: 20},
  ];

  const fadeOut = interpolate(frame, [1830, 1860], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{backgroundColor: C.bg, opacity: fadeOut}}>
      {screens.map((s) =>
        inSub(s.sub) ? (
          <div key={s.sub[0]} style={{opacity: crossFade(s.sub)}}>
            <PhoneFrame scale={s.scale} focusY={s.focusY}>
              {s.node}
            </PhoneFrame>
          </div>
        ) : null,
      )}

      {/* 右侧段标识 */}
      <div
        style={{
          position: 'absolute',
          right: 120,
          top: 200,
          width: 560,
          fontFamily: FONT_BODY,
        }}
      >
        <div style={{fontSize: 20, color: C.muted, letterSpacing: '0.25em'}}>应急咨询</div>
        <div style={{marginTop: 20, height: 2, width: 120, backgroundColor: C.accent}} />
      </div>

      {/* 底部 caption 逐条替换,与旁白句子对应 */}
      {CAPTIONS.map((c) => {
        const o = captionOpacity(frame, c.at);
        return o > 0 ? (
          <div
            key={c.text}
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              bottom: 72,
              textAlign: 'center',
              opacity: o,
              fontSize: 30,
              color: C.fg,
              fontFamily: FONT_BODY,
              letterSpacing: '0.04em',
            }}
          >
            {c.text}
          </div>
        ) : null;
      })}
    </AbsoluteFill>
  );
};
