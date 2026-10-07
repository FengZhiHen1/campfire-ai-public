// S5 AI 流式分析 —— **原生逐 token 输出**(修复「只是滚动截图」)。
//
// ── 与旧版的根本差别 ──────────────────────────────────────────────────────
// 旧版:在一张静态会话截图上滚动 + 把文字画在叠加层 → 用户评价「你所谓的流式输出
//       只是截图滚动,我要的是仿佛原生的逐 token 输出」。
// 新版:真实文本节点按帧增长,浏览器每帧重新排版 —— 换行位置随文字长度变化、
//       下方元素被真实推下去。这就是原生逐 token 的可见形态。
//       文本来自真实会话(177f965b)的助手输出,**逐字复制**,不是编的。
//
// ── 节奏(1080f / 36s) ────────────────────────────────────────────────────
// 真实 SSE 输出的节奏不是匀速的:首字有一段「思考」等待,然后成段涌出。
// 因此这里不是全程 1.15 帧/字,而是:
//   a 0-90f     提交后等待:思考行显示「正在分析…」+ 底部运行状态条
//   b 90-330f   第一段涌出(判断句,138 字,约 1.3 帧/字 = 3.2s)
//   c 330-560f  第二段(依据与取舍,较长,约 0.9 帧/字 = 更快涌出)
//   d 560-1080f 行动卡落位(用真实 ActionCard 组件渲染真实卡片数据)
import {Easing, interpolate, useCurrentFrame} from 'remotion';

import {ChatScreen} from '../lib/ChatScreen';
import {DeviceStage, FilmRoot} from '../lib/DeviceStage';
import {pushCamera, stagedPush} from '../lib/camera';
import {AssistantMessage, UserBubble} from '../lib/StreamingThread';
import {NoteKicker, NoteTitle, NOTE_X} from '../lib/Shot';
import {STREAM_TEXT} from '../fixtures/stream.generated';
import {FIXTURE_DATA} from '../fixtures/data.generated';
import {useShotTiming} from '../lib/shotTiming';

