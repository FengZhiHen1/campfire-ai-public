/**
 * 模块: features/consult/view/ChatWorkspace
 * 职责: 对话工作面——消息流、状态条、候选轻提示、输入区（含待作答时的收起）
 * 数据来源:
 *   - docs/design/pages/对话页.md: MUST — 布局结构、状态覆盖表、输入区互斥、
 *     响应式与平台（平板/PC 经手机蒙版渲染，蒙版体验无损）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 3 节（状态条/发送禁用）、第 7 节（失败语义）
 * 边界:
 *   - 依赖: shared/ui/DeviceFrame、viewModel 的 useConsultRuntime 与 runStore、MessageParts、SkillPicker、react-router
 *   - 被依赖: view 的 ChatPage
 * 禁止行为:
 *   - 禁止把 reasoning 渲染进正文（思考只经 ReasoningDisclosure）
 *   - 禁止在待作答时恢复输入区（提交或问题组移除后才恢复，页面设计布局结构第 3 节）
 *   - 禁止用「未找到相关内容」这类文案（不变量 2）
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router';
import {
  AssistantRuntimeProvider,
  MessagePrimitive,
  ThreadPrimitive,
  type ThreadMessage,
} from '@assistant-ui/react';

import { Icon } from '../../../shared/ui/Icon';
import { BrandMark } from '../../../shared/ui/BrandMark';
import { DeviceFrame } from '../../../shared/ui/DeviceFrame';
import type { ConsultPort } from '../application/ports';
import { skillLabel, EMERGENCY_SKILL_ID } from '../domain/skills';
import { PROGRESS_TEXT } from '../domain/types';
import { SkillPicker } from './SkillPicker';
import { ConsultThreadProvider, CONSULT_MESSAGE_COMPONENTS } from './MessageParts/parts';
import { useConsultRuntime } from '../viewModel/useConsultRuntime';
import { useRunStore } from '../viewModel/runStore';
import styles from './chatPage.module.css';

/** 使用者消息里的 text part 直接内联渲染（气泡不支持块级段落，见 chatPage.module.css 说明）。 */
const USER_MESSAGE_COMPONENTS = {
  Text: ({ text }: { text: string }) => <>{text}</>,
} as const;

/**
 * 页头技能标签的折叠阈值（自几个起整体折叠为「技能 N 个」）。
 *
 * 取 4 的依据是 390 宽页头的实测（对话页设计布局结构第 1 条的阈值表）：
 * 3 个中文标签合计 199.45px，标题仍余 64.39px（宽度够用）；第 4 个起标题宽归零
 * （合计 265.94px，scrollWidth 56 > clientWidth 0）；第 5 个起标签越过页头右边界，
 * 文档级横向溢出（合计 332.42px，documentElement.scrollWidth 390 涨到 464）。
 *
 * 为什么按数量而不是按宽度实测：判据要与测试环境一致。实测 jsdom 不做布局
 * （clientWidth / scrollWidth / getBoundingClientRect 全为 0），且不实现 ResizeObserver
 * ——按宽度判的阈值在单测里恒不触发，那条逻辑就没有任何测试能覆盖它。
 * 因此把「宽度不足」近似为「标签数达到实测的第一个宽度不足点」，并在浏览器探针里
 * 复核真实溢出数字（见交付证据）。
 */
const SKILL_TAG_COLLAPSE_THRESHOLD = 4;

/** 取消息流里最后一张行动卡的 id（重复评估后旧卡据此标失效）。 */
export function newestActionCardId(messages: readonly ThreadMessage[]): string | null {
  let newest: string | null = null;
  for (const message of messages) {
    if (message.role !== 'assistant') continue;
    for (const part of message.content) {
      if (part.type === 'data' && part.name === 'action-card') {
        const data = part.data as { card_id?: unknown };
        if (typeof data.card_id === 'string') newest = data.card_id;
      }
    }
  }
  return newest;
}

