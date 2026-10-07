// S7 记忆与档案 —— **两幕**:档案(孩子)15s + 记忆(账号)11s。
//
// ── 为什么拆两幕(2026-10-07,用户裁决「甲」方案)──
//   产品的档案与记忆是**两件归属不同的东西**:
//     · 档案(ProfilePage,/profile):关于**支持对象**(孩子),条目带确认层;
//     · 记忆(MemoryPage,/settings/memory):关于**使用者本人**,账号级时间线,
//       可纠正、可删除,与孩子档案分开保存(页面原文如此)。
//   原版 S7 标题写「记忆与档案」,画面却只有档案 —— 名实不符。现在两幕都演,
//   「分开保存」这件事才在画面上成立。
//
// ── 素材纪律(重要)──
//   记忆幕的数据来自 src/fixtures/memory.generated.ts,由
//   verify/memory-episodes.py export 走**产品读路径**(read_timeline)导出;
//   其条目是**演示种子数据**(source 自描述为 fixture-memory-seed),
//   **不是真实使用者的记录**。交付文档按同一口径登记,不得声称来自真实使用者。
//   档案幕的数据仍是数据库导出的真实 demo 种子(与其余各段同源)。
//
// ── 与旧版的关系 ──
//   · 删除相机周期漂移(见 lib/camera.ts 顶部);改为单向推近 + 分阶推近。
//   · 描边/下划线由「瞬间出现」改 **draw-on**(clip-path 横扫)——
//     它是「我确认了这一条」的一次事件,不是常亮装饰。
//   · 确认按钮的 sin 脉冲改 **press-pop**(按下去一次,然后静止)。
import {Easing, interpolate, useCurrentFrame} from 'remotion';
import {MemoryRouter} from 'react-router';

import {ProfilePage} from '../../../../apps/web/src/features/profile/view/ProfilePage';
import {MemoryPage} from '../../../../apps/web/src/features/memory/view/MemoryPage';
import {DeviceStage, FilmRoot} from '../lib/DeviceStage';
import {NoteBody, NoteKicker, NoteTitle, NOTE_X} from '../lib/Shot';
import {scrollTo, markScrollPx} from '../lib/pageScroll';
import {pushCamera, stagedPush} from '../lib/camera';
import {useShotTiming} from '../lib/shotTiming';
import {makeProfilePort, CANDIDATE_ITEMS, CONFIRMED_ITEMS, makeMemoryPort} from '../fixtures/ports';

const PORT = makeProfilePort();
const MEMORY_PORT = makeMemoryPort();

/** 两幕分界:档案 15s + 记忆 11s(共 26s)。按比例给,段长变化自动跟随。 */
const ACT_B_R = 15 / 26;

