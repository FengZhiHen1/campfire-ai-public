// S1 品牌开场:准星描画 → 「篝火智答」逐字压印 → 副标打字机 → 品牌 hold → 消散。
//
// ★ v16:时间点改为**从本段时长按比例派生**(见 lib/shotTiming.ts)。
//   原先写死帧号,段长从 90f 改到 120f 时全部失配 —— 段尾会多出 30 帧无事发生。
//   现在 `t.at(0.5)` 永远是「这一段的一半」,改段长不用改本文件。
//
// 硬约束(final-review B3):品牌字标 hold 至少 1 秒。本段 120f(4s),
//   hold 占 0.58→0.82 ≈ 29f ≈ 0.96s —— 略短于 1s,因此再往后延到 0.85(33f ≈ 1.1s)。
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';

import {useShotTiming} from '../lib/shotTiming';
import {C, FONT_BODY, FONT_DISPLAY} from '../tokens';

const WORDMARK = '篝火智答';
const KICKER = '一本安静的照护手册';

export const S1BrandOpen: React.FC = () => {
  const frame = useCurrentFrame();
  const t = useShotTiming();

  // 准星:竖线先画,横线紧随
  //
  // ★ v16 更正(独立终检抓出):初版 vDraw 从 100 起(strokeDashoffset=100 = 一笔都没画),
  //   而字标首字在 0.09 处才起 —— 于是 **f0 是一个完全空白的画面**。
  //   观众按下播放看到的第一帧什么都没有,像是渲染坏了。
  //   现在起手就画出约 40%(offset=60),f0 读作「准星已经画了一小半、正在合拢」。
  //   绘制动画本身不受影响(只是起点前移),但首帧有了明确的主体。
  const vDraw = interpolate(frame, t.span(0, 0.075), [60, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.2, 1),
  });
  const hDraw = interpolate(frame, t.span(0.067, 0.15), [100, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.linear,
  });
  // ★ 这里**必须**降到 0,不能留下限:
  //   crossFade 在段内 0.2–0.28 把准星淡出,之后 **72% 的时间它都不该出现**
  //   (字标压印在它原来的位置)。留 6% 会让准星以 6% 不透明度**常驻**在字标背后。
  //   出场地板只加在「段末淡出」上(那才是接缝问题),不加在这种「中途换场」上。
  const crossFade = interpolate(frame, t.span(0.2, 0.28), [1, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  // 副标打字机:字符速率按段长缩放(4s 段里约每字 3 帧,与 3s 段的观感一致)
  const kickStart = t.at(0.25);
  const perChar = Math.max(1, (t.duration * 0.18) / KICKER.length);
  const kickChars = Math.floor(Math.max(0, frame - kickStart) / perChar);
  const kickDone = kickStart + KICKER.length * perChar;
  /**
   * 打字光标:只在**打字进行中**显示。
   *
   * ★ v16 更正(独立终检抓出):初版让光标在打完后继续**每 2 帧闪动**直到 0.85 处,
   *   于是 f52–f102 的品牌 hold 里有一个 14×24px 的方块在持续闪烁 ——
   *   这段本来是要「字标落定、让眼睛休息」(final-review B3 要求 ≥1s 静止),
   *   结果画面上一直有个东西在闪,**与 hold 的意图相反**。
   *
   *   而且它让我的合规举证失真:我当时抽 f70/f90/f102 三帧比较,恰好落在光标
   *   **同相位**的帧上,得出「三帧逐字节相同 ⇒ 该段完全不动」的结论 ——
   *   抽样撞上周期,是个假阳性。终检用无损抽帧逐个相邻帧对比较才发现。
   *
   *   现在:打字一完成光标立刻消失(这也符合产品的流式行为 —— 输出结束就没有光标),
   *   hold 段因此是真的完全静止。
   */
  const cursorOn = frame >= kickStart && frame < kickDone;

  // 品牌 hold:副标完成 → 0.85 处不动,满足 B3 的「≥1s 静止」
  //
  // ★ v16 二次修正:淡出走**到段末**(1.0)而不是提前归零。
  //   初版是 `[0.85, 1] → [0, 1]`,末帧 opacity=0 —— 加上 S2 首行原本也从 0 淡入,
  //   两者在接缝处叠出一段整屏单色的画面(我扫全片均匀帧时抓到 f118-119)。
  //   现在淡出到段末只走到 **0.55**(不是 0):S2 的首行此时已经硬切在场,
  //   接缝两侧都始终有内容,不存在「两边都空」的帧。
  //   视觉效果不变 —— 硬切前的最后一帧仍明显变淡,只是不再淡到全空。
  const brandOut = interpolate(frame, t.span(0.85, 1), [0, 0.55], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.4, 0, 0.5, 1),
  });

  // 字标逐字压印:每个字在自己的时间窗内完成
  const charStart = 0.09;
  const charStep = 0.032;
  const charSpan = 0.1;

  return (
    <AbsoluteFill style={{backgroundColor: C.bg, justifyContent: 'center', alignItems: 'center'}}>
      <div
        style={{
          textAlign: 'center',
          opacity: 1 - brandOut,
          transform: `translateY(${-brandOut * 40}px) scale(${1 - brandOut * 0.12})`,
        }}
      >
        <svg
          width={64} height={64} viewBox="0 0 64 64"
          style={{display: 'block', margin: '0 auto 34px', opacity: crossFade}}
        >
          <line x1={32} y1={2} x2={32} y2={62} stroke={C.accent} strokeWidth={5}
            strokeLinecap="round" pathLength={100} strokeDasharray={100} strokeDashoffset={vDraw} />
          <line x1={2} y1={32} x2={62} y2={32} stroke={C.accent} strokeWidth={5}
            strokeLinecap="round" pathLength={100} strokeDasharray={100} strokeDashoffset={hDraw} />
        </svg>

        <div
          style={{
            fontFamily: FONT_DISPLAY, fontSize: 128, fontWeight: 500, color: C.fg,
            letterSpacing: '0.06em', lineHeight: 1, whiteSpace: 'pre',
            display: 'inline-flex', alignItems: 'flex-end',
          }}
        >
          {WORDMARK.split('').map((ch, i) => {
            const from = charStart + i * charStep;
            const [d0, d1] = t.span(from, from + charSpan);
            const tt = interpolate(frame, [d0, d1], [0, 1], {
              extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
              easing: Easing.bezier(0.2, 0.7, 0.25, 1),
            });
            // 压印成功的瞬间有一道短高光(离散事件,不是缓动)
            const glint = interpolate(frame, [d1 - 4, d1, d1 + 4], [0, 1, 0], {
              extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
            });
            return (
              <span key={i} style={{
                position: 'relative', display: 'inline-block', opacity: tt,
                transform: `scale(${1.6 - 0.6 * tt})`, transformOrigin: 'center bottom',
                filter: `blur(${(1 - tt) * 6}px)`,
              }}>
                {ch}
                <span style={{
                  position: 'absolute', left: '50%', bottom: -6, transform: 'translateX(-50%)',
                  width: `${glint * 100}%`, height: 2, background: C.accent,
                  opacity: glint, borderRadius: 2,
                }} />
              </span>
            );
          })}
        </div>

        <div style={{
          fontFamily: FONT_BODY, fontSize: 26, letterSpacing: '0.2em', color: C.muted,
          marginTop: 34, height: 30, display: 'flex', justifyContent: 'center', alignItems: 'center',
        }}>
          <span style={{whiteSpace: 'pre'}}>{KICKER.slice(0, kickChars)}</span>
          <span style={{
            display: 'inline-block', width: 14, height: 24, marginLeft: 4,
            background: C.accent, opacity: cursorOn ? 0.85 : 0,
          }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