/** 取最后一条使用者消息的 id（重试的起点）。 */
function lastUserIdOf(messages: readonly ThreadMessage[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message !== undefined && message.role === 'user') return message.id;
  }
  return null;
}

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
          <MessagePrimitive.Parts components={CONSULT_MESSAGE_COMPONENTS} />
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
  initialMessages: Parameters<typeof useConsultRuntime>[0]['initialMessages'];
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
 *
 * 为什么不在本页加 `.phone-shell` 类
 *
 * `.phone-shell` 自带外边距、内边距、`gap` 与 `box-shadow`，且 `.phone-shell .subpage-head`
 * 会取消页头那份左右内边距——四条副作用都会改变窄视口下的既有版式。改为按需补内边距：
 * 页头的基础规则本就自带一份（components.css），消息流与输入区由 chatPage.module.css 的
 * ≥560px 媒体查询补一份；窄视口两处都不生效，版式逐像素不变。
 */
export function ChatWorkspace({ sessionId, initialMessages, initialDraft = '', consult }: ChatWorkspaceProps) {
  const { runtime, thread, send, stop, sendAnswers } = useConsultRuntime({ sessionId, initialMessages, consult });
  const store = useRunStore();
  const [draft, setDraft] = useState(initialDraft);
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    if (initialDraft !== '') void navigate(location.pathname + location.search, { replace: true, state: null });
  }, [initialDraft, location.pathname, location.search, navigate]);
  // 并发闸门（FE-12）：发送按钮的 disabled 之外还有 Enter 键与程序化路径。
  const sending = useRef(false);

  const newestCardId = useMemo(() => newestActionCardId(thread.messages), [thread.messages]);
  /*
    思考行的两个呈现开关在这里取值后经上下文下发（原来由每个思考 part 各自订阅 store）。
    取值语义与原实现逐字一致：subscribing 也算流式（首个 token 到达前已在运行）。
  */
  const reasoningStreaming = store.connection === 'streaming' || store.connection === 'subscribing';
  const reasoningEmergency = store.activeSkills.includes(EMERGENCY_SKILL_ID);
  const threadContext = useMemo(
    () => ({ submitAnswers: sendAnswers, newestActionCardId: newestCardId, reasoningStreaming, reasoningEmergency }),
    [sendAnswers, newestCardId, reasoningStreaming, reasoningEmergency],
  );

  const activeSkillLabels = useMemo(
    () => store.activeSkills.map((id) => skillLabel(store.skills, id)).filter((label): label is string => label !== null),
    [store.activeSkills, store.skills],
  );

  const submitDraft = (): void => {
    if (sending.current) return;
    const content = draft.trim();
    if (content === '') return;
    sending.current = true;
    try {
      send(content);
      setDraft('');
    } finally {
      sending.current = false;
    }
  };

  /**
   * 重试：从最后一条使用者消息重跑一次（失败时使用者消息已留在消息流里，
   * 发送失败与运行失败都走这条路）。
   */
  const retryLastRun = (): void => {
    const lastUser = lastUserIdOf(thread.messages);
    if (lastUser === null) return;
    useRunStore.getState().setFailure(null);
    useRunStore.getState().setConnection('subscribing');
    runtime.thread.startRun({ parentId: lastUser });
  };

  const answering = store.activeBatchId !== null;
  const statusText = answering
    ? '请先处理上面的问题'
    : store.connection === 'reconnecting'
      ? PROGRESS_TEXT.reconnecting
      : store.slowRun
        ? PROGRESS_TEXT.emergencySlow
        : store.progressText;

  return (
    <DeviceFrame>
      <AssistantRuntimeProvider runtime={runtime}>
        <ConsultThreadProvider value={threadContext}>
          <div className={styles.workspace}>
            <header className="subpage-head">
              <Link className="sp-back" to="/consult">
                ← 返回
              </Link>
              <span className="sp-title">咨询</span>
              {/*
                宽度不足时整体折叠为一个汇总标签，而不是「前 N 个 + +N 徽标」——
                授权语义明确否定了徽标形态（对话页设计文档的布局结构第 1 条）。
                判据与阈值见 SKILL_TAG_COLLAPSE_THRESHOLD 的说明。
              */}
              {activeSkillLabels.length === 0
                ? null
                : activeSkillLabels.length >= SKILL_TAG_COLLAPSE_THRESHOLD
                  ? (
                      <span className="tag meta sp-tag">{`技能 ${String(activeSkillLabels.length)} 个`}</span>
                    )
                  : activeSkillLabels.map((label) => (
                      <span key={label} className="tag meta sp-tag">
                        {label}
                      </span>
                    ))}
            </header>

            {store.candidates.length === 0 ? null : (
              <details className="candidate-toast chat-candidate">
                <summary>
                  <span>有 {store.candidates.length} 条待确认</span>
                  <span className="toggle-label">
                    <span className="when-closed">预览</span>
                    <span className="when-open">收起</span>
                  </span>
                </summary>
                <div className="ct-panel">
                  {store.candidates.map((candidate) => (
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
                    <button className="btn btn-secondary" type="button" onClick={() => setDraft('我想聊聊最近发生的一件事。')}>聊聊最近发生的事</button>
                    <button className="btn btn-secondary" type="button" onClick={() => setDraft('我想一起准备下一次外出。')}>一起准备下一次外出</button>
                  </div>
                </section>
              )}
              <ThreadPrimitive.Root>
                <ThreadPrimitive.Viewport>
                  <ThreadPrimitive.Messages>{() => <MessageRow />}</ThreadPrimitive.Messages>
                </ThreadPrimitive.Viewport>
              </ThreadPrimitive.Root>
              {store.interrupted ? <p className="status off">{PROGRESS_TEXT.interrupted}</p> : null}
            </div>

            <div className={styles.footer}>
              {statusText === null ? null : (
                <div className="chat-progress">
                  {store.connection === 'reconnecting' || store.progressText !== null ? (
                    <span className="flame-dot breathing" aria-hidden="true" />
                  ) : null}
                  <span role="status" aria-live="polite">
                    {statusText}
                  </span>
                </div>
              )}

              {store.failure === null ? null : (
                <div className="error-card" role="alert">
                  <strong className="ec-title">{store.failure.title}</strong>
                  <p>{store.failure.message}</p>
                  {store.failure.retryable ? (
                    <div className="button-row">
                      <button type="button" className="btn" onClick={retryLastRun}>
                        重试
                      </button>
                    </div>
                  ) : null}
                </div>
              )}

              {thread.isRunning ? (
                <div className="button-row">
                  <button type="button" className="btn btn-quiet" onClick={stop}>
                    停止
                  </button>
                </div>
              ) : null}

              {/* 待作答时收起 Composer 与 SkillPicker（草稿与选择保留，不清空）。 */}
              {answering ? null : (
                <>
                  <SkillPicker
                    skills={store.skills}
                    selected={store.pendingSkill}
                    disabled={thread.isRunning}
                    onSelect={(skillId) => useRunStore.getState().selectSkill(skillId)}
                  />
                  <form
                    className="chat-compose"
                    onSubmit={(event) => {
                      event.preventDefault();
                      submitDraft();
                    }}
                  >
                    <label className="sr-only" htmlFor="consult-composer">
                      发送消息
                    </label>
                    <textarea
                      id="consult-composer"
                      rows={1}
                      value={draft}
                      placeholder="写下你想补充的情况……"
                      onChange={(event) => setDraft(event.target.value)}
                    />
                    <button className="btn btn-primary compose-send" aria-label="发送" type="submit" disabled={thread.isRunning || draft.trim() === ''}>
                      <Icon name="send" />
                    </button>
                  </form>
                  <details className="compose-help"><summary>关于技能与应急求助</summary><p className="meta">技能只作用于下一条消息；应急求助请返回首页走应急入口。</p></details>
                </>
              )}
            </div>
          </div>
        </ConsultThreadProvider>
      </AssistantRuntimeProvider>
    </DeviceFrame>
  );
}
