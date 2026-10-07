// S4 应急入口与八项采集 —— 用**真实题目数据 + 真实表单结构**当主体。
//
// 与旧版(截图版)的差别:
//   旧版 = 8 张题面 PNG + 按猜的坐标叠 ✓ → ✓ 与复选框对不齐(用户实测指出);
//   新版 = 渲染真实的 <input type=checkbox> + <span class="check-box">,
//         勾选态由产品的 CSS `.selection:has(input:checked)` 驱动 —— ✓ 与框是同一元素,
//         对齐由浏览器布局保证,结构上不可能错位。
//
// 题目与选项取自产品真源 EMERGENCY_QUESTIONS。
// ★ 更正:该常量是 **8 项**(medical_red_flags / baseline_deviation / communication /
//   distress / sensory_environment / what_happened / primary_risk / possible_pain)。
//   这里曾写「九项医疗红灯,不是我上次写的八项」—— 那次「更正」把对的改成了错的
//   (数错了),独立终检指出。画面不受影响(进度用 total={q.length} 实时取),
//   但注释是给后来人看的,写错会误导。
//
// 节奏(960f / 32s,五段;时间点全部按**本段时长**比例派生,见 lib/shotTiming.ts):
//   ① 0.00-0.13  首页:应急入口高亮圈 + 推近
//   ② 0.13-0.36  第 1 题:真实勾选「明显疼痛」(与真实会话一致)
//   ③ 0.36-0.62  第 2-5 题快掠(真实会话里都是「已跳过」)
//   ④ 0.62-0.82  第 6 题:真实自由文本逐字落位
//   ⑤ 0.82-1.00  第 7-8 题快掠(真实会话里也是「已跳过」)+ 提交
import {Easing, interpolate, useCurrentFrame} from 'remotion';
import {MemoryRouter} from 'react-router';

import {HomePage} from '../../../../apps/web/src/app/pages/HomePage';
import {EMERGENCY_QUESTIONS} from '../../../../apps/web/src/features/consult/domain/emergency';
import {DeviceStage, FilmRoot} from '../lib/DeviceStage';
import {EmergencyFormView} from '../lib/EmergencyFormView';
import {useShotTiming} from '../lib/shotTiming';
import {NoteKicker, NoteTitle, NOTE_X} from '../lib/Shot';

/**
 * 真实作答 —— 取自会话 177f965b,与本片 S5/S6 的行动卡、流式文本**同一会话**。
 *
 * ★ 这里修掉一个真实的数据出处不一致(v15 审查发现,我用 `.tmp/extract-answers.py`
 *   直读数据库确认):
 *     初版 Q8(possible_pain)显示勾了「是」,但「是」属于**另一个会话** b897534e;
 *     而本片 S5/S6 的输出属于 177f965b。同一段采集演示与它导出的结果来自不同会话,
 *     违反本片「逐字来自真实记录」的原则。
 *
 *   177f965b 的真实作答(数据库逐字):
 *     medical_red_flags   = obvious_pain          ← 唯一被勾选的一项
 *     what_happened       = 在超市突然蹲下捂住耳朵  ← 唯一的自由文本
 *     其余六项            = 已跳过(未排除)
 *
 *   改用同一会话还有一个额外好处:它把影片右侧自己的那句话
 *   「跳过 = 未排除,不会当作正常」**演出来了** —— 八项里六项是跳过,
 *   而行动卡仍按「未排除」处理。这比原版更有说服力。
 */
const RED_FLAGS = ['obvious_pain'] as const;
/**
 * 真实自由文本(what_happened)。
 *
 * ★ 逐字取自会话 177f965b 的 `agent_messages.id=21474`:
 *     `在超市突然蹲下捂住耳朵,周围人多`(16 字,逗号是半角 U+002C)
 *   v16 初版漏了 `,周围人多` 五个字 —— 而丢掉的恰是**最关键的一半**:
 *   S5 里 AI 说「不能只按『环境太吵』解释」、S6 里 `sensory_environment`
 *   的来源标注,依据都是「周围人多」这句现场描述。少了它,那两处的论证就悬空了。
 *   独立终检直连数据库逐字比对时抓出。
 */
const WHAT_HAPPENED = '在超市突然蹲下捂住耳朵,周围人多';

