// S9 边界与收尾(v16:时间点按本段时长比例派生,见 lib/shotTiming.ts):
// ① 边界声明(0→37%):三句离散落位,每句都是可见事件 + 持续光扫
// ② 品牌落定(37%→100%):字标逐字压印 → rule 生长 → 呼吸点 → 渐隐 + 品牌 hold
// 注:此段不靠「缓慢微动」制造运动——帧差测不出、观众也看不出,那是拖沓而非节奏。
//     节奏来自离散落位(字标逐字、线条生长、呼吸点)与横穿画面的光扫。
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';

import {useShotTiming} from '../lib/shotTiming';
import {C, FONT_BODY, FONT_DISPLAY} from '../tokens';

const B1 = '篝火智答不替代医生、不替代专业服务——';
const B2 = '它做的,是把散落的专业知识,和你们的经验,聚成一堆篝火。';
const B3 = '不是替你判断,是陪你看见。';
const WORDMARK = '篝火智答';

export const S9Closing: React.FC = () => {
  const frame = useCurrentFrame();
  const t = useShotTiming();

  /**
   * 两段的分界(比例)。
   *
   * 依据:边界声明是三句话,品牌落定是「字标压印 + 线 + 副标 + hold」四个动作,
   * 后者动作更多、还含 final-review B3 要求的 ≥1s 品牌 hold,因此给它更多时间。
   */
  const BOUNDARY_END_R = 0.37;

  /**
   * ① 边界声明:三句离散落位(每句都是一次可见事件)。
   *
   * ★ v16 二次修正(我全片扫均匀帧时抓出 f4950-4957 = 8 帧纯纸色):
   *   成因是两端各让一步 —— S8 在自己末尾把内容淡到 0(fadeOut 起于段内 0.94),
   *   而 S9 的第一句原本 0.02 才起(段内第 6 帧),且开场光扫在 x=-560(完全在画外)。
   *   接缝处因此有约 0.27s **整屏只有一个颜色**。
   *
   *   修法:**第一句在第 0 帧就已经在场**(不淡入)。S8 刚把画面淡走,观众的眼睛正等着
   *   新内容;让边界声明第一句直接出现,读起来是「硬切 + 立刻进入边界声明」。
   *   这也符合这一段的功能 —— 它是免责声明,越早出现在画面上越稳妥。
   */
  const b1 = 1;
  const b2 = interpolate(frame, t.span(0.1, 0.16), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.25, 0, 0.3, 1),
  });
  const b3 = interpolate(frame, t.span(0.193, 0.253), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.25, 0, 0.3, 1),
  });
  const boundaryOut = interpolate(frame, t.span(0.307, BOUNDARY_END_R), [1, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  // ② 品牌落定:字标逐字压印是离散事件(每字一次)
  //
  // ★ 起点要**略早于** boundaryOut 归零的时刻(0.02 的搭接),不能正好接上。
  //   两段边界"首尾相接"看似干净,实则会在衔接的那一帧产生一个
  //   **两边都是 0** 的瞬间:边界句已淡净、首字还没开始 → 整屏单色
  //   (我扫全片均匀帧时抓到 f5061 恰好 std=0.0000)。
  //   给 0.02 的搭接后,过渡期两段同时半透明(交叉淡入),不存在全零帧。
  const stampFrom = BOUNDARY_END_R - 0.02;
  const stampStep = 0.017;
  const stampSpan = 0.047;
  const brandIn = (i: number) =>
    interpolate(frame, t.span(stampFrom + i * stampStep, stampFrom + i * stampStep + stampSpan), [0, 1], {
      extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
      easing: Easing.bezier(0.2, 0.7, 0.25, 1),
    });
  const rule = interpolate(frame, t.span(0.633, 0.72), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.2, 1),
  });
  const subIn = interpolate(frame, t.span(0.72, 0.79), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  // 呼吸点(周期不随段长变,它是「心跳」而不是段落节拍)
  const breath = 0.4 + 0.6 * Math.sin((frame / 48) * Math.PI * 2 - Math.PI / 2);

  // ★ 边界声明段的运动(修补历史上这里出现过的 4.2s 静止):
  //   三句落位完成后整块内容曾完全不动,而那段有 4 秒 —— 观众看到的是静止画面。
  //   修法不是「加一点缓慢微动」(那样帧差测不出,见 lib/camera.ts),而是给**可见事件**:
  //     ① 光扫横穿画面(全帧级运动)
  //     ② 缓慢但可测的横向漂移(每 30 帧约 14px)
  //
  // ★ v16 二次修正(独立终检 + 我复算都测到 f5031-5101 = 2.33s 静止):
  //   初版光扫止于 0.36,而**三句在 0.253 就落定完了** —— 于是 0.253→0.307
  //   这段既没有落位事件、光扫又已经跑出画面(2540 已在画外),整块只剩
  //   0.23px/帧 的漂移(帧差测不出)。而它后面紧接 boundaryOut 渐隐到 0.37,
  //   渐隐期间内容变淡、帧差同样很小。两段连起来就是一个 2.3s 的空档。
  //
  //   修法:让光扫在整个边界段内**来回巡游**(和 S2 同一个结论 —— 单次横穿
  //   走完就没了,必须让它不驶出画面),并适当提高亮度让它在缩略图上也测得出。
  const boundarySweepX = (() => {
    const ph = (frame / Math.max(1, t.at(BOUNDARY_END_R))) * Math.PI * 1.6;
    return interpolate(Math.sin(ph - Math.PI / 2), [-1, 1], [-560, 2480]);
  })();
  const boundaryDrift = interpolate(frame, t.span(0, BOUNDARY_END_R), [0, 26], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.4, 0, 0.6, 1),
  });

  // 品牌 hold:字标与副标都落定后**不动**至少 1 秒(final-review B3 的硬要求),
  //   同时叠加缓慢推近(幅度 0.04 ≈ 每 30 帧 0.03,可测),让静止段仍有全帧级变化。
  const brandHoldScale = interpolate(frame, t.span(0.72, 0.93), [1.0, 1.04], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.linear,
  });

  // 可见的光扫:一道宽 520px 的暖光横穿画面(全帧级运动,不是微小抖动)。
  // 微小连续缓动帧差测不出、观众也看不出——那是拖沓;光扫是真正可见的事件。
  const sweepX = interpolate(frame, t.span(0.43, 0.87), [-560, 2480], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.35, 0, 0.65, 1),
  });
  const sweepOn = frame >= t.at(0.43) ? 1 : 0;

  // 整体渐隐(最后约 10%)
  const fadeOut = interpolate(frame, t.span(0.9, 1), [1, 0.06], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{backgroundColor: C.bg}}>
      {/* ① 边界声明:三句离散落位(每句 16f 内完成,是可见事件)
          + 持续横穿的光扫与缓慢漂移(修补该段原本的 4.2s 静止) */}
      <AbsoluteFill
        style={{
          justifyContent: 'center', alignItems: 'center',
          opacity: boundaryOut,
        }}
      >
        {/* 光扫:宽 420px 的暖光在画面内往返(不驶出 —— 单次横穿会在走完后留下空档)。
            ★ 亮度取 accent33/accent4d(20%/30%):初版的 8%/13% 在浅色底上对比太低,
              「帧差测不出」—— 和 S2 是同一个坑(运动存在但太弱)。光扫是本段
              唯一的大面积运动来源,必须真的测得出。 */}
        <div
          style={{
            position: 'absolute', top: 0, bottom: 0, width: 420,
            left: boundarySweepX,
            background: `linear-gradient(90deg, transparent, ${C.accent}33, ${C.accent}4d, ${C.accent}33, transparent)`,
            pointerEvents: 'none',
          }}
        />
        <div
          style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            transform: `translateX(${String(boundaryDrift)}px)`,
          }}
        >
        <p
          style={{
            opacity: b1, transform: `translateY(${(1 - b1) * 16}px)`,
            fontSize: 40, color: C.fg, fontFamily: FONT_DISPLAY,
            fontWeight: 500, margin: 0, letterSpacing: '0.02em',
          }}
        >
          {B1}
        </p>
        <p
          style={{
            opacity: b2, transform: `translateY(${(1 - b2) * 16}px)`,
            fontSize: 32, color: C.fg2, fontFamily: FONT_BODY,
            margin: '48px 0 0', maxWidth: 1240, textAlign: 'center', lineHeight: 1.8,
          }}
        >
          {B2}
        </p>
        <p
          style={{
            opacity: b3, transform: `translateY(${(1 - b3) * 16}px)`,
            fontSize: 44, color: C.accent, fontFamily: FONT_DISPLAY,
            fontWeight: 500, margin: '56px 0 0', letterSpacing: '0.06em',
          }}
        >
          {B3}
        </p>
        </div>
      </AbsoluteFill>

      {/* ② 品牌落定:推近 + 可见光扫(全帧级运动,治拖沓) */}
      <AbsoluteFill
        style={{
          justifyContent: 'center', alignItems: 'center',
          opacity: fadeOut,
        }}
      >
        {/* 暖光横扫:宽 520px 的斜向渐变带,横向穿过整幅画面 */}
        {sweepOn ? (
          <div
            style={{
              position: 'absolute',
              left: sweepX,
              top: -120,
              width: 520,
              height: 1320,
              transform: 'rotate(14deg)',
              background: `linear-gradient(90deg, rgba(194,65,12,0) 0%, rgba(194,65,12,0.30) 42%, rgba(255,250,240,0.55) 52%, rgba(194,65,12,0.18) 62%, rgba(194,65,12,0) 100%)`,
              mixBlendMode: 'multiply',
              pointerEvents: 'none',
            }}
          />
        ) : null}
        <div
          style={{
            textAlign: 'center',
            // 缓慢推近 + 极轻上下浮动:2s 周期内画面始终在变
            transform: `scale(${brandHoldScale}) `,
            transformOrigin: 'center center',
          }}
        >
          {/* 呼吸点 */}
          <div
            style={{
              width: 14, height: 14, borderRadius: 9999,
              backgroundColor: C.accent, margin: '0 auto 44px',
              opacity: frame >= 116 ? breath : 0,
              boxShadow: `0 0 ${22 * breath}px ${C.accent}`,
            }}
          />

          <div
            style={{
              fontFamily: FONT_DISPLAY, fontSize: 108, fontWeight: 500, color: C.fg,
              letterSpacing: '0.06em', lineHeight: 1,
              display: 'inline-flex', alignItems: 'flex-end',
            }}
          >
            {WORDMARK.split('').map((ch, i) => {
              const t = brandIn(i);
              return (
                <span
                  key={i}
                  style={{
                    display: 'inline-block', opacity: t,
                    transform: `scale(${1.4 - 0.4 * t})`, transformOrigin: 'center bottom',
                    filter: `blur(${(1 - t) * 5}px)`,
                  }}
                >
                  {ch}
                </span>
              );
            })}
          </div>

          <div
            style={{
              height: 3, width: 180, margin: '36px auto 0', borderRadius: 2,
              background: C.accent, transform: `scaleX(${rule})`,
            }}
          />

          <div
            style={{
              fontFamily: FONT_BODY, fontSize: 24, color: C.fg2,
              letterSpacing: '0.12em', marginTop: 32, opacity: subIn,
            }}
          >
            不替代医生、不替代专业服务
          </div>

          <div
            style={{
              fontFamily: FONT_BODY, fontSize: 16, color: C.muted,
              letterSpacing: '0.24em', marginTop: 22, opacity: subIn,
            }}
          >
            Campfire-AI
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
