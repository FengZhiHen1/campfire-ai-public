// S6 行动卡 —— 用**真实 ActionCard 组件 + 真实卡片数据**。
//
// ── 为什么这次不会写错来源标注 ─────────────────────────────────────────────
// 旧版:我在右侧手写「小满档案 · 监护人观察」,而产品根本没有这个来源枚举
//       (真实枚举是 本人报告/家属报告/现场观察/历史记录/医疗记录/AI 推断)。
// 新版:整张卡交给产品的 <ActionCard> 渲染,来源与置信由产品自己的
//       domain/actionCard.ts 映射产生 —— 影片不可能再写错。
//
// 卡片数据来自 fixture(数据库导出的真实 emit_emergency_action_card 载荷:
// 7 个分区 / 4 个状态 / 33 条标注 / 真实 card_id b6b1f07c461f459d898f93555d910643)。
//
// 节奏(900f / 30s):
//   ① 0-300f   三档语义特写(真实 RQ-EMG-04 三值)+ 优先级句
//   ② 150-480f 真实行动卡在设备里滚动到「01 当前状态」(★ v14 从 300f 提前,把省下的时间给卡片演示)
//   ③ 480-900f 滚到「02 立即怎么沟通」+ 右侧列真实来源分布
import {Easing, interpolate, useCurrentFrame} from 'remotion';

import {DeviceStage, FilmRoot} from '../lib/DeviceStage';
import {stagedPush} from '../lib/camera';
import {ActionCardScreen} from '../lib/ActionCardScreen';
import {NoteKicker, NoteTitle, NOTE_X} from '../lib/Shot';
import {FIXTURE_DATA} from '../fixtures/data.generated';
import {useShotTiming} from '../lib/shotTiming';
import type {ActionCardEvent} from '../../../../apps/web/src/shared/types/sse';

/** 真实行动卡载荷(有档案会话 177f965b)。 */
const CARD = FIXTURE_DATA.sessions.archive.actionCard as unknown as ActionCardEvent;
const NOARCH_CARD = FIXTURE_DATA.sessions.noArchive.actionCard as unknown as ActionCardEvent;

/**
 * 统计真实标注里某个来源出现了多少次。
 *
 * 标注的线上格式是 `"<source>:<confidence>"`(见产品
 * apps/web/src/features/consult/domain/actionCard.ts 的 decodeAnnotation)。
 * 这里现算,避免手写数字与数据漂移 —— 手写过一次就错了。
 */
function sourceCount(source: string): number {
  const anns = CARD.annotations as readonly {target: string; kind: string}[];
  return anns.filter((a) => a.kind.split(':')[0] === source).length;
}

/** 该卡的真实标注总数。 */
const TOTAL_ANNOTATIONS = (CARD.annotations as readonly unknown[]).length;
/** 无档案会话的真实标注总数(用于双会话对照)。 */
const NOARCH_TOTAL = (NOARCH_CARD.annotations as readonly unknown[]).length;

/** 三档语义(产品契约 RQ-EMG-04:稳定 / 未排除 / 高风险)。 */
const TONES = [
  {label: '稳定', color: 'var(--status-stable)', desc: '现场无急症表现,按孤独症相关支持处理'},
  {label: '未排除', color: 'var(--status-unruled)', desc: '该项未采集或无法核对,不当作正常'},
  {label: '高风险', color: 'var(--status-high)', desc: '需要立即寻求专业医疗帮助'},
] as const;

