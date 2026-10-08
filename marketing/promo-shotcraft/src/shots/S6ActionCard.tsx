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
import {ActionCard} from '../../../../apps/web/src/features/consult/view/MessageParts/ActionCard';
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

/**
 * 三档语义(产品契约 RQ-EMG-04:稳定 / 未排除 / 高风险)。
 * ★ v22:独立的「三档语义特写文案页」已由立传弧取代 —— 三档信息由卡片
 *   自身的「未排除」徽章承载(轮廓光束检视的正是它),不再另列一张文案页。
 */

export const S6ActionCard: React.FC = () => {
  const frame = useCurrentFrame();
  const timing = useShotTiming();

  /**
   * 段划分(比例,2026-10-08 v22 立传版)。
   *
   *   seg 0  0→HERO_END   **行动卡立传**(spotlight-hero-card 语法,见下)
   *   seg 1  HERO_END→0.52  设备内滚动到「01 当前状态」,刹车
   *   seg 2  0.52→1         滚到「02 立即怎么沟通」+ 右侧真实来源分布
   *
   * ★★ v22 为什么换掉「三档语义特写文案页」:
   *   原 seg0 是一段**没有设备的纯文案页**(标题 + 副标 + 三档徽章逐个点亮)。
   *   它的内容没有错,但它让全片 S3→S4→S5→S6→S7→S8 连续六段共享同一种
   *   「左侧小手机 + 右侧大字、正面平视」构图 —— 观众对 S6 的第一印象与
   *   前五段无法区分。而行动卡恰恰是产品最有说服力的资产。
   *   立传弧用**同一张真实 <ActionCard> 组件**当主角:推近 → 弹起悬浮 →
   *   轮廓光束检视 → 落进设备框(Q9:飞入的终点是它在页面里的真实槽位,
   *   不悬浮)。三档信息没有丢 —— 「未排除」徽章就在卡里,光束扫的正是它。
   */
  const HERO_END = Math.max(timing.at(0.18), 108);
  const SEG1_END = timing.at(0.52);
  const seg = frame < HERO_END ? 0 : frame < SEG1_END ? 1 : 2;
  /** 立传段实际的段内比例 —— 供 noteIn 时刻表使用。 */
  const seg0R = HERO_END / timing.duration;

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

  // ════════════════════════════════════════════════════════════════════
  // 立传弧(spotlight-hero-card,references/shots/opening/spotlight-hero-card.md)
  // 参数全部取自该卡的调校表,不凭感觉新写:
  //   相机  正视 → rotY 30°/rotX 6°(卡 34°/8°;本卡文字密,留可读性余量),persp 1200
  //   rise  10f,bezier(0.2,1.25,0.3,1) 过冲(卡原值)
  //   悬停  sin bob 振幅 4px 周期 40f,lift 0→1(卡:z=110px·lift)
  //   光束  lap1 strokeWidth 5+2.5 双层 → lap2 3.5+1.75、opacity 0.62,
  //         strokeDasharray "0.14 1" 走 dashoffset(卡原值;色 = 本片 accent)
  //   落地  reseat 18f,press 0.997(卡原值);终点 = 设备框内的卡片槽位
  //   阴影  0 8·lift / 0 46·lift 90·lift(卡原公式,随高度生长)
  // 与卡的唯一偏离:落点不是「贴回原位」而是「落进设备框」——
  //   本段后面还有 16s 设备内滚动演示,卡片必须回到它的叙事现场。
  // ════════════════════════════════════════════════════════════════════
  const RISE_END = 10;
  const BOB_END = 64;
  const LAP1_END = 80;
  const LAP2_END = 100;
  const RESEAT_END = HERO_END;

  /** 卡片自身的推近(CSS zoom = 布局级放大,按放大后尺寸栅格化,Q2 不走 transform scale)。
   *  ★ 峰值 1.15:裁切窗口 560px × 1.15 ≈ 644px,加 bezel 与阴影仍远小于 1080,
   *    主角完整入画;0.72 那版太小,立传的「推近感」被吃掉(f1920 实测卡片缩成小竖条)。 */
  const heroZoom = interpolate(
    frame,
    [0, RISE_END, BOB_END, RESEAT_END],
    [0.72, 1.12, 1.15, 1.15],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.3, 0, 0.25, 1)},
  );
  /** 侧向机位:推近期摇到 30°/6°,落地前回正 —— 回正后正好交接给设备内的正视镜头。 */
  const heroRotY = interpolate(
    frame,
    [0, RISE_END, LAP2_END, RESEAT_END],
    [2, 30, 30, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.35, 0, 0.3, 1)},
  );
  const heroRotX = interpolate(
    frame,
    [0, RISE_END, LAP2_END, RESEAT_END],
    [0, 6, 6, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.35, 0, 0.3, 1)},
  );
  /** rise → reseat 的垂直主轨迹(px,负=向上)。 */
  const riseY = interpolate(frame, [0, RISE_END], [0, -96], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.2, 1.25, 0.3, 1),
  });
  const reseatY = interpolate(frame, [LAP2_END, RESEAT_END], [0, 96], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.4, 0, 0.25, 1),
  });
  /** 悬停 bob(振幅 4px 周期 40f,卡原值;reseat 起淡出,避免与落地轨迹打架)。 */
  const bobFade = interpolate(frame, [LAP2_END - 8, LAP2_END + 4], [1, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  const bobY = frame >= RISE_END ? Math.sin(((frame - RISE_END) / 40) * Math.PI * 2) * 4 * bobFade : 0;
  const liftY = riseY + reseatY + bobY;
  /** 离地量(0→1),驱动阴影生长。 */
  const lift = interpolate(frame, [0, RISE_END, LAP2_END, RESEAT_END], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  /** 落地微压(press 0.997,卡原值):reseat 最后 6f 轻压再弹回。 */
  const press = interpolate(
    frame,
    [RESEAT_END - 6, RESEAT_END - 2, RESEAT_END],
    [1, 0.997, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
  );
  /** 落地后整卡交棒给设备内镜头。
   *  ★ 不做「原地淡出 + 设备淡入」—— 那会在 12f 交叉里留下
   *    「卡片没落地、设备也没来」的半透明叠影(f1965 实测)。
   *    让 hero 卡**向设备位置物理移动并缩小**(Q9:飞入的终点是页面真实槽位),
   *    整机在同一窗口从同一位置长出接住它 —— 两条轨迹交汇于设备框。 */
  const heroOut = interpolate(frame, [HERO_END - 12, HERO_END], [1, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  /** reseat 后段:hero 卡向设备框中心(cx=640,cy=540)移动的轨迹与缩放。 */
  const flyX = interpolate(frame, [LAP2_END, HERO_END], [0, 640 - 380 - 179], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.4, 0, 0.3, 1),
  });
  const flyY = interpolate(frame, [LAP2_END, HERO_END], [0, 540 - (540 - 470) - 395], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.4, 0, 0.3, 1),
  });
  const flyZoom = interpolate(frame, [LAP2_END, HERO_END], [1, 0.62], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.4, 0, 0.3, 1),
  });
  /** 轮廓光束两圈:dashoffset 走一圈 = 周长(lap1 快而亮,lap2 慢而弱)。 */
  const BEAM_PERIMETER = 2 * (358 + 640);
  const beamLap1 = interpolate(frame, [RISE_END + 4, LAP1_END], [BEAM_PERIMETER, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.3, 0, 0.3, 1),
  });
  const beamLap2 = interpolate(frame, [BOB_END + 10, LAP2_END], [BEAM_PERIMETER, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.45, 0, 0.55, 1),
  });
  /** 悬停期 3D 注记(C3:与主角同一透视空间;卡的 hover-3d-annotation 手法)。 */
  const noteIn3d = interpolate(frame, [RISE_END + 8, RISE_END + 22], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.2, 0.7, 0.25, 1),
  });
  const noteOut3d = interpolate(frame, [LAP2_END - 6, LAP2_END + 6], [1, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  // 相机:★ 分段推近(lib/camera.ts)。首阶从 HERO_END 起(立传段不接整机)。
  //   ★ 2026-10-07:周期漂移分量已删除(用户裁决);分段推近保留(每阶对应叙事上的
  //     下一件事:卡片 → 01 节 → 来源标注)。
  //   ★ 2026-10-08:删除与之并存的**全程线性推近** —— `Math.max` 里线性那条一路抬升,
  //     分段的停顿被覆盖,手机框全程一直在变大。
  const scale = stagedPush(
    frame,
    [1.0, 1.06, 1.13, 1.2],
    [HERO_END, HERO_END + 6, SEG1_END, timing.at(0.8)],
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
  // ★★ 2026-10-08:关键帧表的后续时刻**从 HERO_END 派生**,不再直接用 timing.at(0.1)…
  //   原因:立传段有绝对下限(HERO_END ≥ 108),它可能**大于**某些比例点 ——
  //   而 interpolate 要求 inputRange 严格单调递增,越界不是「画面难看」,
  //   是**渲不出来**。⇒ 换场后的每个时刻都改为「立传结束 + 剩余区间的一个比例」。
  const afterHero = (frac: number) => HERO_END + Math.round(frac * (timing.duration - HERO_END));
  const BRAKE1 = 3200;
  const BRAKE2 = 6400;
  const scrollY = interpolate(
    frame,
    [
      0,
      HERO_END,
      afterHero(0.02),
      afterHero(0.12),
      afterHero(0.26),
      afterHero(0.38),
      afterHero(0.52),
      afterHero(0.86),
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

  /** 立传层的**退场**淡出(结束前 SCENE_FADE 帧内,与设备入场交汇)。 */
  const stageIn = interpolate(
    frame,
    [HERO_END - SCENE_FADE, HERO_END],
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
        {/* ① 行动卡立传(spotlight-hero-card):同一张真实 <ActionCard>,
             推近 → 弹起悬浮 → 轮廓光束检视 → 落进设备框。 */}
        {seg === 0 ? (
          <div
            style={{
              position: 'absolute', inset: 0,
              opacity: heroOut,
              perspective: 1200,
              perspectiveOrigin: '960px 540px',
            }}
          >
            {/* 卡片主角:CSS zoom 做布局级放大(Q2 栅格化按放大后尺寸),
                transform 只做机位旋转与垂直轨迹。构图:卡片偏左(x≈380),
                注记在右侧 —— 左右配重,不让左侧空场。 */}
            <div
              style={{
                position: 'absolute', left: 380, top: 540 - 470,
                transform: `translate(${flyX.toFixed(1)}px, ${(liftY + flyY).toFixed(2)}px) rotateY(${heroRotY.toFixed(2)}deg) rotateX(${heroRotX.toFixed(2)}deg) scale(${(press * flyZoom).toFixed(4)})`,
                transformStyle: 'preserve-3d',
                transformOrigin: 'center center',
              }}
            >
              {/* ★ 立传的主角是卡片的**优先块 + 01 标题 + 医疗徽章行** ——
                  不是整张七节长卡(全卡高 3000+px,任何 zoom 都没法「完整入画」
                  又保持字可读),也不是 860px(那会把「01 当前状态」切在半截)。
                  裁到徽章行结束为止:信息自足(先看什么 + 三档取值),不半句。
                  裁切用 overflow:hidden + 固定高,底下的分区被藏而不是删 ——
                  同一个 <ActionCard> 组件,没有第二份 DOM。 */}
              <div
                style={{
                  position: 'relative',
                  width: 358,
                  height: 790,
                  overflow: 'hidden',
                  zoom: heroZoom,
                  boxShadow: `0 ${String(8 * lift)}px ${String(18 * lift + 6)}px rgba(32,25,20,${(0.10 + lift * 0.10).toFixed(3)}), 0 ${String(46 * lift)}px ${String(90 * lift + 20)}px rgba(32,25,20,${(0.06 + lift * 0.10).toFixed(3)})`,
                  borderRadius: 24,
                }}
              >
                <ActionCard data={CARD} expired={false} />

                {/* 轮廓光束两圈(只给主角一次,Q4;色 = 本片 accent 火焰橙)。
                    SVG 坐标用未缩放逻辑尺寸(358×560),缩放交给外层 CSS zoom,
                    于是 dashoffset 周长与视觉周长一致。 */}
                {frame >= RISE_END + 4 && frame < LAP2_END + 4 ? (
                  <svg
                    width={358 + 40}
                    height={790 + 40}
                    viewBox={`0 0 ${String(358 + 40)} ${String(790 + 40)}`}
                    style={{position: 'absolute', left: -20, top: -20, pointerEvents: 'none'}}
                  >
                    <rect
                      x={20} y={20}
                      width={358} height={790}
                      rx={24}
                      fill="none"
                      stroke="var(--accent)"
                      strokeWidth={5}
                      strokeDasharray={`${String(0.14 * 2 * (358 + 790))} ${String(2 * (358 + 790))}`}
                      strokeDashoffset={(beamLap1 / BEAM_PERIMETER) * 2 * (358 + 790)}
                      opacity={frame <= LAP1_END ? 0.9 : 0}
                      strokeLinecap="round"
                    />
                    <rect
                      x={20} y={20}
                      width={358} height={790}
                      rx={24}
                      fill="none"
                      stroke="var(--accent)"
                      strokeWidth={4.5}
                      strokeDasharray={`${String(0.14 * 2 * (358 + 790))} ${String(2 * (358 + 790))}`}
                      strokeDashoffset={(beamLap2 / BEAM_PERIMETER) * 2 * (358 + 790)}
                      opacity={frame > BOB_END + 10 ? 0.78 : 0}
                      strokeLinecap="round"
                    />
                  </svg>
                ) : null}
              </div>
            </div>

            {/* 悬停期 3D 注记(C3:与主角同一透视 —— 它在旋转层**之外**,
                但跟随同一个 perspectiveOrigin,读起来像浮在卡片左侧的空间里)。 */}
            {frame >= RISE_END + 8 ? (
              <div
                style={{
                  position: 'absolute', left: 1080, top: 420, width: 460,
                  opacity: Math.min(noteIn3d, noteOut3d),
                  transform: `translateZ(0) translateY(${((1 - noteIn3d) * 18).toFixed(1)}px)`,
                }}
              >
                <div
                  style={{
                    fontFamily: 'var(--font-display)', fontSize: 44, fontWeight: 500,
                    color: 'var(--fg)', lineHeight: 1.42,
                  }}
                >
                  行动卡,
                  <br />
                  它先看医疗危险。
                </div>
                <div
                  style={{
                    fontFamily: 'var(--font-body)', fontSize: 21, color: 'var(--muted)',
                    marginTop: 20, lineHeight: 1.75,
                  }}
                >
                  存在急性医疗危险表现时,不优先解释为孤独症相关行为。
                  不做诊断、不给用药建议。
                </div>
              </div>
            ) : null}
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
