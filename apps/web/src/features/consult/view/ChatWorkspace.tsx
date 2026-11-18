/**
 * 模块: features/consult/view/ChatWorkspace
 * 职责: 对话工作面——消息流、状态条、候选轻提示、输入区（含待作答时的收起）
 * 数据来源:
 *   - docs/design/pages/对话页.md: MUST — 布局结构、状态覆盖表、输入区互斥、
 *     响应式与平台（平板/PC 经手机蒙版渲染，蒙版体验无损）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 3 节（状态条/发送禁用）、第 7 节（失败语义）
 * 边界:
 *   - 依赖: shared/ui/DeviceFrame、viewModel 的 useChatWorkspace、MessageParts、SkillPicker、react-router
 *   - 被依赖: view 的 ChatPage
 * 禁止行为:
 *   - 禁止把 reasoning 渲染进正文（思考只经 ReasoningDisclosure）
 *   - 禁止在待作答时恢复输入区（提交或问题组移除后才恢复，页面设计布局结构第 3 节）
 *   - 禁止用「未找到相关内容」这类文案（不变量 2）
 *
 * 职责分层：本组件只做渲染。运行呈现控制、跳过引导、草稿提交与重试、消息流派生判定
 * 全部在 viewModel/useChatWorkspace 里（第一 commit 迁出，行为与导出保持不变）。
 */

import { Link } from 'react-router';
import {
  AssistantRuntimeProvider,
  MessagePrimitive,
  ThreadPrimitive,
} from '@assistant-ui/react';

import { BackLink } from '../../../shared/ui/BackLink';
import { Icon } from '../../../shared/ui/Icon';
import { BrandMark } from '../../../shared/ui/BrandMark';
import { DeviceFrame } from '../../../shared/ui/DeviceFrame';
import type { ConsultPort } from '../application/ports';
import { PROGRESS_TEXT } from '../domain/types';
import { SkillPicker } from './SkillPicker';
import { CONSULT_EMERGENCY_PATH, consultChatPath } from './consultRoutes';
import { ConsultMessageParts, ConsultThreadProvider } from './MessageParts/parts';
import { useChatWorkspace } from '../viewModel/useChatWorkspace';
import styles from './chatPage.module.css';

// 兼容既有对外导出：这些判定原来定义在本文件，测试与本模块的其它消费者按旧路径导入。
export { newestActionCardId } from '../viewModel/useChatWorkspace';

/** 使用者消息里的 text part 直接内联渲染（气泡不支持块级段落，见 chatPage.module.css 说明）。 */
const USER_MESSAGE_COMPONENTS = {
  Text: ({ text }: { text: string }) => <>{text}</>,
} as const;

/** 单条消息：使用者是右对齐气泡，助手是全宽读物（对话页设计的核心视觉决策）。 */
function MessageRow() {
  return (
    <MessagePrimitive.Root className="chat-message">
      <MessagePrimitive.If user>
        <div className="bubble-user">
          <MessagePrimitive.Parts components={USER_MESSAGE_COMPONENTS} />
        </div>
      </MessagePrimitive.If>
      <MessagePrimitive.If assistant>
        <p className="meta message-caption">篝火智答</p>
        <div className="msg-doc">
          <ConsultMessageParts />
        </div>
      </MessagePrimitive.If>
    </MessagePrimitive.Root>
  );
}

/** 对话工作面 props。 */
export interface ChatWorkspaceProps {
  initialDraft?: string;
  sessionId: string;
  /** 水合得到的初始消息。 */
  initialMessages: Parameters<typeof useChatWorkspace>[0]['initialMessages'];
  /** 订阅不可续传时请求重新水合（由对话页交给会话装配的 retry）。 */
  onNeedsResync?: () => void;
  /** 一次性引导是否仍待处理（决定页头是否给「跳过引导」）。 */
  guidePending?: boolean;
  /** 引导已收束（跳过成功 / 已出现「完成引导」）：调用方据此撤掉入口与记忆标记。 */
  onGuideSettled?: () => void;
  consult: ConsultPort;
}

