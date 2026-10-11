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
  const { hydration, retry } = useConsultSession(sessionId, consult);

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
    // key 绑定会话 id：切换会话时重建 runtime，避免上一条对话的消息留在新会话里。
    <ChatWorkspace key={sessionId} sessionId={sessionId} initialMessages={hydration.messages} initialDraft={initialDraft} consult={consult} />
  );
}
