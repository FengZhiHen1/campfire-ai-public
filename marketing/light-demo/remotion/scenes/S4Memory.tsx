import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_BODY} from '../lib/tokens';
import {easeOutCubic} from '../lib/ease';
import {PhoneFrame} from '../components/PhoneFrame';
import {ProfileScreen} from '../placeholders/ProfileScreen';
import {ActionCardScreen} from '../placeholders/ActionCardScreen';

// ④ 记忆与档案(92-132s,对应 shot-list ④-a~④-c)。
// 占位版:a 待确认分组特写 → b 纠正操作 → c 第二次应急档案预取(快切对比)。

// 帧窗口 @30fps(段长 1200):a 0-540 | b 540-840 | c 840-1200
const SUB = {a: [0, 540], b: [540, 840], c: [840, 1200]} as const;

const CAPTIONS: {at: [number, number]; text: string}[] = [
  {at: [60, 300], text: '你的观察,直接入档'},
  {at: [320, 510], text: '系统的推断,只能以「待确认」存在'},
  {at: [570, 810], text: '这条推断不对?纠正它'},
  {at: [870, 1170], text: '下一次,它带着这些进来,你不用从头说'},
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

export const S4Memory: React.FC = () => {
  const frame = useCurrentFrame();

  // ④-a:zoom 到「待确认(1)」分组(档案页高约 1/4 处),强调推断与事实的可辨
  const zoomA = interpolate(frame, [SUB.a[0] + 120, SUB.a[0] + 270], [1, 1.1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: easeOutCubic,
  });
  // ④-b:纠正段退回全景,观众看得到操作落在列表上
  const zoomB = interpolate(frame, [SUB.b[0], SUB.b[0] + 30], [1.1, 1], {
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

  const fadeOut = interpolate(frame, [1170, 1200], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{backgroundColor: C.bg, opacity: fadeOut}}>
      {inSub(SUB.a) ? (
        <div style={{opacity: crossFade(SUB.a)}}>
          <PhoneFrame scale={zoomA} focusY={25}>
            <ProfileScreen />
          </PhoneFrame>
        </div>
      ) : null}
      {inSub(SUB.b) ? (
        <div style={{opacity: crossFade(SUB.b)}}>
          <PhoneFrame scale={zoomB} focusY={25}>
            <ProfileScreen />
          </PhoneFrame>
        </div>
      ) : null}

      {/* ④-b 纠正操作提示:待确认条目高亮圈(占位,真实素材为纠正后列表刷新)。
          屏幕内坐标:PhoneFrame 位于 (150,84),内容区减去外壳 padding 14,
          待确认条目约在内容区 y 118-260(页头 + 页标题 + 分组标题之后)。 */}
      {inSub(SUB.b) ? (
        <div
          style={{
            position: 'absolute',
            left: 150 + 14 + 16,
            top: 84 + 14 + 118,
            width: 420 - 28 - 32,
            height: 150,
            borderRadius: 20,
            border: `3px solid ${C.accent}`,
            boxShadow: `0 0 40px rgba(194, 65, 12, 0.3)`,
            pointerEvents: 'none',
            opacity: interpolate(frame, [SUB.b[0] + 40, SUB.b[0] + 70], [0, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            }),
          }}
        />
      ) : null}

      {/* ④-c 第二次应急:行动卡快切,表达「档案预取后更快出结果」 */}
      {inSub(SUB.c) ? (
        <div style={{opacity: crossFade(SUB.c)}}>
          <PhoneFrame>
            <ActionCardScreen />
          </PhoneFrame>
        </div>
      ) : null}

      <div
        style={{
          position: 'absolute',
          right: 120,
          top: 200,
          width: 560,
          fontFamily: FONT_BODY,
        }}
      >
        <div style={{fontSize: 20, color: C.muted, letterSpacing: '0.25em'}}>记忆与档案</div>
        <div style={{marginTop: 20, height: 2, width: 120, backgroundColor: C.accent}} />
      </div>

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