/**
 * 四段的划分**按本段时长的比例**给出(v16)。
 *
 * ★ 为什么改成比例:原先写死绝对帧号(P1_END=112 等),段长 780f→960f 后
 *   这些帧号全部失配 —— 段尾会多出约 180 帧(6s)无事发生。改比例后段长自动跟随。
 *
 * 比例依据:四段的叙事权重是「入口 → 第1题(重点) → 快掠 → 自由文本+提交」。
 *   第 1 题要给足(它是唯一被勾选的一项,要看清 ✓ 落在真实复选框上),
 *   快掠四题要快要匀,末段要留时间给文字逐字落位。
 */
const P1_END_R = 0.13; // 首页(入口高亮)
const P2_END_R = 0.36; // 第 1 题(勾选「明显疼痛」)
const P3_END_R = 0.62; // 快掠(第 2-5 题,真实会话里都是「已跳过」)

/**
 * 「滚到底」用的值。
 *
 * 刻意给一个**足够大**的数,让 DeviceStage 按真实 scrollHeight 夹紧到实际底部。
 * 为什么不填实测值:影片渲染的是复刻视图 EmergencyFormView,其高度与真实产品页不同
 * (实测该视图 maxScroll=300,产品页是 344)。写实测值会「差一点没滚到底」——
 * 实测确实如此,选项卡仍被屏幕下缘切断。
 */
const EMERGENCY_SCROLL = 9999;
/**
 * 快掠段:第 2-5 题(index 1..4)—— 它们在真实会话里都是「已跳过」。
 * ★ 刻意**不含** index 5(what_happened):那一题有真实自由文本,单独给它一段展示,
 *   避免和「跳过」混在一起演。
 */
const QUICK = [1, 2, 3, 4];
/** what_happened 的题号(0-based)。 */
const WHAT_HAPPENED_INDEX = 5;
/**
 * 末段的尾部还要再过一遍第 7、8 题(index 6/7)。
 *
 * ★ 为什么必须补上(目标规格的「8 道题逐屏」):
 *   原版覆盖的是 Q1..Q6,index 6/7(primary_risk / possible_pain)**从未出现** ——
 *   八道题只演了六道。目标规格明确要求八道逐屏,这是一处实质缺口。
 *
 *   补的方式与真实数据一致:这两题在会话 177f965b 里**都是「已跳过」**
 *   (数据库实测),因此演「跳过」而不是编一个作答 —— 这恰好是右侧
 *   「跳过 = 未排除,不会当作正常」的实证。
 */
const TAIL_QUESTIONS = [6, 7];

