// S7 记忆与档案 —— 用**真实 ProfilePage 组件 + 真实档案数据**。
//
// ── 为什么这次不会「框没匡准」 ─────────────────────────────────────────────
// 旧版:在档案页截图上按猜的坐标画高亮框 → 用户实测「这里的框没匡准」。
// 新版:高亮直接作用在**真实的条目元素**上 —— 用 CSS 选择器命中该条目里的
//       「确认」按钮并给它 outline。元素位置由 DOM 决定,框必然贴合。
//       (旧版的根本错误是「另画一层」;这里不再有另一层。)
//
// 档案数据来自 fixture:数据库导出的 8 条真实档案(7 条已确认 + 1 条待确认)。
// 那条待确认的是 ai_inference / unconfirmed,主题「疼痛与过载的区分压力」——
// 正是产品「系统的推断只以待确认存在」的真实体现。
//
// 节奏(660f / 22s):
//   ① 0-190f  档案首屏「关于 TA 的当前认识」+ 推近
//   ② 190-380f 滚到「待确认」分组,高亮那条候选
//   ③ 380-660f 高亮真实「确认」按钮 + 状态翻转为已确认 + 右侧说明
import {Easing, interpolate, useCurrentFrame} from 'remotion';
import {MemoryRouter} from 'react-router';

import {ProfilePage} from '../../../../apps/web/src/features/profile/view/ProfilePage';
import {DeviceStage, FilmRoot} from '../lib/DeviceStage';
import {NoteKicker, NoteTitle, NOTE_X} from '../lib/Shot';
import {scrollTo, markScrollPx} from '../lib/pageScroll';
import {pushCamera} from '../lib/camera';
import {useShotTiming} from '../lib/shotTiming';
import {makeProfilePort, CANDIDATE_ITEMS, CONFIRMED_ITEMS} from '../fixtures/ports';

const PORT = makeProfilePort();

