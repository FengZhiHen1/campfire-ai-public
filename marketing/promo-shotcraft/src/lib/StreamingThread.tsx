// StreamingThread —— 用真实产品的消息类名渲染一条「正在逐 token 输出」的助手消息。
//
// ── 与旧版伪造流式的根本差别 ──────────────────────────────────────────────
// 旧版:滚动一张静态截图,把文字画在叠加层上 —— 本质是「滚截图」,不是流式。
// 本组件:真实文本节点按帧增长,浏览器每帧重新排版 —— 这就是原生逐 token:
//   文本变长 → 换行位置变化 → 下方元素被推下去 → 全部由 DOM 真实回流产生。
//   因此不会出现「文字溢出容器」「与下方重叠」这类叠加层特有的错误。
//
// ── 使用的类名来自产品契约(consultComponents.css) ─────────────────────
//   .stack / .chat-message / .bubble-user / .message-caption / .msg-doc
//   .reasoning-row / .process-body / .hint
// 不自己写样式,因此影片里的消息外观与真实产品一致。
import {Easing, interpolate, useCurrentFrame} from 'remotion';

import {STREAM_TEXT} from '../fixtures/stream.generated';

/** 真实助手正文(从数据库导出)。 */
const ARCHIVE_TEXTS = STREAM_TEXT.archive.assistantTexts;
const NO_ARCHIVE_TEXTS = STREAM_TEXT.noArchive.assistantTexts;

/** 取「有档案」会话的主判断句(第二段,内容是六层闸门自述)。 */
const JUDGEMENT = ARCHIVE_TEXTS[1] ?? '';
/** 取「无档案」会话的说明段。 */
const NO_ARCHIVE_NOTE = NO_ARCHIVE_TEXTS[0] ?? '';

export interface StreamingLineProps {
  /** 完整文本 */
  text: string;
  /** 开始输出的帧(相对本组件) */
  start: number;
  /** 每 token 消耗帧数 */
  framesPerToken?: number;
  /** 文字大小(px) */
  size?: number;
  /** 文字色 */
  color?: string;
  /** 是否显示输出光标 */
  cursor?: boolean;
  /** 光标色 */
  cursorColor?: string;
}

/**
 * 一行逐 token 输出的文本。
 *
 * 前置: text 非空
 * 后置: 第 start 帧起按 framesPerToken 逐字揭示;完成前在末尾显示光标
 * 异常: 无
 *
 * 切分口径:按**字符**而非词 —— 中文没有词边界,按字符最接近真实 SSE 的增量。
 * 这正是「逐 token」在中文界面上的可见形态。
 */
export const StreamingLine: React.FC<StreamingLineProps> = ({
  text,
  start,
  framesPerToken = 1.4,
  size = 17,
  color = 'var(--fg)',
  cursor = true,
  cursorColor = 'var(--accent)',
}) => {
  const frame = useCurrentFrame();
  const elapsed = frame - start;
  if (elapsed < 0) return null;

  const shown = Math.floor(elapsed / framesPerToken);
  const count = Math.min(shown, text.length);
  const visible = text.slice(0, count);
  const done = count >= text.length;
  // 光标 8 帧周期闪烁(与真实终端/SSE 光标观感一致)
  const cursorOn = cursor && !done && Math.floor(frame / 4) % 2 === 0;

  return (
    <span style={{fontSize: size, color, lineHeight: 'var(--leading-body)'}}>
      {visible}
      {cursorOn ? (
        <span
          style={{
            display: 'inline-block',
            width: size * 0.42,
            height: size * 1.05,
            backgroundColor: cursorColor,
            marginLeft: 2,
            verticalAlign: 'text-bottom',
          }}
        />
      ) : null}
    </span>
  );
};

/**
 * 完整的助手消息块:思考折叠行 + 正文。
 *
 * 结构逐字复刻 ChatWorkspace 的消息 DOM(见其 MessageRow):
 *   .chat-message > .stack? > .bubble-user(使用者) / .message-caption + .msg-doc(助手)
 */
export const AssistantMessage: React.FC<{
  /**
   * 正文段(按顺序逐段输出)。
   * `framesPerToken` 可选:由调用方按「这段要在第几帧打完」反推,
   * 因此段长变化时打字速率自动适配(见 shots/S5Analysis.tsx)。
   */
  paragraphs: readonly {text: string; start: number; framesPerToken?: number}[];
  /** 思考段是否显示(默认显示为「正在分析…」折叠行) */
  showReasoning?: boolean;
  /** 思考行的状态文案 */
  reasoningLabel?: string;
  /** 标题(「篝火智答」) */
  caption?: string;
}> = ({paragraphs, showReasoning = true, reasoningLabel, caption = '篝火智答'}) => {
  const frame = useCurrentFrame();
  const firstStart = paragraphs[0]?.start ?? 0;
  const reasoningDone = frame > firstStart + 20;

  return (
    <div className="chat-message">
      <p className="meta message-caption">{caption}</p>
      <div className="msg-doc">
        {showReasoning ? (
          <details className="reasoning-row" open={false}>
            <summary>
              <span>
                {reasoningLabel ?? (reasoningDone ? '分析说明 · 已结束' : '正在分析…')}
              </span>
              <span className="toggle-label">
                <span className="when-closed">展开</span>
                <span className="when-open">收起</span>
              </span>
            </summary>
            <div className="process-body">
              分析说明是中间状态，不作为结论或依据。
            </div>
          </details>
        ) : null}
        {paragraphs.map((p, i) => (
          <p key={i}>
            <StreamingLine
              text={p.text}
              start={p.start}
              {...(p.framesPerToken === undefined ? {} : {framesPerToken: p.framesPerToken})}
            />
          </p>
        ))}
      </div>
    </div>
  );
};

/** 使用者气泡(真实文案取自产品应急表单的提交摘要)。 */
export const UserBubble: React.FC<{text: string; start: number}> = ({text, start}) => {
  const frame = useCurrentFrame();
  const appear = interpolate(frame, [start, start + 8], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.2, 0.7, 0.25, 1),
  });
  if (appear <= 0) return null;
  return (
    <div className="chat-message">
      <div className="bubble-user" style={{opacity: appear}}>
        {text}
      </div>
    </div>
  );
};

export {JUDGEMENT, NO_ARCHIVE_NOTE};
