/**
 * 模块: features/consult/view/ChatWorkspace
 * 职责: 对话工作面——消息流、状态条、候选轻提示、输入区（含待作答时的收起）
 * 数据来源:
 *   - docs/design/pages/对话页.md: MUST — 布局结构、状态覆盖表、输入区互斥
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 3 节（状态条/发送禁用）、第 7 节（失败语义）
 * 边界:
 *   - 依赖: viewModel 的 useConsultRuntime 与 runStore、MessageParts、SkillPicker、react-router
 *   - 被依赖: view 的 ChatPage
 * 禁止行为:
 *   - 禁止把 reasoning 渲染进正文（思考只经 ReasoningDisclosure）
 *   - 禁止在待作答时恢复输入区（提交或问题组移除后才恢复，页面设计布局结构第 3 节）
 *   - 禁止用「未找到相关内容」这类文案（不变量 2）
 */

import { useMemo, useRef, useState } from 'react';
import { Link } from 'react-router';
import {
  AssistantRuntimeProvider,
  MessagePrimitive,
  ThreadPrimitive,
  type ThreadMessage,
} from '@assistant-ui/react';

import type { ConsultPort } from '../application/ports';
import { skillLabel } from '../domain/skills';
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
  sessionId: string;
  /** 水合得到的初始消息。 */
  initialMessages: Parameters<typeof useConsultRuntime>[0]['initialMessages'];
  consult: ConsultPort;
}

/**
 * 渲染对话工作面。
 *
 * 前置: 历史水合已完成（loading/error 由 ChatPage 处置）
 * 后置: 输出消息流、状态条、候选轻提示与输入区；待作答时收起输入区
 * 异常: 无
 */
export function ChatWorkspace({ sessionId, initialMessages, consult }: ChatWorkspaceProps) {
  const { runtime, thread, send, stop, sendAnswers } = useConsultRuntime({ sessionId, initialMessages, consult });
  const store = useRunStore();
  const [draft, setDraft] = useState('');
  // 并发闸门（FE-12）：发送按钮的 disabled 之外还有 Enter 键与程序化路径。
  const sending = useRef(false);

  const newestCardId = useMemo(() => newestActionCardId(thread.messages), [thread.messages]);
  const threadContext = useMemo(
    () => ({ submitAnswers: sendAnswers, newestActionCardId: newestCardId }),
    [sendAnswers, newestCardId],
  );

  const activeSkillLabel = useMemo(() => skillLabel(store.skills, store.activeSkill), [store.activeSkill, store.skills]);

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
    <AssistantRuntimeProvider runtime={runtime}>
      <ConsultThreadProvider value={threadContext}>
        <div className={styles.workspace}>
          <header className="subpage-head">
            <Link className="sp-back" to="/consult">
              ← 返回
            </Link>
            <span className="sp-title">咨询</span>
            {activeSkillLabel === null ? null : <span className="tag meta sp-tag">{activeSkillLabel}</span>}
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
                  <button className="btn btn-primary" type="submit" disabled={thread.isRunning || draft.trim() === ''}>
                    发送
                  </button>
                </form>
                <p className="meta">技能只作用于下一条消息，发送后回归「自动」。</p>
              </>
            )}
          </div>
        </div>
      </ConsultThreadProvider>
    </AssistantRuntimeProvider>
  );
}
