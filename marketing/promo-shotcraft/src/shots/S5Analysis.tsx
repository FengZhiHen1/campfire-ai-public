// S5 AI 流式分析 —— **原生逐 token 输出**(修复「只是滚动截图」)。
//
// ── 与旧版的根本差别 ──────────────────────────────────────────────────────
// 旧版:在一张静态会话截图上滚动 + 把文字画在叠加层 → 用户评价「你所谓的流式输出
//       只是截图滚动,我要的是仿佛原生的逐 token 输出」。
// 新版:真实文本节点按帧增长,浏览器每帧重新排版 —— 换行位置随文字长度变化、
//       下方元素被真实推下去。这就是原生逐 token 的可见形态。
//       文本来自真实会话(177f965b)的助手输出,**逐字复制**,不是编的。
//
// ── ★ 2026-10-07 v18:整段 SSE 走完,一直到**行动卡真的出现** ──────────────
// 用户裁决「节奏明显偏慢,是为了凑时长」并选定「压缩 + 补真实内容」,给的例子就是
// 本段:「换成整段 SSE 逐 token 直到卡片真的出现,而不是只打 138 字就停」。
//
// 旧版把 40s 花在哪(代码推导,见 timeline.ts 的 v18 注释):
//   · 死头 3.00s(WAIT_END_R=0.075):只有「正在分析…」＋右栏淡入;
//   · 判断句 138 字打 17.0s(3.70 帧/字 = 每秒 8.1 字);
//   · 一条滚动铺 14s,末尾还有 2.87s 空档。
// 而**真实会话的思考段**(reasoningTexts,3 段共 2 万余字)**一个字都没演** ——
// 影片把折叠区正文写死成占位句。那段推理正是本段右栏那句
// 「它不是先给结论,是按固定顺序过六层闸门」的实证。
//
// 现在本段 = 真实 SSE 的完整形状,26s:
//   a 0.00-0.05  提交后等待:思考行「正在分析…」
//   b 0.05-0.31  **展开思考区**,真实推理节选逐字输出(节选自 fixture 现取),然后收起
//   c 0.33-0.56  正文两段逐字输出(13 字 + 138 字)
//   d 0.56-0.61  结论行贴身 accent 竖线 draw-on(一次事件,画完即停)
//   e 0.63-1.00  **行动卡在对话里出现**(用产品的真实 <ActionCard> 渲染真实数据)
// ── 节奏说明 ─────────────────────────────────────────────────────────────
// 真实 SSE 不是匀速的:首字前有一段思考,然后成段涌出。本段的三个速率都由
// 「这段要在第几帧做完」反推,段长再变时自动适配,不会出现「打完了还剩半段」。
import {Easing, interpolate, useCurrentFrame} from 'remotion';

import {ChatScreen} from '../lib/ChatScreen';
import {DeviceStage, FilmRoot} from '../lib/DeviceStage';
import {pushCamera, stagedPush} from '../lib/camera';
import {AssistantMessage, UserBubble} from '../lib/StreamingThread';
import {NoteKicker, NoteTitle, NOTE_X} from '../lib/Shot';
import {STREAM_TEXT} from '../fixtures/stream.generated';
import {FIXTURE_DATA} from '../fixtures/data.generated';
import {useShotTiming} from '../lib/shotTiming';
import {ActionCard} from '../../../../apps/web/src/features/consult/view/MessageParts/ActionCard';
import type {ActionCardEvent} from '../../../../apps/web/src/shared/types/sse';

/** 真实助手正文(从数据库导出,逐字使用)。 */
const TEXTS = STREAM_TEXT.archive.assistantTexts;
/** 判断句 = 第二段(第一段是「我先读一下判据与措辞模板。」这句过渡语)。 */
const JUDGEMENT = TEXTS[1] ?? '';
/** 开场过渡句。 */
const OPENING = TEXTS[0] ?? '';

/**
 * 思考段节选 —— **从 fixture 现取,不手抄**。
 *
 * ★ 为什么现取:这段文本要满足「逐字来自真实记录」,手抄进源码就有转录失真的可能
 *   (本项目已经因为「手写会与数据漂移」出过错,见 S6 把 history 写成 8)。
 *   窗口起点定在医疗闸门那条(`- medical_red_flags:`),终点取其后最近的句号 ——
 *   于是它是一段**连续、逐字**的原文,只是不完整(故尾注标明节选)。
 *
 * ★ 为什么只取节选而不是全部 2 万字:折叠区没有高度上限,全量会把正文挤出屏幕;
 *   而观众要看到的是「它真的在逐条过闸门」,不是读完一条思维链。
 */
