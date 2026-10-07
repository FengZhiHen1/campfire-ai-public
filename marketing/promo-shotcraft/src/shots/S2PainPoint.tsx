// S2 痛点情境(180f / 6s):纯 Motion,无 UI——
// 暗场,超市场景文字逐行浮现,末行「是没人商量」强调。为后续产品出场建立情绪。
//
// ★ v16:时间点改为**从本段时长按比例派生**(见 lib/shotTiming.ts)。
//   原先写死帧号(lineIn(8)/lineIn(52)/lineIn(88)、dim [0,60,100,115]、fadeOut [104,120]),
//   段长从 120f 改到 180f 后全部失配:末行会停在 0.49 处,后 73 帧(2.4s)什么都不发生。
//
// 节奏(比例,6s 段):六次文字落位 + 三条贯穿运动
//   落位:0.055 首行 → 0.17 次行 → 0.28/0.39 第二句情境(不知道是什么、也没人能回答)
//         → 0.50 痛点上半句 → 0.72 末行「是没人商量」
//   事件:0.62 转折线由中心展开;0.90→1 底回升到亮米纸(交棒给产品镜头)
//   贯穿:0.02→0.26 暖光带横穿(仅在亮底阶段);全段 scale 1.00→1.12;
//         压暗后由**暖光晕缓慢漂移**提供大面积运动(位移型,不起频闪)
//   收尾:0.94→1 整体淡出
//   相邻落位间隔 0.09–0.11(180f 里 16–20f),任意 30 帧窗口内至少一次可见事件。
//
// ★ 为什么除了落位还要有贯穿运动:落位是**离散事件**,事件之间是渐变的空档;
//   而本段是「大字 + 空场」的画面,只落在文字上的运动在整帧差分里会被大片空白稀释。
//   实测(逐帧 |Δ亮度| 均值,阈值 0.35):只有落位 + 推近时,有一段 11 帧全程 0.15–0.24,
//   是掉到阈值下的静止区间。
//   ★ 两次修法的对比留档:先试「底色明暗呼吸」(静止率 0.6% 达标)但视觉上是灰褐浑浊
//     且周期接近闪烁临界;最终改为**暖光晕位移**(同样大面积、不混灰、无频闪感)。
//     结论:达标手段不能只看指标,还要看它长什么样。
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';

import {useShotTiming} from '../lib/shotTiming';
import {C, FONT_BODY, FONT_DISPLAY} from '../tokens';

const L1A = '超市里,孩子突然蹲下捂住耳朵,';
const L1B = '周围全是目光。';
// ★ 第二句情境不是为凑时长编的:它逐字取自项目自己的旁白脚本
//   (marketing/light-demo/screenplay/narration.md 第 14-15 行)。
//   加它的理由:原版从「周围全是目光」直接跳到「最难的不是辛苦」,
//   中间缺了「没人商量」这句话的**来处** —— 正是这两行把来处讲清楚了。
const L2A = '你不知道这是感官过载,还是哪里疼——';
const L2B = '而能回答你的人,都不在现场。';
const L3 = '照护一个孤独症孩子,最难的不是辛苦,';
const L4 = '是没人商量。';