export const S7Memory: React.FC = () => {
  const frame = useCurrentFrame();
  const t = useShotTiming();

  /** 幕内比例 → 绝对帧。a() 是档案幕,b() 是记忆幕。 */
  const a = (ratio: number) => t.at(ACT_B_R * ratio);
  const b = (ratio: number) => t.at(ACT_B_R + (1 - ACT_B_R) * ratio);
  const actBFrame = a(1);

  const inActB = frame >= actBFrame;

  // ── 相机:单向推近 + 四阶分阶(语义:档案首屏 → 待确认 → 确认翻转 → 记忆时间线)──
  const camScale = pushCamera(frame, 1.0, 1.18, t.duration).scale;
  const stageScale = stagedPush(
    frame,
    [1.0, 1.06, 1.12, 1.18],
    [0, a(0.2), a(0.78), b(0.5)],
  );
  const scale = Math.max(camScale, stageScale);

  // ── 换场:档案幕在自己的末段淡到 **0**(中途消失的元素必须降到 0),
  //    记忆幕从 0.35 起(保证交界帧就有内容,不会出现整屏纯色)。──
  const actAOut = 1 - interpolate(frame, [actBFrame - 8, actBFrame], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  const actBIn = interpolate(frame, [actBFrame, actBFrame + 10], [0.35, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  const fadeOut = interpolate(frame, t.span(0.972, 1), [1, 0.06], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  // ────────────────────────── 幕一:档案 ──────────────────────────
  /** 屏内滚动:用实测元素位置(markScrollPx),不是猜的像素。 */
  const profileScroll = interpolate(
    frame,
    [0, a(0.2), a(0.44), t.duration],
    [0, scrollTo('profile', 0.05), markScrollPx('profile', 'pendingGroup') * 0.92,
      markScrollPx('profile', 'pendingGroup')],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.35, 0, 0.25, 1)},
  );
  /** 候选条目描边的 draw-on(左→右横扫)。 */
  const ringDraw = interpolate(frame, [a(0.44), a(0.56)], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.25, 0, 0.2, 1),
  });
  /** 确认按钮的一次按压回弹(0.56 起,0.70 收)。 */
  const pressOn = interpolate(frame, [a(0.56), a(0.62)], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.2, 0.75, 0.3, 1),
  });
  const pressPop = 1 - interpolate(frame, [a(0.62), a(0.70)], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  /** 状态翻转(右栏文案里的「待确认 → 已确认」)。 */
  const flip = interpolate(frame, [a(0.78), a(0.90)], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.4, 0, 0.2, 1),
  });
  const tagFlip = interpolate(frame, [a(0.82), a(0.88)], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  const noteIn = (ratio: number) =>
    interpolate(frame, t.span(ratio, ratio + 0.05), [0, 1], {
      extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
      easing: Easing.bezier(0.2, 0.7, 0.25, 1),
    });

  const pending = CANDIDATE_ITEMS[0];
  const confirmedCount = CONFIRMED_ITEMS.length;

  // ────────────────────────── 幕二:记忆 ──────────────────────────
  /**
   * 记忆幕不滚动。
   *
   * 取景只覆盖第一组(见下方样式里的说明):设备层既不滚动也不裁切,滚到第二组
   * 只会把内容漏到机身外。等设备层修好再恢复「滚到第二组」。
   */
  const memoryScroll = 0;
  /** 删除按钮的一次高亮(单次,不做持续脉动)。 */
  const delOn = interpolate(frame, [b(0.70), b(0.79)], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.2, 0.75, 0.3, 1),
  });
  const memoryNoteIn = (ratio: number) =>
    interpolate(frame, t.span(ACT_B_R + (1 - ACT_B_R) * ratio,
                              ACT_B_R + (1 - ACT_B_R) * ratio + 0.035), [0, 1], {
      extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
      easing: Easing.bezier(0.2, 0.7, 0.25, 1),
    });

  /**
   * 时间线三行**逐一落位**。
   *
   * 选择器用 `article.list-row:nth-of-type(N)`:article 在 `.gc-body` 里是同类兄弟,
   * 序号稳定(不像 nth-child 会被非 article 兄弟挤偏)。每一行只驱动 opacity 与位移,
   * 值都是 frame 的纯函数。
   */
  const rowLand = (start: number) => {
    const p = interpolate(frame, [b(start), b(start + 0.09)], [0, 1], {
      extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
      easing: Easing.bezier(0.2, 0.7, 0.25, 1),
    });
    return {opacity: p, transform: `translateY(${(1 - p) * 14}px)`};
  };
  const row1 = rowLand(0.20);
  const row2 = rowLand(0.32);

  return (
    <FilmRoot>
      <div style={{position: 'absolute', inset: 0, opacity: fadeOut}}>
        {/* ── 幕一:档案(ProfilePage)。高亮与描边全部**长在真实元素上**,
              不另画一层 —— 旧版截图路线在这里栽过「框没匡准」。 ── */}
        {!inActB ? (
          <>
            <style>{`
              .film-root details.group-collapse:has(.list-row.candidate-record) {
                position: relative;
              }
              .film-root details.group-collapse:has(.list-row.candidate-record) > summary {
                position: relative;
              }
              .film-root details.group-collapse:has(.list-row.candidate-record) > summary::after {
                content: '';
                position: absolute;
                inset: -4px -6px;
                border: 2px dashed var(--status-unruled);
                border-radius: 12px;
                pointer-events: none;
                opacity: ${String(ringDraw * 0.9)};
                clip-path: inset(0 ${String((1 - ringDraw) * 100)}% 0 0);
              }
              .film-root .list-row.candidate-record { position: relative; }
              .film-root .list-row.candidate-record::after {
                content: '';
                position: absolute;
                inset: -6px;
                border: 3px solid var(--accent);
                border-radius: 14px;
                pointer-events: none;
                opacity: ${String(ringDraw * 0.95)};
                clip-path: inset(0 ${String((1 - ringDraw) * 100)}% 0 0);
                box-shadow: 0 6px 26px rgba(194, 65, 12, 0.2);
              }
              .film-root .list-row.candidate-record .btn-secondary {
                position: relative;
                z-index: 4;
                transform: scale(${(1 + pressPop * 0.04).toFixed(3)});
              }
              .film-root .list-row.candidate-record .btn-secondary::after {
                content: '';
                position: absolute;
                inset: ${(-5 - pressPop * 3).toFixed(1)}px;
                border: 3px solid var(--accent);
                border-radius: 9999px;
                pointer-events: none;
                opacity: ${String(pressOn * (0.55 + pressPop * 0.45))};
                box-shadow: 0 6px 24px rgba(194, 65, 12, ${String(0.2 + pressPop * 0.2)});
              }
            `}</style>
            <div style={{opacity: actAOut}}>
              <DeviceStage cx={640} cy={540} scale={scale} scrollY={profileScroll}>
                <MemoryRouter initialEntries={['/profile']}>
                  <ProfilePage port={PORT} />
                </MemoryRouter>
              </DeviceStage>
            </div>
          </>
        ) : null}

        {/* ── 幕二:记忆(MemoryPage)。三行落位 + 删除按钮单次高亮,全部
              作用在真实元素上(nth-of-type 序号由 DOM 结构决定,不靠猜)。 ── */}
        {inActB ? (
          <>
            <style>{`
              /* ★ 2026-10-07 实测记录(为什么这里不是「滚动到第二组」):
                 记忆页内容比屏幕高时,影片里**既不滚动也不裁切** —— 第二组卡片会压到
                 机身下缘之外。三处证据:
                   · 静帧 f4310/f4440:第二组 tile 印在机身 bezel 之外;
                   · v16 成片同段(档案幕, t=133.3s)有同样现象 ⇒ **既有缺陷**,非本轮引入;
                   · 本文件曾加 \`.film-root .device-screen { overflow: hidden }\` 重渲,
                     仍然溢出 ⇒ 该盒在影片里不生成盒模型(overflow 无效),
                     也解释了设备侧的 \`scrollHeight - clientHeight\` 夹紧恒为 0(不滚动)。
                 结论:在修好影片的设备层裁切之前,记忆幕**只呈现第一组**(它完整在屏内),
                 第二组隐藏 —— 宁可少一组,也不让内容漏到机身外。待办见 CHECKPOINT。
                 ⚠ 隐藏是**影片侧**的取景决定,不改产品页面。 */
              .film-root details.group-collapse:nth-of-type(2) { display: none; }
              .film-root details.group-collapse:nth-of-type(1) .gc-body article.list-row:nth-of-type(1) {
                opacity: ${row1.opacity.toFixed(3)};
                transform: ${row1.transform};
              }
              .film-root details.group-collapse:nth-of-type(1) .gc-body article.list-row:nth-of-type(2) {
                opacity: ${row2.opacity.toFixed(3)};
                transform: ${row2.transform};
              }
              .film-root .gc-body article.list-row .btn-quiet { position: relative; }
              .film-root .gc-body article.list-row .btn-quiet::after {
                content: '';
                position: absolute;
                inset: -5px;
                border: 2px solid var(--accent);
                border-radius: 9999px;
                pointer-events: none;
                opacity: ${String(delOn * 0.9)};
                box-shadow: 0 4px 18px rgba(194, 65, 12, ${String(delOn * 0.25)});
              }
            `}</style>
            <div style={{opacity: actBIn}}>
              <DeviceStage cx={640} cy={540} scale={scale} scrollY={memoryScroll}>
                <MemoryRouter initialEntries={['/settings/memory']}>
                  <MemoryPage port={MEMORY_PORT} />
                </MemoryRouter>
              </DeviceStage>
            </div>
          </>
        ) : null}

        {/* ── 右栏说明:两幕各说一件事 ── */}
        {!inActB ? (
          <div style={{position: 'absolute', left: NOTE_X, top: 250, width: 790}}>
            <NoteKicker opacity={noteIn(0.013)}>记忆与档案 · 档案</NoteKicker>
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

            {pending !== undefined ? (
              <div
                style={{
                  marginTop: 34, padding: '20px 22px', borderRadius: 14,
                  border: '2px solid var(--status-unruled)',
                  backgroundColor: 'var(--surface)',
                  opacity: noteIn(0.33),
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

            <NoteBody opacity={flip} top={28}>
              确认之后,这条才进入「关于 TA 的当前认识」,
              <br />
              并且从此可以被后续咨询预取。
            </NoteBody>
          </div>
        ) : (
          <div style={{position: 'absolute', left: NOTE_X, top: 250, width: 790}}>
            <NoteKicker opacity={memoryNoteIn(0.02)}>记忆与档案 · 记忆</NoteKicker>
            <NoteTitle opacity={memoryNoteIn(0.05)} size={42}>
              你说过的事,
              <br />
              只有你能改。
            </NoteTitle>

            <div
              style={{
                marginTop: 36, fontFamily: 'var(--font-body)', fontSize: 21,
                color: 'var(--muted)', lineHeight: 1.85,
              }}
            >
              <div style={{opacity: memoryNoteIn(0.34)}}>
                记忆归账号、档案归孩子 ——
                <br />
                <span style={{color: 'var(--accent)'}}>分开保存</span>,切换对象也不会变。
              </div>
              <div style={{opacity: memoryNoteIn(0.72), marginTop: 24}}>
                每条都能纠正或删除;
                <br />
                删除后,咨询与历史都不会再用到它。
              </div>
            </div>
          </div>
        )}
      </div>
    </FilmRoot>
  );
};