const REASONING_FULL = STREAM_TEXT.archive.reasoningTexts[1] ?? '';
const _EXCERPT_FROM = REASONING_FULL.indexOf('- medical_red_flags');
const _EXCERPT_TO = REASONING_FULL.indexOf('。', _EXCERPT_FROM + 240) + 1;
const REASONING_EXCERPT =
  _EXCERPT_FROM >= 0 && _EXCERPT_TO > _EXCERPT_FROM
    ? REASONING_FULL.slice(_EXCERPT_FROM, _EXCERPT_TO)
    : '';
/** 节选尾注:如实说明这是节选,而不是假装它是全部。 */
const REASONING_HINT = `节选自本次分析的思考记录(原文共 ${String(
  REASONING_FULL.length,
)} 字)。分析说明是中间状态,不作为结论或依据。`;

/** 真实行动卡载荷(数据库导出的 emit_emergency_action_card 参数)。 */
const CARD = FIXTURE_DATA.sessions.archive.actionCard as unknown as ActionCardEvent;

/**
 * 本会话真实行动卡的标注分布(用于「真实产生 N 条来源标注」那行)。
 *
 * ★ 现算而不是手写:手写数字会与数据漂移,本项目已因此出过一次错
 *   (S6 把 history 写成 8,实际是 9)。fixture 是数据库导出的真实标注。
 *   标注的线上格式是 `"<source>:<confidence>"`(见产品
 *   apps/web/src/features/consult/domain/actionCard.ts 的 decodeAnnotation)。
 */
const CARD_ANNOTATIONS = (
  FIXTURE_DATA.sessions.archive.actionCard?.annotations ?? []
) as readonly {target: string; kind: string}[];
const ANNOTATION_TOTAL = CARD_ANNOTATIONS.length;
function annotationCount(source: string): number {
  return CARD_ANNOTATIONS.filter((a) => a.kind.split(':')[0] === source).length;
}