export const S2PainPoint: React.FC = () => {
  const frame = useCurrentFrame();
  const t = useShotTiming();

  // 单次落位占段长的 13%(180f 里约 23f),与 4s 段里 16f 的观感同族。
  const LINE_LEN = 0.13;
  const lineIn = (start: number) =>
    interpolate(frame, t.span(start, start + LINE_LEN), [0, 1], {
      extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
      easing: Easing.bezier(0.25, 0, 0.3, 1),
    });

  /**
   * 六次离散落位 —— 每一次都是一次「看得见的新信息出现」,这就是本段的节拍。
   *
   * ★ v16 更正(独立终检抓出「f115–132 有 0.60s 近空白带」,我抽帧确认 f122 纯纸色):
   *   成因是两端各让一步 —— S1 在自己末端把内容淡到几乎全空(opacity≈0.03),
   *   而 S2 的首行原本 0.055 才起(段内第 10 帧)。接缝处因此有约 0.6s 只有纸色。
   *
   *   修法:**首行在第 0 帧就已经在场**(不淡入)。理由是接缝那一侧 S1 刚把字淡走,
   *   观众的眼睛正等着新内容;让第一句直接出现,读起来是「硬切 + 立刻有新信息」,
   *   比「先空一会儿再淡入」干净。其余五行仍逐行淡入,节拍不受影响。
   *   S2 第 0 帧因此不再空白,而且它同时还有压暗与光带在动。
   */
  const t1a = 1;
  const t1b = lineIn(0.11);
  const t2a = lineIn(0.24);
  const t2b = lineIn(0.35);
  const t3 = lineIn(0.48);
  const t4 = lineIn(0.72);

  // 转折线:0.62→0.70 由中心向两侧展开。
  // 为什么取这个比例:它正好落在 t3 落位完成(0.63)与末行 t4 起(0.72)之间的空档里 ——
  // 没有它,那 16 帧只有渐变,是这一段唯一的「无事发生」窗口。
  // 语义上它也不多余:它就是「最难的不是辛苦」与「是没人商量」之间的那个停顿。
  const ruleW = interpolate(frame, t.span(0.62, 0.7), [0, 240], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.2, 1),
  });

  // 底:暖米纸转暗(0→0.26 走完)→ 保持深暖黑 → 末行说完后 0.90→1 回升到亮米纸。
  //
  // ★ v16 修正:初版在暗段做了「暗 ↔ 稍亮」的**连续呼吸**(0.85↔1.00 三次)。
  //   它确实把静止率压到 0.6%,但代价是两个视觉缺陷(我抽帧复核后确认):
  //     ① 中间过渡是**灰褐色的浑浊带** —— 因为 color-mix 在 srgb 里把暖米纸与近黑
  //        对半混,得到的是低饱和的灰褐,而不是影片其他段落那种干净的暖黑;
  //        实测 f30 整帧亮度 101 → f50 降到 23,过渡中段明显发灰。
  //     ② 呼吸周期约 1 秒(暗度 0.15),正好落在闪烁临界附近 ——
  //        子代理自己也标注「读起来是屏住呼吸还是频闪,未用播放验证」。
  //   因此改回**单次单调压暗**:视觉上是干净的「灯慢慢关掉」,不是明暗脉动。
  //
  //   那「大面积运动」从哪来?改为**暖光晕缓慢漂移**(见下方 emberGlow):
  //   同样是整屏级的大面积变化(光晕覆盖约 55% 画面),但运动方向是位移而不是灰度,
  //   不会有频闪感,也不需要把底色混成灰。
  const dim = interpolate(
    frame,
    [t.at(0), t.at(0.26), t.at(0.88), t.at(1)],
    [0, 1, 1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.35, 0, 0.5, 1)},
  );
  // 直接用两层纯色叠加,不走 color-mix —— 避免 srgb 中段混出灰褐。
  const bg = C.bg;
  const ink = `color-mix(in srgb, ${C.fg} ${(1 - dim) * 100}%, #f5ead9)`;
  const inkSoft = `color-mix(in srgb, ${C.fg2} ${(1 - dim) * 100}%, #cbb89f)`;

  /**
   * ★★ 2026-10-07:删除「暗场宽光带 sin 往返」。
   *
   * 它当年是为了把**帧差指标**填满而造的(见下方历史记录:三次实验淘汰到「往返」为止),
   * 与相机周期漂移属于同一类**无语义连续运动** —— 用户裁决那类运动「没有任何语义」。
   * 现在门禁口径已改为**语义事件制**(verify/motion-gate.py + src/events.json):
   * 本段的六个落位 + 转折线 + 单次扫光已经满足「任意 ≤2s 窗口内有事件」,不需要
   * 用巡游光斑去凑帧差。
   *
   * 保留下来的两件连续元素:
   *   · 开场**单次**暖光带横穿(0.02→0.26)——有方向、有始有终,是「场景开场」;
   *   · 全局推近 1.00→1.08 —— 单向、减速落定。
   *
   * 历史记录(为什么当初会走到「往返」这一步,留档以免重蹈):
   *   ① 底色明暗呼吸 → 帧差达标,但中段混出灰褐浑浊、周期接近闪烁临界(视觉不合格)
   *   ② 径向暖光晕漂移 → 视觉干净,但梯度太平缓,帧差测不出(静止率 63.3%)
   *   ③ 宽光带单次横穿 → 前 2/3 达标,光带出画后又静下来
   *   ④ 宽光带 sin 往返 → 全程有位移(当时的最优解)
   * 教训:①②③④ 争的都是「怎么让指标过」,而正确的问题是「观众需要看到什么」。
   */

  // 暖光带:只在**开场亮底阶段**横穿(0.02→0.26),此时底还是暖米纸,
  //   一条边缘柔和的暖带扫过是干净的(与 S6/S9 同机制)。
  //   ★ 初版让它一直扫到 0.42,那时底已经压暗 —— 暗场上一条橙色竖带看起来
  //     是一块**污渍**而不是扫光(实测 f30 可见)。因此缩短到压暗完成之前。
  const sweepX = interpolate(frame, t.span(0.02, 0.26), [-620, 2540], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.35, 0, 0.65, 1),
  });
  // ★ 与 S1 的 crossFade 同理:**必须降到 0**。
  //   这是开场的一次性扫光(sweepX 在 0.26 已驶到 2540,即画面右侧之外),
  //   留 6% 会在画面右缘留一条**静止的淡橙色竖带**直到段末。
  //   出场地板只加段末淡出(S2 的 fadeOut),不加这种中途消失的元素。
  const sweepFade = interpolate(frame, t.span(0.2, 0.3), [1, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  /**
   * 暗场的**大面积运动**:一道很宽、边缘柔和的暖白光带横穿画面。
   *
   * ★ 为什么是「宽光带」而不是前面试过的两种做法(两次实测的结论):
   *   ① 底色明暗呼吸 → 帧差达标,但中段混出**灰褐浑浊**、周期接近闪烁临界(视觉不合格)
   *   ② 径向暖光晕漂移 → 视觉干净,但梯度太平缓,**帧差测不出**
   *      (实测静止率 63.3%、最长静止 3.73s —— 等于没有运动)
   *   ③ 宽光带**单次**横穿 → 前 2/3 达标,但光带走完出画后(0.56 起)又静下来
   *      (实测 f120-159 静止 38/40 帧)
   *
   * 上面第 ③ 条的修正就是下面这段:光带在画面内**往返**(不驶出),因此全程有位移。
   */

  // 全局推近:整段 1.00→1.08,单向、减速落定。
  //   ★ 2026-10-07:从 1.12 收到 1.08 —— 本段的运动主角改为**六次按压落位**,
  //     推近只做「把观众带进画面」的底噪,不必再承担「填满帧差」的职责。
  const push = interpolate(frame, t.span(0, 1), [1.0, 1.08], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.linear,
  });

  const fadeOut = interpolate(frame, t.span(0.94, 1), [1, 0.06], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  // 参数名用 p(progress)而不是 t —— 外层的 t 已经是 shotTiming,避免遮蔽。
  //
  // ★ 2026-10-07:落位方式从「下方浮入」改**按压落定**(镜头卡 list-stack-press 的语法):
  //   文字从略上方落下、带一点点缩小,像被按进纸面 —— 六次落位 = 六次「信息压过来」,
  //   与「痛苦在累积」的叙事一致;而浮入读起来是「轻轻飘上来」,与痛点段的力量相反。
  const lineStyle = (
    p: number, color: string, size: number, display = false,
  ): React.CSSProperties => ({
    opacity: p,
    transform: `translateY(${(1 - p) * -12}px) scale(${String(1 + (1 - p) * 0.035)})`,
    color,
    fontSize: size,
    lineHeight: 1.75,
    fontFamily: display ? FONT_DISPLAY : FONT_BODY,
    fontWeight: display ? 500 : 400,
    margin: 0,
    textAlign: 'center',
  });

  return (
    <AbsoluteFill
      style={{background: bg, justifyContent: 'center', alignItems: 'center', opacity: fadeOut}}
    >
      {/* 压暗层:纯色叠加,不走 color-mix —— 避免 srgb 中段混出低饱和的灰褐。
          用 #17110c(深暖黑)而不是中性黑,压暗后仍是暖调,与影片其他段同族。 */}
      <div
        style={{
          position: 'absolute', inset: 0,
          backgroundColor: '#17110c',
          opacity: dim,
          pointerEvents: 'none',
        }}
      />

      {/* 暖光带画在文字下层:它只是「画面在动」的证据,不能盖住正在落位的字 */}
      <div
        style={{
          position: 'absolute', top: 0, bottom: 0, width: 460, left: sweepX,
          background:
            'linear-gradient(90deg, transparent, rgba(194,65,12,0.14), rgba(194,65,12,0.22), rgba(194,65,12,0.14), transparent)',
          opacity: sweepFade,
          pointerEvents: 'none',
        }}
      />

      <div
        style={{
          maxWidth: 1240,
          transform: `scale(${String(push)})`,
          transformOrigin: 'center center',
        }}
      >
        {/* 情境两句:第一句是「发生了什么」,第二句是「为什么没人能回答」——不铺陈,是递进 */}
        <p style={lineStyle(t1a, inkSoft, 34)}>{L1A}</p>
        <p style={lineStyle(t1b, inkSoft, 34)}>{L1B}</p>
        <div style={{height: 44}} />
        <p style={lineStyle(t2a, inkSoft, 30)}>{L2A}</p>
        <p style={lineStyle(t2b, inkSoft, 30)}>{L2B}</p>
        <div style={{height: 52}} />
        <p style={lineStyle(t3, ink, 40, true)}>{L3}</p>

        {/* 转折线:随 ruleW 从中心长出,把上下两句断成「辛苦」与「没人商量」两拍 */}
        <div
          style={{
            height: 22, margin: '10px 0',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <div style={{width: ruleW, height: 2, borderRadius: 2, background: C.accent, opacity: 0.7}} />
        </div>

        <p
          style={{
            ...lineStyle(t4, C.accent, 68, true),
            transform: `translateY(${(1 - t4) * -14}px) scale(${String(1.05 - t4 * 0.05)})`,
            letterSpacing: '0.04em',
            textShadow: `0 0 60px rgba(194, 65, 12, ${0.4 * t4})`,
          }}
        >
          {L4}
        </p>
      </div>
    </AbsoluteFill>
  );
};