/**
 * 渲染对话工作面。
 *
 * 前置: 历史水合已完成（loading/error 由 ChatPage 处置）
 * 后置: 输出 DeviceFrame 包裹的消息流、状态条、候选轻提示与输入区；待作答时收起输入区
 * 异常: 无
 *
 * 滚动责任分层（外壳落地后新增，必须保持）
 *
 * 本页是「满高 flex + 内部滚动 + 输入区贴底」的自成体系布局，而 DeviceFrame 的屏幕区
 * 本身也是滚动容器，两者叠加会出现嵌套滚动。约定如下：
 *   1. `.device-screen` 不滚动——`.workspace` 撑满它（100%），本页内部消化所有滚动；
 *   2. `.thread` 在剩余空间内滚动（剩余空间之上是吸顶页头与候选提示，之下是输入区）；
 *   3. 页头与输入区因此天然留在外壳可视区内，输入区不可能被滚出屏幕。
 * 窄视口下屏幕区不生成盒子（display: contents），.workspace 的 100% 退化为内容高，
 * 由文档承担滚动——与外壳落地前的行为一致。
 */
export function ChatWorkspace({
  sessionId,
  initialMessages,
  initialDraft = '',
  consult,
  onNeedsResync,
  guidePending = false,
  onGuideSettled,
}: ChatWorkspaceProps) {
  const ws = useChatWorkspace({
    sessionId,
    initialMessages,
    consult,
    ...(initialDraft === '' ? {} : { initialDraft }),
    ...(onNeedsResync === undefined ? {} : { onNeedsResync }),
    guidePending,
    ...(onGuideSettled === undefined ? {} : { onGuideSettled }),
  });
  const { thread, runtime } = ws;

  return (
    <DeviceFrame>
      <AssistantRuntimeProvider runtime={runtime.runtime}>
        <ConsultThreadProvider value={ws.threadContext}>
          <div className={styles.workspace}>
            <header className="subpage-head">
              {/*
                direct：应急提交经「固定跳转」进入本页（EmergencyFormPage 用 navigate(consultChatPath)），
                此时 history.idx 指向上一个屏（刚提交的表单）；若不显式钉住目标，window.history.idx
                的「往回一屏」会退回表单。返回目标固定为咨询历史（/consult），符合「提交后回列表」。
              */}
              <BackLink fallback="/consult" direct />
              <span className="sp-title">咨询</span>
              {/*
                宽度不足时整体折叠为一个汇总标签，而不是「前 N 个 + +N 徽标」——
                授权语义明确否定了徽标形态（对话页设计文档的布局结构第 1 条）。
                折叠判定在 viewModel（SKILL_TAG_COLLAPSE_THRESHOLD）。
              */}
              {ws.showSkipGuide ? (
                <button
                  type="button"
                  className={`${styles.guideSkip} meta`}
                  onClick={ws.skipGuide}
                  disabled={ws.skipping || thread.isRunning}
                >
                  {ws.skipping ? '正在跳过…' : '跳过引导'}
                </button>
              ) : null}
              {ws.skillTags.map((label) => (
                <span key={label} className="tag meta sp-tag">
                  {label}
                </span>
              ))}
            </header>

            {ws.skipFailed === null ? null : (
              <p className="status off" role="alert">
                跳过引导没有成功：{ws.skipFailed}
              </p>
            )}

            {ws.candidates.length === 0 ? null : (
              <details className="candidate-toast chat-candidate">
                <summary>
                  <span>有 {ws.candidates.length} 条待确认</span>
                  <span className="toggle-label">
                    <span className="when-closed">预览</span>
                    <span className="when-open">收起</span>
                  </span>
                </summary>
                <div className="ct-panel">
                  {ws.candidates.map((candidate) => (
                    <div key={`${candidate.source}-${candidate.summary}`}>
                      <p>{candidate.summary}</p>
                      <p className="meta">来源：{candidate.source}</p>
                    </div>
                  ))}
                  <Link className="btn block" to="/profile">
                    去档案核对
                  </Link>
                </div>
              </details>
            )}

            <div className={styles.thread} role="log" aria-label="咨询消息" aria-live="off">
              {thread.messages.length === 0 && (
                <section className="chat-welcome" aria-label="开始咨询">
                  <span className="chat-welcome-mark"><BrandMark size="32px" /></span>
                  <h1>从你在意的事开始</h1>
                  <p>说说具体的情况，也可以先写下你的困惑。我们一起梳理下一步。</p>
                  <div className="stack">
                    <button className="btn btn-secondary" type="button" onClick={() => ws.setDraft('我想聊聊最近发生的一件事。')}>聊聊最近发生的事</button>
                    <button className="btn btn-secondary" type="button" onClick={() => ws.setDraft('我想一起准备下一次外出。')}>一起准备下一次外出</button>
                  </div>
                </section>
              )}
              <ThreadPrimitive.Root>
                <ThreadPrimitive.Viewport>
                  <ThreadPrimitive.Messages>{() => <MessageRow />}</ThreadPrimitive.Messages>
                </ThreadPrimitive.Viewport>
              </ThreadPrimitive.Root>
              {ws.interrupted ? <p className="status off">{PROGRESS_TEXT.interrupted}</p> : null}
            </div>

            <div className={styles.footer}>
              {ws.statusText !== null || thread.isRunning ? (
                <div className="chat-run-controls">
                  {ws.statusText !== null ? (
                    <div className="chat-progress" data-tone={ws.showProgressDot ? 'working' : 'info'}>
                      {ws.showProgressDot ? <span className="flame-dot breathing" aria-hidden="true" /> : null}
                      <span role="status" aria-live="polite">{ws.statusText}</span>
                    </div>
                  ) : null}
                  {thread.isRunning ? (
                    <button type="button" className="text-button chat-stop" onClick={runtime.stop}>
                      <span aria-hidden="true" />
                      停止
                    </button>
                  ) : null}
                </div>
              ) : null}

              {/*
                失败反馈：像「服务回话」而不是报错弹层。原因在上（标题 + 一句说明），动作在下
                （重试）。关联到输入器的 aria-describedby，读屏聚焦输入时能听到「上一条没发出去」，
                不必先看见红色块。Retry 保留（run 失败/发送失败都走同一路）。
              */}
              {ws.failure === null ? null : (
                <div className="error-card" role="alert" id="consult-run-failure">
                  <strong className="ec-title">{ws.failure.title}</strong>
                  <p>{ws.failure.message}</p>
                  {ws.failure.retryable ? (
                    <div className="button-row">
                      <button type="button" className="btn" onClick={ws.retryLastRun}>
                        重试
                      </button>
                    </div>
                  ) : null}
                </div>
              )}

              {/* 待作答时收起 Composer 与 SkillPicker（草稿与选择保留，不清空）。 */}
              {ws.answering ? null : (
                <div className="composer-card">
                  <form
                    className="chat-compose"
                    onSubmit={(event) => {
                      event.preventDefault();
                      ws.submitDraft();
                    }}
                  >
                    <label className="sr-only" htmlFor="consult-composer">
                      发送消息
                    </label>
                    <textarea
                      id="consult-composer"
                      rows={1}
                      value={ws.draft}
                      placeholder="写下你想补充的情况……"
                      onChange={(event) => ws.setDraft(event.target.value)}
                      aria-describedby={ws.failure === null ? undefined : 'consult-run-failure'}
                    />
                    {/*
                      发送键三态（以真实几何与禁用态区分，不靠半透明「仍可点」的错觉）：
                        1. 空草稿 —— 禁用、中性弱化（既有契约）；
                        2. 运行中 —— 禁用（本轮运行未结束，但输入框仍可先写下一句）；
                        3. 可发送 —— 品牌色实心。
                      aria-label 随状态切换，读屏听到的是「发送」/「发送中，请稍候」而非只一个图标。
                    */}
                    <button
                      className="btn btn-primary compose-send"
                      aria-label={thread.isRunning ? '发送中，请稍候' : '发送'}
                      type="submit"
                      disabled={thread.isRunning || ws.draft.trim() === ''}
                    >
                      <Icon name="send" />
                    </button>
                  </form>
                  <div className="composer-controls">
                    <SkillPicker
                      skills={ws.skills}
                      selected={ws.pendingSkill}
                      disabled={thread.isRunning}
                      onSelect={ws.selectSkill}
                    />
                    <details className="compose-help">
                      <summary>技能与应急求助</summary>
                      <p>技能只作用于下一条消息。<Link to={CONSULT_EMERGENCY_PATH} state={{ returnTo: consultChatPath(sessionId) }}>打开应急表单</Link></p>
                    </details>
                  </div>
                </div>
              )}
            </div>
          </div>
        </ConsultThreadProvider>
      </AssistantRuntimeProvider>
    </DeviceFrame>
  );
}