export const S5Analysis: React.FC = () => {
  const frame = useCurrentFrame();
  const t = useShotTiming();

  /**
   * 四段的划分(比例)。依据这一段要讲的三件事:
   *   ① 等待 → 展开思考区,真实推理涌出(这是「过六层闸门」的实证)
   *   ② 判断句涌出:逐 token 输出最长的真实文本(138 字)
   *   ③ 行动卡在对话里出现 —— SSE 的终点,不再用滚动与描线去填尾巴
   */
  const WAIT_END_R = 0.05;
  /** 展开思考区(使用者的一次动作,不是自动展开 —— 产品契约要求默认收起) */
  const REASON_OPEN_R = 0.05;
  const REASON_START_R = 0.075;
  /** 节选打完的时刻 */
  const REASON_DONE_R = 0.3;
  /** 收起思考区 */
  const REASON_CLOSE_R = 0.315;
  /** 判断句开始涌出 */
  const JUDGE_START_R = 0.33;
  /** 判断句打完(按字符数反推每字帧数) */
  const JUDGE_DONE_R = 0.56;
  /** 行动卡出现 */
  const CARD_IN_R = 0.63;

  // 相机:★ 单向推近 + 分段推近(lib/camera.ts)。
  //   ★ 2026-10-07:周期漂移分量已删除(用户裁决);本段的主运动本来就是
  //     **逐 token 流式输出**,漂移是当年为填帧差而加的。
  const camScale = pushCamera(frame, 1.0, 1.16, t.duration).scale;
  const stageScale = stagedPush(
    frame,
    [1.0, 1.05, 1.11, 1.16],
    [0, t.at(0.28), t.at(0.5), t.at(0.78)],
  );
  const scale = Math.max(camScale, stageScale);

  /**
   * 屏内滚动:卡片到场后,把「卡片顶」送到页头下方。
   *
   * ★ 为什么是**标定过的最小位移**而不是「给个大值让它夹到底」:
   *   夹紧上限 = thread 的全部溢出量,而行动卡本身很高(远高于一屏)。滚到上限会把
   *   正文整段推出视野,并在卡片上方留下大片空白(实测静帧:f1820 上方空了约 590px)。
   *   这个像素值与 S6 的 BRAKE1/BRAKE2 同一性质 —— 由逐帧静帧标定,不是猜的。
   *   ★ 它只有在 DeviceStage 的夹紧改用量 `.film-chat-thread` 之后才生效:
   *     在此之前对话页的 max 恒为 0,给多少都不动(那正是「卡片只露顶部」的原因)。
   */
  const CARD_SCROLL = 570;
  const scrollY = interpolate(
    frame,
    [0, t.at(0.6), t.at(0.72)],
    [0, 0, CARD_SCROLL],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.25, 0, 0.2, 1)},
  );

  /**
   * 结论行的**贴身**标注(镜头卡 scanline-annotate-focus 的语法,去掉扫描线,只留「画出依据线」)。
   *
   * ★ 为什么是元素相对的 ::before,而不是画布坐标上的一个框:
   *   本项目在「另画一层」上栽过两次(S4 的圈要靠实测常量、S3 的记录写明相机缩放会让
   *   画布坐标的圈与元素错位)。这里让标注长在**真实元素自己**身上(左缘竖线 scaleY 展开),
   *   缩放、滚动、重排全部自动跟随,结构上不可能错位。
   *
   * 为什么是 draw-on 而不是常亮:它是**一次事件**(「找到了这一行」),画完就停;
   *   常亮描边会变成又一个无声明的装饰。
   */
  const annotateDraw = interpolate(frame, t.span(0.565, 0.61), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.25, 0, 0.2, 1),
  });

  /** 行动卡的到场:一次位移 + 淡入(卡片是 SSE 的最后一个事件)。 */
  const cardIn = interpolate(frame, t.span(CARD_IN_R, CARD_IN_R + 0.05), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.2, 0.7, 0.25, 1),
  });

  const fadeOut = interpolate(frame, t.span(0.972, 1), [1, 0.06], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  // 阶段划分:思考期仍显示「正在分析…」,打完显示「分析说明 · 已结束」
  const reasoningDone = frame >= t.at(REASON_DONE_R);
  const reasoningOpen = frame >= t.at(REASON_OPEN_R) && frame < t.at(REASON_CLOSE_R);

  /**
   * 每字消耗的帧数。
   *
   * ★ 由「这段要在第几帧打完」反推,而不是取一个固定常数 ——
   *   这样段长变化时打字速率自动适配,不会出现「打完了还剩半段」或「没打完就切走」。
   */
  const judgeStart = t.at(JUDGE_START_R);
  const judgeEnd = t.at(JUDGE_DONE_R);
  const framesPerToken = Math.max(0.2, (judgeEnd - judgeStart) / Math.max(1, JUDGEMENT.length));
  const reasonStart = t.at(REASON_START_R);
  const reasonFramesPerToken = Math.max(
    0.2,
    (t.at(REASON_DONE_R) - reasonStart) / Math.max(1, REASONING_EXCERPT.length),
  );

  const noteOpacity = interpolate(frame, t.span(0.012, 0.04), [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  /** 右侧说明条目的落位。cue 用比例给,段长变化自动跟随。 */
  const scrollNoteIn = (ratio: number) =>
    interpolate(frame, t.span(ratio, ratio + 0.024), [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.bezier(0.2, 0.7, 0.25, 1),
    });

  return (
    <FilmRoot>
      <div style={{position: 'absolute', inset: 0, opacity: fadeOut}}>
        {/* 结论行的贴身标注:作用在**真实段落元素**上的左缘竖线,由帧驱动展开。
            选择器限定在 .film-root 内,不影响产品自身样式。 */}
        <style>{`
          .film-root .chat-message .msg-doc p:last-child { position: relative; }
          .film-root .chat-message .msg-doc p:last-child::before {
            content: '';
            position: absolute;
            left: -14px; top: 2px; bottom: 2px; width: 3px;
            background: var(--accent);
            border-radius: 2px;
            transform: scaleY(${annotateDraw.toFixed(3)});
            transform-origin: top center;
            opacity: ${(annotateDraw * 0.9).toFixed(3)};
          }
        `}</style>
        <DeviceStage cx={640} cy={540} scale={scale} scrollY={scrollY}>
          <ChatScreen skillLabels={['应急咨询']} footerHint="技能只作用于下一条消息。">
            <UserBubble text="八项现场采集已提交" start={6} />

            {/* 助手消息:思考行(可展开,真实节选) + 逐 token 正文。
                开场过渡句先出(真实的第一段),然后判断句涌出。 */}
            <AssistantMessage
              paragraphs={[
                {text: OPENING, start: t.at(0.315)},
                {text: JUDGEMENT, start: judgeStart, framesPerToken},
              ]}
              reasoningLabel={reasoningDone ? '分析说明 · 已结束' : '正在分析…'}
              reasoningText={REASONING_EXCERPT}
              reasoningStart={reasonStart}
              reasoningFramesPerToken={reasonFramesPerToken}
              reasoningOpen={reasoningOpen}
              reasoningHint={REASONING_HINT}
            />

            {/* ★ 行动卡:SSE 的最后一个事件,在对话里**真的出现**。
                结构与产品一致(ChatWorkspace 的 MessageRow:.chat-message > .msg-doc),
                卡片本体交给产品的 <ActionCard> 渲染 —— 来源与置信由产品自己的
                domain/actionCard.ts 映射产生,影片写不错。 */}
            <div
              className="chat-message"
              style={{
                opacity: cardIn,
                // ★ 必须把滚动位移**合进这个行内 transform**:行内样式会压过样式表里
                //   `.film-chat-thread > *` 的位移规则 ⇒ 否则同一层的兄弟节点都跟着滚,
                //   只有卡片不动。实测症状:上方内容移出视野,卡片却停在原位、
                //   它上方留出约 590px 空白。--film-scroll 是继承来的变量,calc 里可用。
                transform: `translateY(calc(${((1 - cardIn) * 22).toFixed(1)}px - var(--film-scroll, 0px)))`,
              }}
            >
              <div className="msg-doc">
                <ActionCard data={CARD} expired={false} />
              </div>
            </div>
          </ChatScreen>
        </DeviceStage>

        {/* 右侧说明区:讲「AI 在这一步做了什么」,随输出阶段推进 */}
        <div style={{position: 'absolute', left: NOTE_X, top: 230, width: 790}}>
          <NoteKicker opacity={noteOpacity}>核心功能 · AI 如何得出结论</NoteKicker>
          <NoteTitle opacity={noteOpacity} size={42}>
            它不是先给结论,
            <br />
            是按固定顺序过六层闸门。
          </NoteTitle>

          <div
            style={{
              marginTop: 36, display: 'flex', flexDirection: 'column', gap: 18,
            }}
          >
            {/* 右侧说明条目。cue 按比例给出,段长变化自动跟随。
                ★ v18:前两条紧贴**思考区展开**那一段(cue 0.10/0.17),它们是「闸门
                真的在过」的注解,与画面上的真实推理同步;后两条接在正文之后。 */}
            {[
              {t: '先排除医疗危险', d: '「明显疼痛」命中医疗红灯 → 医疗层优先', cue: 0.1},
              {t: '推理过程逐条写在明面上', d: '上一屏的思考区是它自己的输出,逐字未改', cue: 0.17},
              {t: '不能只按「环境太吵」解释', d: '这句话来自它的真实输出,不是我们写的旁白', cue: 0.4},
              {t: '档案里的四组已预取', d: '感官特征 · 已验证策略 · 无效策略 · 安全史', cue: 0.48},
            ].map((item) => {
              // ★ 变量名不要用 t —— 外层 t 是 useShotTiming() 的返回值,会被遮蔽
              const appear = scrollNoteIn(item.cue);
              return (
                <div
                  key={item.t}
                  style={{
                    display: 'flex', gap: 16, alignItems: 'flex-start',
                    opacity: appear, transform: `translateY(${(1 - appear) * 14}px)`,
                  }}
                >
                  <span
                    style={{
                      width: 8, height: 8, borderRadius: 9999,
                      backgroundColor: 'var(--accent)', marginTop: 10, flexShrink: 0,
                    }}
                  />
                  <div>
                    <div style={{fontFamily: 'var(--font-body)', fontSize: 21, color: 'var(--fg)'}}>
                      {item.t}
                    </div>
                    <div style={{fontFamily: 'var(--font-body)', fontSize: 17, color: 'var(--muted)', marginTop: 5}}>
                      {item.d}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* 真实的依据条数。
              ★ 数字**从 fixture 现算**,不手写 —— 手写会与数据漂移,
                本项目已因此出过一次错(S6 把 history 写成 8,实际 9)。 */}
          <div
            style={{
              marginTop: 40, paddingTop: 24, borderTop: '1px solid var(--border-soft)',
              fontFamily: 'var(--font-body)', fontSize: 18, color: 'var(--fg-2)',
              lineHeight: 1.8, opacity: scrollNoteIn(0.72),
            }}
          >
            {`本次会话真实产生 ${String(ANNOTATION_TOTAL)} 条来源标注:`}
            <br />
            {`历史记录 ${String(annotationCount('history'))} · AI 推断 ${String(annotationCount('ai_inference'))} · 家属报告 ${String(annotationCount('family_report'))} · 现场观察 ${String(annotationCount('onsite_observation'))}。`}
          </div>
        </div>
      </div>
    </FilmRoot>
  );
};