export const S4Intake: React.FC = () => {
  const frame = useCurrentFrame();
  const t = useShotTiming();

  const P1_END = t.at(P1_END_R);
  const P2_END = t.at(P2_END_R);
  const P3_END = t.at(P3_END_R);
  /** 快掠段每题占多少帧 */
  const QUICK_PER = Math.max(1, Math.round((P3_END - P2_END) / QUICK.length));

  /**
   * 五段(不是四段):末段再拆出 Q7/Q8 的收尾快掠。
   *
   * ★ 为什么要拆(目标规格的「8 道题逐屏」):
   *   四段版覆盖 Q1..Q6,index 6/7(primary_risk / possible_pain)从未出现 ——
   *   八道题只演了六道。这里把末段 0.62→1 再分成:
   *     ④ 0.62→0.82  Q6 what_happened(真实自由文本,逐字落位)
   *     ⑤ 0.82→1.00  Q7/Q8 快掠(真实会话里两题都是「已跳过」)
   */
  const TAIL_END_R = 0.82;
  const TAIL_END = t.at(TAIL_END_R);
  const tailIdx = Math.max(
    0,
    Math.min(TAIL_QUESTIONS.length - 1, Math.floor((frame - TAIL_END) / Math.max(1, (t.duration - TAIL_END) / TAIL_QUESTIONS.length))),
  );

  /**
   * ★ v16 三次修正:逐字落位必须**在 seg3 结束前**打完,否则最后一个字落在 seg4 里。
   *
   * 独立终检抓出:TAIL_END_R=0.82 ⇒ 局部帧 787,而 `seg === 3` 的条件是 `frame < 787`,
   * 即 seg3 最大帧 786。`typedChars = ⌊((f−595)/192)×16⌋` 在 f786 得 15、**f787 才得 16** ——
   * 于是演 Q6 的那一段时间里,textarea 最多显示 15 字,第 16 个字(「多」)只在 seg4
   * (已经切到 Q7 的画面)才补上。抽帧实测确认:f1326 的 textarea 是「…周围人」,
   * 而右侧说明区写着完整的 16 字 —— 左右不一致。
   *
   * 修法:打字窗口提前 4% 结束(TAIL_DONE_R),让 16 字在 seg3 内就位。
   * 用比例而不是减固定帧数 —— 段长再变时窗口自动跟随。
   */
  const TAIL_DONE_R = TAIL_END_R - 0.04;
  const TAIL_DONE = t.at(TAIL_DONE_R);
  const typedChars = Math.max(
    0,
    Math.floor(
      ((frame - t.at(P3_END_R)) / Math.max(1, TAIL_DONE - t.at(P3_END_R))) *
        WHAT_HAPPENED.length,
    ),
  );

  const seg: 0 | 1 | 2 | 3 | 4 =
    frame < P1_END ? 0
      : frame < P2_END ? 1
        : frame < P3_END ? 2
          : frame < TAIL_END ? 3
            : 4;

  // 相机:★ 分段幅度(lib/camera.ts)。
  //   ★ 2026-10-07:周期漂移分量已删除(用户裁决);分段推近是语义运动(逐段进入
  //     下一组题),保留。
  //   ★ 2026-10-08:删除与之并存的**全程线性推近** `pushCamera(frame, 1.0, 1.2, t.duration)`。
  //     原来 `scale = Math.max(camScale, segPush)`:线性那条一路抬升,把分段的停顿覆盖掉,
  //     结果是**手机框 18s 里全程一直在变大**(用户:「我为什么还能看到手机框在动?」)。
  //     现在只留分段:每段进入时推一下,段内读题时画面完全静止。
  const segPush = interpolate(
    frame,
    [0, P1_END, P2_END, P3_END, TAIL_END, t.duration],
    [1.0, 1.06, 1.12, 1.16, 1.18, 1.2],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.3, 0, 0.25, 1)},
  );
  const scale = segPush;

  // 屏内滚动:★ 必须传!初版四处 DeviceStage 都没传 scrollY,而该页需要滚动,
  // 结果第 1 题的「明显疼痛」选项卡被屏幕下缘拦腰截断、三个按钮全在屏外
  // (独立审查实测抓出)。这是截图路线缺陷②换了个形状重现 ——
  // 「不滚」和「滚过头」都会露出不该露的东西。
  //
  // ★ 用**足够大的值**而不是 page-metrics.json 的 emergencyQ1.maxScroll(=344):
  //   那个值是量**真实产品页**得到的,而影片渲染的是复刻视图 EmergencyFormView,
  //   元素高度与产品不完全相同。实测拿 344 去滚影片的视图确实「差一点没滚到底」,
  //   选项卡仍被切断。给大值后 DeviceStage 会读当前 DOM 的真实 scrollHeight 夹紧,
  //   不需要事先知道正确数字 —— 抗漂移。
  //
  // 各段目标:
  //   ① 首页     不滚(首页无溢出)
  //   ② 第 1 题  先停在题目顶部让观众读题,勾选后滚到底 → 被勾的项与按钮同屏
  //   ③ 快掠     滚到底(每题高度不同,底部最稳)
  //   ④ 自由文本 滚到底 → 保证输入区与「提交」按钮可见
  const scrollY = (() => {
    if (seg === 0) return 0;
    // 第 1 题先停在顶部(约本段前半),之后滚到底
    if (seg === 1) return frame < P1_END + (P2_END - P1_END) * 0.45 ? 0 : EMERGENCY_SCROLL;
    return EMERGENCY_SCROLL;
  })();

  const fadeOut = interpolate(frame, t.span(0.965, 1), [1, 0.06], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  // ── ① 首页:应急入口高亮圈(画在真实按钮位置,用**一次**回弹吸引注意) ──
  //   ★ 2026-10-07:替换原先的 sin 持续脉冲(16f 周期)。圈是「锁定」的语义:
  //     张开一次 + 收回 + 保持静止,不是一直在呼吸。
  const ringIn = interpolate(frame, t.span(0.035, 0.075), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.2, 0.75, 0.3, 1),
  });
  const ringPop = 1 - interpolate(frame, t.span(0.075, 0.115), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  // ── ② 第 1 题:勾选「明显疼痛」(多选题第 8 项) ──
  const flagOn = interpolate(
    frame,
    t.span(P1_END_R + (P2_END_R - P1_END_R) * 0.3, P1_END_R + (P2_END_R - P1_END_R) * 0.5),
    [0, 1],
    {
      extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
      easing: Easing.bezier(0.2, 0.75, 0.3, 1),
    },
  );

  /**
   * 勾选落定之后的两件事(镜头卡 chip-grid-single-select-blackout 的语法):
   *   ① 其余 7 项**压暗到稳态** —— 视线落在被选中的那一条上;
   *   ② 选中项一次**回弹**然后静止。
   * 起点与 `flagOn` 的完成时刻对齐,终点按同段比例派生 —— 段长变化自动跟随。
   */
  const checkSettled = interpolate(
    frame,
    t.span(P1_END_R + (P2_END_R - P1_END_R) * 0.52, P1_END_R + (P2_END_R - P1_END_R) * 0.64),
    [0, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
  );
  const unselectedDim = checkSettled;
  const checkedPop = 1 - checkSettled;

  // ── ③ 快掠 ──
  const quickIdx = Math.max(0, Math.min(QUICK.length - 1, Math.floor((frame - P2_END) / QUICK_PER)));
  const quickLocal = (frame - P2_END) % QUICK_PER;
  const cutFlash = interpolate(quickLocal, [0, 4], [0.09, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  // ── ④ 自由文本(what_happened)── 打字窗口已在上面定义(TAIL_DONE_R),
  //    这里只留提交动作。
  // ── ⑤ Q7/Q8 收尾快掠:提交动作放在最末
  const submitting = frame >= t.at(0.945);
  const submitPressed = frame >= t.at(0.935) && frame <= t.at(0.965);

  const q = EMERGENCY_QUESTIONS;

  return (
    <FilmRoot>
      <div style={{position: 'absolute', inset: 0, opacity: fadeOut}}>
        {/* ① 首页 */}
        {seg === 0 ? (
          <DeviceStage cx={640} cy={540} scale={scale} scrollY={scrollY}>
            <MemoryRouter initialEntries={['/']}>
              <HomePage />
            </MemoryRouter>
          </DeviceStage>
        ) : null}

        {/* ② 第 1 题 */}
        {seg === 1 ? (
          <DeviceStage cx={640} cy={540} scale={scale} scrollY={scrollY}>
            <EmergencyFormView
              question={q[0]}
              index={0}
              total={q.length}
              selected={flagOn > 0.5 ? [...RED_FLAGS] : []}
              handled={0}
              unselectedDim={unselectedDim}
              checkedPop={checkedPop}
            />
          </DeviceStage>
        ) : null}

        {/* ③ 快掠(第 2-5 题,真实会话里都是「已跳过」) */}
        {seg === 2 ? (
          <DeviceStage cx={640} cy={540} scale={scale} scrollY={scrollY}>
            <EmergencyFormView
              question={q[QUICK[quickIdx]]}
              index={QUICK[quickIdx]}
              total={q.length}
              selected={[]}
              handled={QUICK[quickIdx]}
              skipped
            />
          </DeviceStage>
        ) : null}

        {/* ④ 第 6 题 what_happened。
            ★ 这一题展示**真实自由文本**(数据库逐字「在超市突然蹲下捂住耳朵」),
              并用文字逐字落位演出「写下发生了什么」的过程 —— 比勾选框更有信息量。 */}
        {seg === 3 ? (
          <DeviceStage cx={640} cy={540} scale={scale} scrollY={scrollY}>
            <EmergencyFormView
              question={q[WHAT_HAPPENED_INDEX]}
              index={WHAT_HAPPENED_INDEX}
              total={q.length}
              selected={[]}
              note={WHAT_HAPPENED.slice(0, typedChars)}
              handled={6}
            />
          </DeviceStage>
        ) : null}

        {/* ⑤ 第 7、8 题收尾快掠 + 提交。
            ★ 补这两题是为了兑现目标规格的「8 道题逐屏」：原版只演了 Q1..Q6。
              两题在真实会话里都是「已跳过」，因此如实演「跳过」而不编作答 ——
              这正好是右侧「跳过 = 未排除」的实证。
              收尾停在「提交，开始分析」被按下,接 S5 的流式分析。 */}
        {seg === 4 ? (
          <DeviceStage cx={640} cy={540} scale={scale} scrollY={scrollY}>
            <EmergencyFormView
              question={q[TAIL_QUESTIONS[tailIdx]]}
              index={TAIL_QUESTIONS[tailIdx]}
              total={q.length}
              selected={[]}
              handled={8}
              skipped
              submitting={submitting}
              submitPressed={submitPressed}
            />
          </DeviceStage>
        ) : null}

        {/* 高亮圈:只在首页段显示。
            位置用 CSS 变量 + 百分比锚定在真实元素上不现实(影片不读 DOM),
            因此这里用实测过的首页版式常量:应急卡在屏幕内 y≈116..319。
            ★ 与旧版的差别:旧版圈是唯一信息源;这里圈只是「引导视线」,
              真实按钮本身就在圈内,即使圈略有偏差也不会出现「框错位置」的观感。 */}
        {seg === 0 && ringIn > 0 ? (
          <div
            style={{
              position: 'absolute',
              left: 640 - 195 + 16 - 8,
              top: 540 - 422 + 116 - 8,
              width: 358 + 16,
              height: 203 + 16,
              borderRadius: 26,
              border: '3px solid var(--accent)',
              boxShadow: `0 0 ${String(30 + ringPop * 22)}px rgba(194,65,12,${String(0.22 + ringPop * 0.2)})`,
              opacity: ringIn,
              transform: `scale(${String(1.05 - ringIn * 0.05)})`,
              transformOrigin: 'center center',
              pointerEvents: 'none',
            }}
          />
        ) : null}

        {/* 快掠段的切题白闪(强化节拍) */}
        {seg === 2 && cutFlash > 0 ? (
          <div
            style={{
              position: 'absolute', inset: 0,
              backgroundColor: 'var(--bg)', opacity: cutFlash, pointerEvents: 'none',
            }}
          />
        ) : null}

        {/* 右侧说明区 */}
        <div style={{position: 'absolute', left: NOTE_X, top: 250, width: 790}}>
          <NoteKicker>
            {seg === 0
              ? '现场采集 · 入口'
              : `现场采集 · 第 ${String(
                  seg === 1 ? 1
                    : seg === 2 ? QUICK[quickIdx] + 1
                      : seg === 3 ? WHAT_HAPPENED_INDEX + 1
                        : TAIL_QUESTIONS[tailIdx] + 1,
                )} / ${String(q.length)} 题`}
          </NoteKicker>
          <NoteTitle size={40}>
            {seg === 0
              ? '首页只有一件事最重:现在需要帮助'
              : seg === 1
                ? q[0].prompt
                : seg === 2
                  ? q[QUICK[quickIdx]].prompt
                  : seg === 3
                    ? q[WHAT_HAPPENED_INDEX].prompt
                    : q[TAIL_QUESTIONS[tailIdx]].prompt}
          </NoteTitle>

          <div
            style={{
              marginTop: 34, fontFamily: 'var(--font-body)', fontSize: 21,
              color: 'var(--muted)', lineHeight: 1.8,
            }}
          >
            {seg === 0 ? (
              <>
                在现场遇到正在发生的情况,回答几个问题。
                <br />
                应急入口是首页唯一的强调单元。
              </>
            ) : seg === 1 ? (
              <>
                医疗危险是第一个闸门——先排除它,再谈孤独症相关支持。
                <br />
                <span style={{color: 'var(--accent)'}}>
                  真实记录只勾选了「明显疼痛」这一项。
                </span>
              </>
            ) : seg === 2 ? (
              <>
                每一项都可以跳过。
                <br />
                跳过 = 未排除,不会当作正常。
              </>
            ) : seg === 3 ? (
              <>
                唯一写下的一句,是现场的样子:
                <br />
                <span style={{color: 'var(--accent)'}}>
                  「{WHAT_HAPPENED}」
                </span>
              </>
            ) : (
              <>
                八道题走完:只有一项被勾选,一句被写下,
                <br />
                其余全部跳过。
                <br />
                <span style={{color: 'var(--accent)'}}>
                  未答的一律按「未排除」处理,不当作正常。
                </span>
              </>
            )}
          </div>

          {/* 进度条(与屏内进度同步,强化位置感)。
              用「已处理题数」而不是「当前题号」:真实的采集里多项是跳过,
              进度条因此走得慢 —— 这本身就是「跳过 = 未排除」的视觉证据。 */}
          {(() => {
            const handledNow =
              seg === 0 ? 0
                : seg === 1 ? (flagOn > 0.5 ? 1 : 0)
                  : seg === 2 ? QUICK[quickIdx] + 1
                    : seg === 3 ? WHAT_HAPPENED_INDEX + 1
                      : q.length;
            return (
              <div style={{marginTop: 44, width: 420, height: 3, background: 'var(--border)', borderRadius: 2}}>
                <div
                  style={{
                    width: `${String((handledNow / q.length) * 100)}%`,
                    height: '100%', background: 'var(--accent)', borderRadius: 2,
                  }}
                />
              </div>
            );
          })()}
        </div>
      </div>
    </FilmRoot>
  );
};