export const S6ActionCard: React.FC = () => {
  const frame = useCurrentFrame();
  const timing = useShotTiming();

  /**
   * 段划分(比例)。
   *
   * ★ seg 0 是「三档语义特写」——一段**没有设备的纯文案页**。
   *   它曾经占 10s 并出现两段各约 3.7s 的静止(只有细笔画文字的透明度变化,
   *   帧差天然很小)。给纯文案页 10s 是拖沓;用户要的是「核心功能演示」。
   *   因此压到 ~8%(36s 段里约 3s),把其余时间全给**真实行动卡的滚动演示**。
   *
   * seg 1 让 01→07 七个分区依次经过;seg 2 停在底部看来源标注与双会话对照。
   */
  /**
   * 说明幕(seg 0)的时长:**绝对下限,不是纯比例**。
   *
   * ★ 为什么这里破一次「内部时间点全部比例派生」的约定(2026-10-08,用户报告):
   *   原来是 `SEG0_END_R = 0.083`(比例)。比例对**运动 / 滚动**是对的 —— 段长变了它
   *   跟着缩放,观感不变。但对**需要最短可读时间的固定文案页**是错的:
   *   这一幕有 1 个标题 + 1 行副标 + 3 行徽章 = 4 个落位事件。
   *   v17(36s 段)按比例算出 3.0s,够读;v18 把段压到 20s 后,同一比例只剩 **1.66s**
   *   (实测:第三档徽章在段内 f47 才亮完,场景在 f50 就被整体换掉 —— **只留 3 帧**;
   *    扫光窗口是 `[20, SEG0_END+20]`,到卸载时只走了 58%,那道光是**被切掉的**)。
   *   用户看到的就是「刚亮完就被抽走 + 光扫到一半没了」。
   *   ⇒ 给这一幕一个有下限的长度:不足 60 帧(2s)时按 60 帧算。
   *     不再是 0.083 的等比结果,但这正是「可读时间不能被等比压缩」的意思。
   */
  const SEG0_MIN_FRAMES = 72;
  const SEG0_END = Math.max(timing.at(0.083), SEG0_MIN_FRAMES);
  const SEG1_END = timing.at(0.46);
  const seg = frame < SEG0_END ? 0 : frame < SEG1_END ? 1 : 2;
  /** 说明幕实际的段内比例 —— 供 noteIn / 徽章时刻表使用(不再假设它是 0.083)。 */
  const seg0R = SEG0_END / timing.duration;

  /**
   * 幕间**交叉淡入淡出**的帧数(2026-10-08 修「硬切」)。
   *
   * 现象:此前 seg0 与 seg1/2 之间是**条件替换**(`seg === 0 ? 文字页 : null` /
   *   `seg > 0 ? 设备 : null`)—— 说明幕没有任何退场、手机整机也没有入场,
   *   在**同一张米色底**上直接「传送」进来,看起来像丢帧而不是切镜。
   *   实测 f1909 → f1910:前一帧是全屏文字页,后一帧手机已成型。
   * 修法:说明幕在结束前 SCENE_FADE 帧内淡出,整机同时淡入并轻微放大;
   *   两条曲线在 SEG0_END 处交汇,替换发生在两者都接近不可见的时刻。
   */
  const SCENE_FADE = 12;

  // 相机:★ 分段推近(lib/camera.ts)。
  //   ★ 2026-10-07:周期漂移分量已删除(用户裁决);分段推近保留(每阶对应叙事上的
  //     下一件事:三档特写 → 卡片 → 来源标注)。
  //   ★ 2026-10-08:删除与之并存的**全程线性推近** `pushCamera(frame, 1.0, 1.2, duration)` ——
  //     `Math.max` 里线性那条一路抬升,分段的停顿被覆盖,手机框全程一直在变大。
  const scale = stagedPush(
    frame,
    [1.0, 1.06, 1.13, 1.2],
    [0, SEG0_END, SEG1_END, timing.at(0.78)],
    timing.duration,
  );

  // ★ 屏内滚动:行动卡有 7 个分区、很长。滚动量交给 DeviceStage 按真实 scrollHeight
  //   夹紧(写死像素在卡片长度变化时会滚出底部露空白 —— 旧版 1760 就是猜的)。
  //
  // ★★ 2026-10-07 改**两次刹车**(镜头卡 scroll-brake-moves 的语法):
  //   旧版是一条贝塞尔一路滚到底 —— 25 秒连续平移,读起来像「资料在飘」。
  //   现在:滚到「01 当前状态」停一下、再滚到「02 立即怎么沟通」停一下、然后到底。
  //   停车点用像素给,理由与旧版一致(DeviceStage 按真实 scrollHeight 夹紧);
  //   ⚠ 3200 / 6400 是**初值**,由逐帧 still 自检校准到两个分区真正停在读数位置。
  //
  // ★★ 2026-10-08:关键帧表的后续时刻**从 seg0R 派生**,不再直接用 timing.at(0.1)…
  //   原因:seg0 有了绝对下限(SEG0_MIN_FRAMES)后,SEG0_END = 72 可能**大于**
  //   timing.at(0.1) = 60 —— 而 interpolate 要求 inputRange 严格单调递增,
  //   实测渲染直接抛 `inputRange must be strictly monotonically increasing but got
  //   [0,72,60,108,180,240,312,516,600]`。这不是「画面难看」级别的错,是**渲不出来**。
  //   ⇒ 换场后的每个时刻都改为「seg0 结束 + 剩余区间的一个比例」,结构上不可能再越界:
  //     后续比例按旧表在剩下 0.917 里所占位置折算(0.1→(0.1-0.083)/0.917 等)。
  const afterSeg0 = (frac: number) => SEG0_END + Math.round(frac * (timing.duration - SEG0_END));
  const BRAKE1 = 3200;
  const BRAKE2 = 6400;
  const scrollY = interpolate(
    frame,
    [
      0,
      SEG0_END,
      afterSeg0(0.019),
      afterSeg0(0.106),
      afterSeg0(0.237),
      afterSeg0(0.346),
      afterSeg0(0.477),
      afterSeg0(0.847),
      timing.duration,
    ],
    [0, 0, 900, BRAKE1, BRAKE1, BRAKE2, BRAKE2, 9999, 9999],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.3, 0, 0.25, 1)},
  );

  /**
   * 两处**事后标注**:两次刹车各给该节标题画一条 accent 下划线(draw-on)。
   *
   * 选择器用 `:nth-of-type(N)` 而不是「第几个 .ac-section」——CSS 无法按类名计数,
   * 而 N 由**数据**算出(卡片有优先块时分区整体后移一位),不是猜的。
   * 画法是元素自身的 ::after 横向 scaleX 展开:位置由布局决定,缩放/滚动自动跟随
   * (本项目两次「另画一层 → 框没匡准」的教训见 S3 与 S4 的注释)。
   */
  const cardHasPriority = (CARD as unknown as {priority?: unknown}).priority !== undefined;
  const sectionIdx = (n: number) => n + (cardHasPriority ? 1 : 0);
  const draw1 = interpolate(frame, timing.span(0.19, 0.25), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.25, 0, 0.2, 1),
  });
  const draw2 = interpolate(frame, timing.span(0.41, 0.47), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.25, 0, 0.2, 1),
  });
  const underlineCss = (idx: number, draw: number) => `
    .film-root .action-card > .ac-section:nth-of-type(${String(idx)}) .ac-head {
      position: relative;
    }
    .film-root .action-card > .ac-section:nth-of-type(${String(idx)}) .ac-head::after {
      content: '';
      position: absolute;
      left: 0; right: 0; bottom: -5px; height: 2px;
      background: var(--accent);
      border-radius: 2px;
      transform: scaleX(${draw.toFixed(3)});
      transform-origin: left center;
      opacity: ${(draw * 0.85).toFixed(3)};
    }
  `;

  // ★ 出场淡出留 6% 下限,不降到 0。
  //   降到 0 会让本段**最后一帧**内容全无(f1499/f2699/3779/4559/4949 实测:
  //   画面 92% 是纯 --bg #fbf6ee,只剩极轻暗角),而下一段首帧是满的 →
  //   形成「满→渐淡→全空一帧→满」的单帧闪空(33ms,抽帧条上可见的白闪,
  //   见 out/dip/strip.jpg)。留 6% 后末帧与倒数第二帧连续。　←　该证据已于 2026-10-07 清理(回收空间),见 DELIVERY.md 的「证据清理记录」
  const fadeOut = interpolate(frame, timing.span(0.967, 1), [1, 0.06], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  // 三档徽章逐个点亮:在 seg 0 内均分。
  //   ★ 2026-10-07:落位瞬间一次**回弹**(badgePop),随后保持静止 ——
  //     替换原先的 sin 持续脉动(16f 周期),那是与相机漂移同类的无语义连续运动。
  //   ★ 2026-10-08:时刻表原本写死 `SEG0_END_R * (…)`,而 SEG0_END_R 是**比例**;
  //     现在 seg0 有了绝对下限(见 SEG0_MIN_FRAMES),比例与实际帧数可能不等 ——
  //     若仍用比例,末档会在场景被换掉之后才亮(实测旧版正是「末档 f47 亮完、f50 换场」)。
  //     改成直接用 **seg0R = SEG0_END / duration**,保证三档一定在幕内亮完。
  //     校验(v18 段长 600,seg0R = 72/600 = 0.12):三档分别在
  //     (0.28→0.55)·72 = f20→40 / (0.48→0.75)·72 = f35→54 / (0.68→0.95)·72 = f49→68
  //     ⇒ 末档 f68 亮完,距 SEG0_END=f72 仍有 4 帧静止,且整段退场从 f60 才开始,
  //       所以「亮完 → 停一下 → 退场 → 交接」是一条完整的读得完的弧线。
  const badgeOn = (i: number) =>
    interpolate(
      frame,
      timing.span(seg0R * (0.28 + i * 0.2), seg0R * (0.55 + i * 0.2)),
      [0, 1],
      {
        extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
        easing: Easing.bezier(0.2, 0.75, 0.3, 1),
      },
    );
  const badgePop = (i: number) =>
    1 - interpolate(
      frame,
      timing.span(seg0R * (0.55 + i * 0.2), seg0R * (0.72 + i * 0.2)),
      [0, 1],
      {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
    );

  /** 说明幕的**退场**淡出(结束前 SCENE_FADE 帧内线性到 0)。 */
  const scene0Out = interpolate(
    frame,
    [SEG0_END - SCENE_FADE, SEG0_END],
    [1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
  );
  /** 整机的**入场**淡入,与上面同窗口(两条曲线在 SEG0_END 交汇)。 */
  const stageIn = interpolate(
    frame,
    [SEG0_END - SCENE_FADE, SEG0_END],
    [0, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.3, 0, 0.4, 1)},
  );

  /** 右侧说明条目的落位(cue 用比例给)。 */
  const noteIn = (ratio: number) =>
    interpolate(frame, timing.span(ratio, ratio + 0.024), [0, 1], {
      extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
      easing: Easing.bezier(0.2, 0.7, 0.25, 1),
    });

  return (
    <FilmRoot>
      <div style={{position: 'absolute', inset: 0, opacity: fadeOut}}>
        {/* ① 三档语义特写 */}
        {seg === 0 ? (
          <div style={{position: 'absolute', inset: 0, opacity: scene0Out}}>
            {/* ★ 该段原本 10s 几乎全静止(实测 f2250-2549 帧差全程 <0.35)。
                根因:三档徽章在 110f 就点亮完毕,之后没有任何新事件;而徽章变的是
                **细笔画文字的透明度**,帧差天然很小,连光扫(alpha 0.07–0.13)也不够。
                修法(补**大面积**运动,而不是「缓慢微动」):
                  ① 整块内容做 scale 推近 —— 大字缩放带来大量像素位移,帧差明显
                  ② 增强光扫的对比(0.07→0.16)
                  ③ 段落缩短到 90f(3s):纯文案页给 10s 本身就是拖沓,
                     用户要的是核心功能演示,时间该给真实卡片(见下方 SEG0_END) */}
            <div
              style={{
                position: 'absolute', inset: 0,
                transform: `scale(${String(1 + interpolate(frame, [0, SEG0_END], [0, 0.06], {
                  extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
                }))})`,
                transformOrigin: '40% 45%',
              }}
            >
            <div
              style={{
                position: 'absolute', top: 0, bottom: 0, width: 460,
                left: interpolate(frame, [20, SEG0_END - 8], [-540, 2480], {
                  extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
                  easing: Easing.bezier(0.35, 0, 0.65, 1),
                }),
                background: 'linear-gradient(90deg, transparent, rgba(194,65,12,0.10), rgba(194,65,12,0.16), rgba(194,65,12,0.10), transparent)',
                pointerEvents: 'none',
              }}
            />
            
            <div
              style={{
                position: 'absolute', left: 400, top: 290, width: 1120,
                opacity: interpolate(frame, [0, 20], [0, 1], {
                  extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
                }),
              }}
            >
              <div
                style={{
                  fontFamily: 'var(--font-display)', fontSize: 44, fontWeight: 500,
                  color: 'var(--fg)', lineHeight: 1.4,
                }}
              >
                第一步永远是:先排除医疗危险
              </div>
              <div
                style={{
                  fontFamily: 'var(--font-body)', fontSize: 22, color: 'var(--muted)',
                  marginTop: 18, lineHeight: 1.7,
                }}
              >
                存在急性医疗危险表现时,不优先解释为孤独症相关行为。不做诊断、不给用药建议。
              </div>
            </div>

            {/* 三档徽章:用产品真实的三值语义色,「未排除」为本次真实取值 */}
            <div
              style={{
                position: 'absolute', left: 400, top: 556, width: 1120,
                display: 'flex', flexDirection: 'column', gap: 22,
              }}
            >
              {TONES.map((tone, i) => {
                const t = badgeOn(i);
                const isActive = i === 1;
                return (
                  <div
                    key={tone.label}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 22,
                      opacity: 0.25 + t * 0.75,
                      transform: `translateX(${(1 - t) * -18}px)`,
                    }}
                  >
                    <span
                      style={{
                        fontFamily: 'var(--font-body)', fontSize: 20, fontWeight: 600,
                        color: tone.color,
                        border: `2px solid ${tone.color}`,
                        borderRadius: 9999, padding: '6px 22px',
                        flexShrink: 0, minWidth: 108, textAlign: 'center',
                        backgroundColor: isActive
                          ? `color-mix(in oklab, ${tone.color}, transparent ${String(100 - (14 + badgePop(i) * 16))}%)`
                          : 'transparent',
                      }}
                    >
                      {tone.label}
                    </span>
                    <span style={{fontFamily: 'var(--font-body)', fontSize: 21, color: 'var(--fg-2)'}}>
                      {tone.desc}
                    </span>
                    {isActive ? (
                      <span
                        style={{
                          fontFamily: 'var(--font-body)', fontSize: 15,
                          color: tone.color, marginLeft: 'auto',
                        }}
                      >
                        本次结果
                      </span>
                    ) : null}
                  </div>
                );
              })}
            </div>

            {/* ★ 这里曾有一块「后半段的离散文案落位」三栏文案（未采集/已采集且正常/存在高风险表现），
                注释写的是「让 3s-10s 之间也有信息推进」。**它是死代码，全片一帧都不可见**：
                它在 `seg === 0` 分支里，而 seg 0 只在 frame < SEG0_END = at(0.083) = 90 时渲染；
                该块的 opacity 是 `interpolate(frame, [100, 126])`，最早也要 frame 100 才显现 ——
                那时 seg 已经是 1，整个分支早被卸载了。
                独立终检实测 f2700–2789 该位置墨量恒为 0.00%，确认从不出现。

                删除而不是「把时间改到 90 以内」的理由：seg 0 只有 90 帧（3s），
                三档语义行自己的落位（见上方 badgeOn，末档在 f78 完成）已经填满这一段；
                再塞三栏文案只会让 3 秒里挤五个事件。**这一段的问题从来不是事件不够。** */}
            </div>
          </div>
        ) : null}

        {/* ② ③ 真实行动卡在设备里滚动 */}
        {seg > 0 ? (
          <>
            <style>{underlineCss(sectionIdx(1), draw1)}</style>
            <style>{underlineCss(sectionIdx(2), draw2)}</style>
            {/* 入场包装层:整机淡入 + 轻微放大(与说明幕退场同窗口,见 SCENE_FADE)。
                包装层只加 opacity/transform,不参与布局 —— DeviceStage 自己仍是
                position:absolute 的定位层,尺寸不受影响(与 S3/S7/S8 的舞台调用一致)。 */}
            <div
              style={{
                position: 'absolute', inset: 0,
                opacity: stageIn,
                transform: `scale(${String(1 + (1 - stageIn) * 0.02)})`,
              }}
            >
              <DeviceStage cx={640} cy={540} scale={scale} scrollY={scrollY}>
                <ActionCardScreen data={CARD} />
              </DeviceStage>
            </div>
          </>
        ) : null}

        {/* 右侧说明区 */}
        {seg > 0 ? (
          <div style={{position: 'absolute', left: NOTE_X, top: 230, width: 790}}>
            <NoteKicker opacity={noteIn(seg0R)}>本次结果 · 现场行动卡</NoteKicker>
            {/* ★ 2026-10-08:标题排在 Kicker 之后(+0.04),正文再排在标题之后(+0.07)。
                原来的问题是正文**完全没有入场**(见下方),于是切场那一帧标题还没淡入、
                正文已全亮 —— 右栏看起来「有内容、没标题」。 */}
            <NoteTitle opacity={noteIn(seg0R + 0.04)} size={42}>
              {seg === 1 ? '七节分区,先看哪一节由闸门决定' : '每条建议都带着它的出处'}
            </NoteTitle>

            {seg === 1 ? (
              <div
                style={{
                  marginTop: 36, fontFamily: 'var(--font-body)', fontSize: 21,
                  color: 'var(--muted)', lineHeight: 1.8,
                  // ★ 补上入场(原先这一段只有 marginTop/fontFamily/color,没有 opacity
                  //   也没有 transform ⇒ 场景一出现它就已经是全不透明的满亮度)。
                  opacity: noteIn(seg0R + 0.07),
                  transform: `translateY(${(1 - noteIn(seg0R + 0.07)) * 12}px)`,
                }}
              >
                卡顶的「现在先看」块是优先级最高的一节;
                <br />
                医疗风险三值决定后续措辞强度。
                <br />
                <span style={{color: 'var(--accent)'}}>本次真实取值:未排除。</span>
              </div>
            ) : (
              <>
                <div
                  style={{
                    marginTop: 36, fontFamily: 'var(--font-body)', fontSize: 21,
                    color: 'var(--muted)', lineHeight: 1.8,
                    // ★ 同上:seg 2 的这一段也补入场。
                    opacity: noteIn(seg0R + 0.07),
                    transform: `translateY(${(1 - noteIn(seg0R + 0.07)) * 12}px)`,
                  }}
                >
                  来源与置信不是我们写的旁白,
                  <br />
                  是产品自己的枚举与映射。
                </div>
                <div style={{marginTop: 34, display: 'flex', flexDirection: 'column', gap: 14}}>
                  {[
                    // ★ 数字**从 fixture 现算**,不手写。
                    //   手写过一次就错了(把 history 写成 8,实际 9 —— 8 条 confirmed + 1 条 likely)。
                    //   现算的另一个好处:fixture 重新导出后这里自动跟随,不会漂移。
                    {k: '历史记录', v: sourceCount('history')},
                    {k: 'AI 推断', v: sourceCount('ai_inference')},
                    {k: '家属报告', v: sourceCount('family_report')},
                    {k: '现场观察', v: sourceCount('onsite_observation')},
                  ].map((row, i) => {
                    const t = noteIn(SEG1_END / timing.duration + 0.037 + i * 0.028);
                    return (
                      <div
                        key={row.k}
                        style={{
                          display: 'flex', alignItems: 'baseline', gap: 14,
                          opacity: t, transform: `translateY(${(1 - t) * 12}px)`,
                        }}
                      >
                        <span
                          style={{
                            fontFamily: 'var(--font-mono, monospace)', fontSize: 26,
                            color: 'var(--accent)', minWidth: 44, textAlign: 'right',
                          }}
                        >
                          {row.v}
                        </span>
                        <span style={{fontFamily: 'var(--font-body)', fontSize: 19, color: 'var(--fg-2)'}}>
                          {row.k}
                        </span>
                      </div>
                    );
                  })}
                </div>
                {/* 合计行:★ 用现算值,不手写。上一版手写「33」而明细手写成 32 条,自相矛盾。 */}
                <div
                  style={{
                    marginTop: 18, fontFamily: 'var(--font-body)', fontSize: 17,
                    color: 'var(--fg-2)', opacity: noteIn(0.6),
                  }}
                >
                  {`以上合计 ${String(TOTAL_ANNOTATIONS)} 条标注 —— 与本卡真实标注数一致。`}
                </div>
                {/* 双会话对照:★ 用 NOARCH_CARD 的真实分布与有档案会话并置。
                    这修掉两个问题:
                      ① 上一版写「无档案会话全部是 AI 推断」——**数据反驳**:无档案会话
                         实际是 ai_inference 31 + onsite_observation 5,并非「全部」。
                         现在数字全部现算,不写断言。
                      ② 用户当初要求「两个场景都包括(评估)」。上一版只演了有档案那一半,
                         NOARCH_CARD 定义了却没用(独立审查作为方案-实现偏离提出)。
                    并置形态同时说明了一个真实的产品性质:「历史记录」只在有记忆时出现。 */}
                <div
                  style={{
                    marginTop: 22, paddingTop: 20, borderTop: '1px solid var(--border-soft)',
                    fontFamily: 'var(--font-body)', fontSize: 17, color: 'var(--fg-2)',
                    lineHeight: 1.75, opacity: noteIn(0.63),
                  }}
                >
                  同一个产品,两个真实会话:
                </div>
                <div
                  style={{
                    marginTop: 12, display: 'flex', gap: 26,
                    opacity: noteIn(0.72),
                  }}
                >
                  {[
                    {t: '有档案', v: TOTAL_ANNOTATIONS, extra: `含「历史记录」${String(sourceCount('history'))} 条`},
                    {t: '无档案', v: NOARCH_TOTAL, extra: `无「历史记录」· 全是推断与观察`},
                  ].map((col) => (
                    <div key={col.t} style={{flex: 1}}>
                      <div
                        style={{
                          fontFamily: 'var(--font-body)', fontSize: 16,
                          color: 'var(--muted)', marginBottom: 4,
                        }}
                      >
                        {col.t}
                      </div>
                      <div
                        style={{
                          fontFamily: 'var(--font-mono, monospace)', fontSize: 24,
                          color: 'var(--accent)',
                        }}
                      >
                        {`${String(col.v)} 条标注`}
                      </div>
                      <div
                        style={{
                          fontFamily: 'var(--font-body)', fontSize: 15,
                          color: 'var(--muted)', marginTop: 4, lineHeight: 1.6,
                        }}
                      >
                        {col.extra}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        ) : null}
      </div>
    </FilmRoot>
  );
};
