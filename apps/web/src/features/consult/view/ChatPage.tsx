/**
 * 模块: features/consult/view/ChatPage
 * 职责: 对话页容器——历史水合的三态（骨架 / 就绪 / 错误 + 重试）与工作面挂载
 * 数据来源:
 *   - docs/design/pages/对话页.md: MUST — 状态覆盖表（历史水合 loading/error、401）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 4.1 节（对话 id 在 URL）、第 4.4 节（水合失败不显示空对话）
 * 边界:
 *   - 依赖: shared/ui（AppShell、Skeleton、ErrorCard）、viewModel/useConsultSession、view/ChatWorkspace
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止在水合失败或未完成时挂载工作面（会显示空对话冒充成功）
 *   - 禁止在此直接调 HTTP（端口由路由注入）
 */

import { useEffect, useState } from 'react';
import { useLocation, useParams } from 'react-router';

import { AppShell } from '../../../shared/ui/AppShell';
import { BackLink } from '../../../shared/ui/BackLink';
import { ErrorCard } from '../../../shared/ui/StatePrimitives';
import type { ConsultPort } from '../application/ports';
import { useConsultSession } from '../viewModel/useConsultSession';
import { ChatWorkspace } from './ChatWorkspace';
import styles from './chatPage.module.css';
// 对话面的契约组件样式（.bubble-user/.msg-doc/.question-card/.action-card…）是全局类名表：
// 它必须由消费它的页面模块 import 才会进产物，漏了它对话面的组件全部退化为浏览器默认外观。
import './consultComponents.css';

/** 对话页 props。 */
export interface ChatPageProps {
  consult: ConsultPort;
}

/**
 * 渲染对话页。
 *
 * 前置: 路由参数含 sessionId（app/routes 的路由表保证）
 * 后置: 水合中就绪后挂载工作面；水合失败显示错误与重试，不显示空对话
 * 异常: 无
 */
export function ChatPage({ consult }: ChatPageProps) {
  const location = useLocation();
  const state: unknown = location.state;
  const initialDraft =
    typeof state === 'object' && state !== null && 'draft' in state && typeof state.draft === 'string'
      ? state.draft
      : '';
  const params = useParams<{ sessionId: string }>();
  const sessionId = params.sessionId ?? '';
  const { hydration, retry, revision } = useConsultSession(sessionId, consult);

  /**
   * 引导是否仍待处理 —— 决定页头是否给「跳过引导」。
   *
   * 为什么还要 `sessionStorage`：`onboarding_pending` 只在**建会话的响应**里出现，刷新之后就没了。
   * 只靠路由 state 的话，使用者刷新一次就再也找不到跳过入口，而引导此时仍会继续注入
   * （`campfire_onboarding` 状态还是 in_progress）——那正是「引导不可跳过」（`RQ-ACC-02`）的形态。
   * 记住的只是「这个会话创建时引导待注入」这一个布尔事实，不含任何内容；跳过或引导完成后即清除
   * （`onGuideSettled`）。它按会话 id 分键，不会串到别的会话上。
   */
  const guideKey = `consult.guidePending.${sessionId}`;
  const guideFlagFromState =
    typeof state === 'object' && state !== null && 'guidePending' in state && state.guidePending === true;
  /**
   * 初值在 `useState` 的惰性初始化里取，**不在 effect 里 setState**：
   * effect 里同步 setState 会多一轮渲染，而且这条判据没有「异步才知道」的成分——
   * 路由 state 与 sessionStorage 都是同步可读的。
   */
  const [guidePending, setGuidePending] = useState(() => {
    if (guideFlagFromState) return true;
    try {
      return window.sessionStorage.getItem(guideKey) === '1';
    } catch {
      // 隐私模式/禁用存储：退化为「只信路由 state」，不阻断页面（跳过是便利功能，不是安全边界）。
      return false;
    }
  });
  // 只做**副作用**（把这次的事实记下来），不在这里改 React 状态。
  useEffect(() => {
    if (!guideFlagFromState) return;
    try {
      window.sessionStorage.setItem(guideKey, '1');
    } catch {
      // 同上：存储不可用时无副作用可做。
    }
  }, [guideKey, guideFlagFromState]);

  const settleGuide = (): void => {
    try {
      window.sessionStorage.removeItem(guideKey);
    } catch {
      // 同上：存储不可用时无副作用可清。
    }
    setGuidePending(false);
  };

  if (hydration.status === 'loading') {
    return (
      <AppShell>
        <div className={styles.workspace}>
          <header className="subpage-head">
            <BackLink fallback="/consult" />
            <span className="sp-title">咨询</span>
          </header>
          <div className={styles.thread}>
            {/* 骨架与真实消息同形：先是使用者气泡，再是助手正文块（对话页状态覆盖表）。 */}
            <div className="stack" aria-hidden="true">
              <div className="bubble-user skeleton bubble" />
              <div className="skeleton doc" />
              <div className="bubble-user skeleton bubble" />
              <div className="skeleton doc" />
            </div>
            <p className="run-status" role="status">
              正在载入这段对话…
            </p>
          </div>
        </div>
      </AppShell>
    );
  }

  if (hydration.status === 'error') {
    return (
      <AppShell>
        <div className={styles.workspace}>
          <header className="subpage-head">
            <BackLink fallback="/consult" />
            <span className="sp-title">咨询</span>
          </header>
          <div className={styles.thread}>
            <ErrorCard
              title={hydration.failure.title}
              description={hydration.failure.message}
              actions={
                <div className="button-row">
                  <button type="button" className="btn" onClick={retry}>
                    重试
                  </button>
                </div>
              }
            />
          </div>
        </div>
      </AppShell>
    );
  }

  return (
    // key 绑定「会话 id + 第几次水合」：切换会话、以及订阅不可续传后重新读历史时都重建 runtime，
    // 避免上一条对话（或本次已废弃的 partial）留在界面上。
    <ChatWorkspace
      key={`${sessionId}#${String(revision)}`}
      sessionId={sessionId}
      initialMessages={hydration.messages}
      initialDraft={initialDraft}
      consult={consult}
      onNeedsResync={retry}
      guidePending={guidePending}
      onGuideSettled={settleGuide}
    />
  );
}