/** 真实助手正文(从数据库导出,逐字使用)。 */
const TEXTS = STREAM_TEXT.archive.assistantTexts;
/** 判断句 = 第二段(第一段是「我先读一下判据与措辞模板。」这句过渡语)。 */
const JUDGEMENT = TEXTS[1] ?? '';
/** 开场过渡句。 */
const OPENING = TEXTS[0] ?? '';

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
   * 三段的划分(比例)。依据这一段要讲的三件事:
   *   ① 等待 + 首句:思考行显示「正在分析…」,然后真实的第一段文字涌出
   *   ② 判断句涌出:本段的核心 —— 逐 token 输出最长的真实文本(138 字)
   *   ③ 右侧说明推进:正文写完后,由说明区的条目落位接住尾部,避免画面静止
   *
   * ★ 为什么第 ③ 段必须存在:真实会话的助手正文只有两段(13 字 + 138 字)。
   *   若把 40s 全给打字,正文会在约 2/3 处写完,剩下 1/3 段完全静止 —— 那是拖沓。
   *   因此把说明区的四条落位安排在后面,每条一次离散事件,接住尾部。
   */
  const WAIT_END_R = 0.075;
  const JUDGE_START_R = 0.075;
  /** 判断句打完的时刻(按字符数 × 每字帧数反推,见下方 framesPerToken) */
  const JUDGE_DONE_R = 0.5;

  // 相机:★ 用带节拍的推近(见 lib/camera.ts 的说明)。
  // 旧版把 1.00→1.14 铺满 36s → 每帧位移约 0.0001,帧差测不出、观众也看不出,
  // 该段静止率飙到 98%(实测)。现在:分段推近 + 周期位移,
  // 保证任意 20 帧窗口内都有可见的相机变化。
  //
  // ★ v16 二次修正:上限从 1.22 降到 **1.16**。
  //   独立终检实测推近到 1.22 的末段(f2660)设备框**下间隙只剩 2px**(上间隙 18px)——
  //   没有越 1.3 的硬约束,但与影片「大片纸面留白」的视觉语言冲突,读起来像贴边了。
  //   我复算确认(f2400 上下 42/26 → f2660 18/**2**)。
  //   降到 1.16 后:最小边距 **29px**(逐帧全扫 5250 帧,不是抽样 —— f2660 上45/下29)。
  //   推近幅度仍远高于 lib/camera.ts 的「每 30 帧 ≥0.02」下限(0.16 / 40s),运动量不受影响:
  //   降幅后的 S5 静止率实测 **2.6%**(阈值 0.35,与全片同口径;此值随出场地板微调而变)。
  //
  //   ⚠ 这里原先写「2.2%,与调整前一致」和「下间隙回到 40px 量级」——两个都是过时数字。
  //     独立终检指出文档里同一条修正出现过 2.8% / 3.0% / 2.2% 三个值;现测为 2.6%:
  //     该段逐帧 YAVG 有 34/1200 帧 < 0.35。(阈值取 0.30 得 1.7%、0.40 得 3.3%,
  //     所以引用这类比例**必须带上阈值口径**,否则数字之间没法比。)
  const cam = pushCamera(
    frame,
    1.0,
    1.16,
    t.duration,
    {beat: 14, beatPeriod: 30},
  );
  const stageScale = stagedPush(
    frame,
    [1.0, 1.05, 1.11, 1.16],
    [0, t.at(0.3), t.at(0.52), t.at(0.83)],
  );
  const scale = Math.max(cam.scale, stageScale);

  // 屏内滚动:跟随逐 token 输出的内容增长往下走。
  // 给一个「够大」的上限再由 DeviceStage 按真实 scrollHeight 夹紧 ——
  // 对话内容高度随文本增长而变,写死像素会滑出内容底部露空白。
  // 前段(等待 + 首段涌出)停在顶部,让观众看到「正在分析…」到首句的过程。
  const scrollY = interpolate(
    frame,
    [0, t.at(0.3), t.at(0.52), t.at(0.85)],
    [0, 0, 4000, 9999],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.3, 0, 0.25, 1)},
  );

  const fadeOut = interpolate(frame, t.span(0.972, 1), [1, 0.06], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  // 阶段划分
  const phase = frame < t.at(WAIT_END_R) ? 'wait' : frame < t.at(0.3) ? 'judge' : 'rest';

  /**
   * 每字消耗的帧数。
   *
   * ★ 由「判断句要在 JUDGE_DONE_R 处打完」反推,而不是取一个固定常数 ——
   *   这样段长变化时打字速率自动适配,不会出现「打完了还剩半段」或「没打完就切走」。
   */
  const judgeStart = t.at(JUDGE_START_R);
  const judgeEnd = t.at(JUDGE_DONE_R);
  const framesPerToken = Math.max(0.2, (judgeEnd - judgeStart) / Math.max(1, JUDGEMENT.length));

  const noteOpacity = interpolate(frame, t.span(0.018, 0.055), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  /** 右侧说明条目的落位。cue 用比例给,段长变化自动跟随。 */
  const scrollNoteIn = (ratio: number) =>
    interpolate(frame, t.span(ratio, ratio + 0.024), [0, 1], {
      extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
      easing: Easing.bezier(0.2, 0.7, 0.25, 1),
    });

  return (
    <FilmRoot>
      <div style={{position: 'absolute', inset: 0, opacity: fadeOut}}>
        <DeviceStage cx={640 + cam.tx} cy={540 + cam.ty} scale={scale} scrollY={scrollY}>
          <ChatScreen skillLabels={['应急咨询']} footerHint="技能只作用于下一条消息。">
            <UserBubble text="八项现场采集已提交" start={6} />

            {/* 助手消息:思考行 + 逐 token 正文。
                开场过渡句先出(真实的第一段),然后判断句涌出。
                start 用 t.at() 比例派生;framesPerToken 由「判断句在 JUDGE_DONE_R 处打完」反推。 */}
            <AssistantMessage
              paragraphs={[
                {text: OPENING, start: t.at(0.03)},
                {text: JUDGEMENT, start: judgeStart, framesPerToken},
              ]}
              reasoningLabel={phase === 'wait' ? '正在分析…' : '分析说明 · 已结束'}
            />
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
            {/* 右侧说明条目:★ 四条落位安排在**判断句打完之后**(0.52 起),
                用来接住尾部 —— 真实会话的助手正文只有两段,若把 40s 全给打字,
                正文会在约一半处写完,剩下半段完全静止(拖沓)。
                每条一次离散事件,间隔约 0.06 ≈ 2.4s,任意 1s 窗口内都有事件。 */}
            {[
              {t: '先排除医疗危险', d: '「明显疼痛」命中医疗红灯 → 医疗层优先', cue: 0.53},
              {t: '不能只按「环境太吵」解释', d: '这句话来自它的真实输出,不是我们写的旁白', cue: 0.59},
              {t: '档案里的四组已预取', d: '感官特征 · 已验证策略 · 无效策略 · 安全史', cue: 0.65},
              {t: '两组未预存,按未排除处理', d: '不做推断补全 —— 这是产品自己的取舍', cue: 0.71},
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
                本项目已因此出过一次错(S6 把 history 写成 8,实际 9)。
                fixture 是数据库导出的真实标注,见 .tmp/export-fixtures.py。 */}
          <div
            style={{
              marginTop: 40, paddingTop: 24, borderTop: '1px solid var(--border-soft)',
              fontFamily: 'var(--font-body)', fontSize: 18, color: 'var(--fg-2)',
              lineHeight: 1.8, opacity: scrollNoteIn(0.78),
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
