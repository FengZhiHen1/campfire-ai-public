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
import {pushCamera, stagedPush} from '../lib/camera';
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
  const SEG0_END_R = 0.083;
  const SEG1_END_R = 0.46;

  const SEG0_END = timing.at(SEG0_END_R);
  const SEG1_END = timing.at(SEG1_END_R);
  const seg = frame < SEG0_END ? 0 : frame < SEG1_END ? 1 : 2;

  // 相机:★ 单向推近 + 分段推近(lib/camera.ts)。
  //   ★ 2026-10-07:周期漂移分量已删除(用户裁决);分段推近保留(每阶对应叙事上的
  //     下一件事:三档特写 → 卡片 → 来源标注)。
  const camScale = pushCamera(frame, 1.0, 1.2, timing.duration).scale;
  const stageScale = stagedPush(
    frame,
    [1.0, 1.06, 1.13, 1.2],
    [0, SEG0_END, SEG1_END, timing.at(0.78)],
  );
  const scale = Math.max(camScale, stageScale);

  // ★ 屏内滚动:行动卡有 7 个分区、很长。滚动量交给 DeviceStage 按真实 scrollHeight
  //   夹紧(写死像素在卡片长度变化时会滚出底部露空白 —— 旧版 1760 就是猜的)。
  //
  // ★★ 2026-10-07 改**两次刹车**(镜头卡 scroll-brake-moves 的语法):
  //   旧版是一条贝塞尔一路滚到底 —— 25 秒连续平移,读起来像「资料在飘」。
  //   现在:滚到「01 当前状态」停一下、再滚到「02 立即怎么沟通」停一下、然后到底。
  //   停车点用像素给,理由与旧版一致(DeviceStage 按真实 scrollHeight 夹紧);
  //   ⚠ 3200 / 6400 是**初值**,由逐帧 still 自检校准到两个分区真正停在读数位置。
  const BRAKE1 = 3200;
  const BRAKE2 = 6400;
  const scrollY = interpolate(
    frame,
    [
      0,
      SEG0_END,
      timing.at(0.1),
      timing.at(0.18),
      timing.at(0.3),
      timing.at(0.4),
      timing.at(0.52),
      timing.at(0.86),
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
  const badgeOn = (i: number) =>
    interpolate(
      frame,
      timing.span(SEG0_END_R * (0.28 + i * 0.2), SEG0_END_R * (0.55 + i * 0.2)),
      [0, 1],
      {
        extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
        easing: Easing.bezier(0.2, 0.75, 0.3, 1),
      },
    );
  const badgePop = (i: number) =>
    1 - interpolate(
      frame,
      timing.span(SEG0_END_R * (0.55 + i * 0.2), SEG0_END_R * (0.72 + i * 0.2)),
      [0, 1],
      {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
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
          <>
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
                left: interpolate(frame, [20, SEG0_END + 20], [-540, 2480], {
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
          </>
        ) : null}

        {/* ② ③ 真实行动卡在设备里滚动 */}
        {seg > 0 ? (
          <>
            <style>{underlineCss(sectionIdx(1), draw1)}</style>
            <style>{underlineCss(sectionIdx(2), draw2)}</style>
            <DeviceStage cx={640} cy={540} scale={scale} scrollY={scrollY}>
              <ActionCardScreen data={CARD} />
            </DeviceStage>
          </>
        ) : null}

        {/* 右侧说明区 */}
        {seg > 0 ? (
          <div style={{position: 'absolute', left: NOTE_X, top: 230, width: 790}}>
            <NoteKicker opacity={noteIn(SEG0_END_R)}>本次结果 · 现场行动卡</NoteKicker>
            <NoteTitle opacity={noteIn(SEG0_END_R + 0.01)} size={42}>
              {seg === 1 ? '七节分区,先看哪一节由闸门决定' : '每条建议都带着它的出处'}
            </NoteTitle>

            {seg === 1 ? (
              <div
                style={{
                  marginTop: 36, fontFamily: 'var(--font-body)', fontSize: 21,
                  color: 'var(--muted)', lineHeight: 1.8,
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
                    const t = noteIn(SEG1_END_R + 0.037 + i * 0.028);
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