export const S7Memory: React.FC = () => {
  const frame = useCurrentFrame();
  const t = useShotTiming();

  /**
   * 三段划分(比例)。依据:第 ① 段只交代「档案只收你确认过的内容」+ 首屏;
   * 第 ② 段要滚到待确认分组(滚动本身就是运动);第 ③ 段是高亮 + 状态翻转 + 结论,
   * 动作最多,因此给它最多时间。
   */
  const SEG1_END_R = 0.29;
  const SEG2_END_R = 0.58;

  const SEG1_END = t.at(SEG1_END_R);
  const SEG2_END = t.at(SEG2_END_R);

  const seg = frame < SEG1_END ? 0 : frame < SEG2_END ? 1 : 2;

  // 相机:★ 带节拍的推近(lib/camera.ts)——避免「缓慢微动」(每帧位移不可见)。
  const cam = pushCamera(frame, 1.0, 1.18, t.duration, {beat: 12, beatPeriod: 26});

  // 屏内滚动:★ 用实测的 maxScroll 换算(src/page-metrics.json:档案页 maxScroll=4194)。
  // 待确认分组在页面中后段;旧版写死 1980 → 实际没滚到位(用户实测「框没匡准」)。
  // markScrollPx 给出「把该元素滚到屏幕上方 1/4」所需的像素,由真实浏览器量出。
  const scrollY = interpolate(
    frame,
    [0, SEG1_END, SEG2_END, t.duration],
    [
      0,
      scrollTo('profile', 0.05),
      markScrollPx('profile', 'pendingGroup') * 0.9,
      markScrollPx('profile', 'pendingGroup'),
    ],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.35, 0, 0.25, 1)},
  );

  const fadeOut = interpolate(frame, t.span(0.97, 1), [1, 0.06], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  /** 右侧说明条目的落位。cue 用**比例**给,因此段长变化自动跟随。 */
  const noteIn = (ratio: number) =>
    interpolate(frame, t.span(ratio, ratio + 0.04), [0, 1], {
      extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
      easing: Easing.bezier(0.2, 0.7, 0.25, 1),
    });

  // 高亮与确认动作(比例派生)
  const highlight = interpolate(frame, t.span(SEG2_END_R + 0.03, SEG2_END_R + 0.09), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  const confirmPulse = 0.5 + 0.5 * Math.sin((frame / 14) * Math.PI * 2);
  const flip = interpolate(frame, t.span(0.79, 0.91), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.4, 0, 0.2, 1),
  });
  const tagFlip = interpolate(frame, t.span(0.85, 0.9), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  const pending = CANDIDATE_ITEMS[0];
  const confirmedCount = CONFIRMED_ITEMS.length;

  return (
    <FilmRoot>
      <div style={{position: 'absolute', inset: 0, opacity: fadeOut}}>
        <DeviceStage cx={640 + cam.tx} cy={540 + cam.ty} scale={cam.scale} scrollY={scrollY}>
          <MemoryRouter initialEntries={['/profile']}>
            <ProfilePage port={PORT} />
          </MemoryRouter>
        </DeviceStage>

        {/* 高亮层:用 **CSS 选择器命中真实元素**,而不是另画一个框。
            ★ 为什么这次不会「框没匡准」:
              旧版在截图上按猜的坐标画框;这里高亮是该元素自己的 ::after 伪元素,
              位置由布局引擎决定 —— 结构上不可能偏。
            选择器来自 capture/dump-profile-dom.mjs 对真实页面 DOM 的实测:
              · 待确认分组 = details.group-collapse 且 summary 含「待确认」
              · 待确认条目 = .list-row.candidate-record
              · 确认按钮   = 该条目里的 .btn-secondary
            CSS 无法按文本内容选祖先,因此用 :has() 反向命中
            (Chromium 支持 :has,Remotion 用 Chromium 渲染)。 */}
        <style>{`
          .film-root details.group-collapse:has(.list-row.candidate-record) {
            position: relative;
          }
          .film-root details.group-collapse:has(.list-row.candidate-record) > summary {
            position: relative;
          }
          /* 待确认分组标题的描边 */
          .film-root details.group-collapse:has(.list-row.candidate-record) > summary::after {
            content: '';
            position: absolute;
            inset: -4px -6px;
            border: 2px dashed var(--status-unruled);
            border-radius: 12px;
            pointer-events: none;
            opacity: ${String(highlight * 0.9)};
          }
          /* 待确认条目本体 */
          .film-root .list-row.candidate-record {
            position: relative;
          }
          .film-root .list-row.candidate-record::after {
            content: '';
            position: absolute;
            inset: -6px;
            border: 3px solid var(--accent);
            border-radius: 14px;
            pointer-events: none;
            opacity: ${String(highlight * (0.55 + confirmPulse * 0.45))};
            box-shadow: 0 6px 26px rgba(194, 65, 12, ${String(0.14 + confirmPulse * 0.14)});
          }
          /* 真实的「确认」按钮(条目内第一个 btn-secondary) */
          .film-root .list-row.candidate-record .btn-secondary {
            position: relative;
            z-index: 4;
          }
          .film-root .list-row.candidate-record .btn-secondary::after {
            content: '';
            position: absolute;
            inset: -5px;
            border: 3px solid var(--accent);
            border-radius: 9999px;
            pointer-events: none;
            opacity: ${String(confirmPulse > 0.5 ? highlight : 0)};
            box-shadow: 0 6px 24px rgba(194, 65, 12, 0.3);
          }
        `}</style>

        {/* 右侧说明 */}
        <div style={{position: 'absolute', left: NOTE_X, top: 250, width: 790}}>
          <NoteKicker opacity={noteIn(0.013)}>记忆与档案 · 它怎么记住你</NoteKicker>
          <NoteTitle opacity={noteIn(0.026)} size={42}>
            档案只收你直接说过
            <br />
            或确认过的内容。
          </NoteTitle>

          <div
            style={{
              marginTop: 36, fontFamily: 'var(--font-body)', fontSize: 21,
              color: 'var(--muted)', lineHeight: 1.85,
            }}
          >
            <div style={{opacity: noteIn(0.051)}}>
              {/* ★ 不能用 markdown 星号:React 不解析 markdown,原样写 `**x**` 会把星号
                  直接印到画面上(实测踩过)。强调改用 <span> 表达。 */}
              使用者的直接陈述
              <span style={{color: 'var(--accent)'}}>零确认</span>
              入档;
              <br />
              系统的归纳必须以「待确认」存在。
            </div>
            <div style={{opacity: noteIn(0.27), marginTop: 26}}>
              当前 {confirmedCount} 条已确认,
              <br />
              1 条是 AI 归纳、等你裁决。
            </div>
          </div>

          {/* 待确认条目的真实内容 */}
          {seg >= 1 && pending !== undefined ? (
            <div
              style={{
                marginTop: 34, padding: '20px 22px', borderRadius: 14,
                border: '2px solid var(--status-unruled)',
                backgroundColor: 'var(--surface)',
                opacity: noteIn(0.515),
              }}
            >
              <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
                <span
                  style={{
                    fontFamily: 'var(--font-body)', fontSize: 15,
                    color: tagFlip < 0.5 ? 'var(--status-unruled)' : 'var(--status-stable)',
                    border: `2px solid ${tagFlip < 0.5 ? 'var(--status-unruled)' : 'var(--status-stable)'}`,
                    borderRadius: 9999, padding: '3px 16px',
                  }}
                >
                  {tagFlip < 0.5 ? '待确认' : '已确认'}
                </span>
                <span style={{fontFamily: 'var(--font-body)', fontSize: 15, color: 'var(--muted)'}}>
                  {tagFlip < 0.5 ? '· AI 归纳' : '· 由你确认'}
                </span>
              </div>
              <div
                style={{
                  fontFamily: 'var(--font-body)', fontSize: 19, color: 'var(--fg)',
                  marginTop: 14, lineHeight: 1.65,
                }}
              >
                {pending.description}
              </div>
            </div>
          ) : null}

          {seg === 2 ? (
            <div
              style={{
                marginTop: 28, fontFamily: 'var(--font-body)', fontSize: 19,
                color: 'var(--fg-2)', lineHeight: 1.8, opacity: flip,
              }}
            >
              确认之后,这条才进入「关于 TA 的当前认识」,
              <br />
              并且从此可以被后续咨询预取。
            </div>
          ) : null}
        </div>
      </div>
    </FilmRoot>
  );
};
