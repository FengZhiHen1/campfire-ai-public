/**
 * 模块: features/consult/view/ConsultListPage
 * 职责: 会话列表页——新对话入口、历史会话行与触底加载
 * 数据来源:
 *   - docs/design/pages/会话列表页.md: MUST — 全文（布局结构、组件选用、状态覆盖表）
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 3.1/3.2 节（新会话与列表端点）
 * 边界:
 *   - 依赖: shared/ui（AppShell、EmptyState、ErrorCard、Skeleton）、viewModel/useSessionList
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止发明契约未定义的列表字段（四个字段即端点形状）
 *   - 禁止把「加载失败」呈现成空列表（新对话入口在错误态仍可用）
 */

import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';

import { Icon } from '../../../shared/ui/Icon';
import { AppShell } from '../../../shared/ui/AppShell';
import { EmptyState, ErrorCard, Skeleton } from '../../../shared/ui/StatePrimitives';
import type { ConsultPort } from '../application/ports';
import { useSessionList } from '../viewModel/useSessionList';
import { consultChatPath } from './consultRoutes';
import styles from './consultListPage.module.css';

/** 会话列表页 props。 */
export interface ConsultListPageProps {
  consult: ConsultPort;
}

/**
 * 渲染会话列表页。
 *
 * 前置: 无
 * 后置: 输出新对话入口、会话行列表与分页加载；三态各自显式
 * 异常: 无
 */
export function ConsultListPage({ consult }: ConsultListPageProps) {
  const navigate = useNavigate();
  const list = useSessionList(consult, (sessionId, onboardingPending) => {
    navigate(consultChatPath(sessionId), { state: { guidePending: onboardingPending } });
  });
  const sentinel = useRef<HTMLDivElement | null>(null);

  // 触底自动加载：哨兵进入视口即请求下一页（页面设计「推荐自动 + 触底呼吸点」）。
  useEffect(() => {
    const node = sentinel.current;
    if (node === null || list.state.status !== 'ready' || list.state.nextCursor === null) return;
    if (typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) list.loadMore();
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [list]);

  return (
    <AppShell tab="consult">
      <header className="page-head">
        <div><h1>咨询</h1><p className="hint">开始新的对话，或接着上次的思路。</p></div>
      </header>

      <button type="button" className={`tile ${styles.newEntry}`} disabled={list.creating} onClick={() => void list.startNewConversation()}>
        <span className={styles.newIcon}><Icon name="plus" /></span>
        <strong className={styles.newTitle}>{list.creating ? '正在创建…' : '开始新的日常咨询'}</strong>
        <span className={styles.newBody}>说说正在准备、正在经历或刚发生的事</span>
      </button>
      {list.createFailure === null ? null : (
        <div className="error-card" role="alert">
          <strong className="ec-title">{list.createFailure.title}</strong>
          <p>{list.createFailure.message}</p>
        </div>
      )}

      {list.state.status === 'loading' ? <Skeleton rows={4} /> : null}

      {list.state.status === 'error' ? (
        <ErrorCard
          title={list.state.failure.title}
          description={list.state.failure.message}
          actions={
            <div className="button-row">
              <button type="button" className="btn" onClick={list.reload}>
                重试
              </button>
            </div>
          }
        />
      ) : null}

      {list.state.status === 'ready' && list.state.rows.length === 0 ? (
        <EmptyState title="还没有咨询记录" description="从上面开始第一次咨询" />
      ) : null}

      {list.state.status === 'ready' && list.state.rows.length > 0 ? (
        <section aria-label="咨询记录"><p className="eyebrow">之前的咨询</p><div className={styles.rows}>
          {list.state.rows.map((row) => (
            <button
              type="button"
              className={`list-row ${styles.row}`}
              key={row.sessionId}
              onClick={() => navigate(consultChatPath(row.sessionId))}
            >
              <strong className="lr-title">{row.title}</strong>
              <span className="lr-sub">
                {row.relativeTime}
                {row.supportObjectName === null ? '' : ` · ${row.supportObjectName}`}
              </span>
              {row.preview === null ? null : <span className="lr-meta">{row.preview}</span>}
            </button>
          ))}
        </div></section>
      ) : null}

      <div ref={sentinel} className={styles.sentinel} aria-hidden="true" />
      {list.state.status === 'ready' && list.state.loadingMore ? (
        <p className="meta" role="status">
          正在加载更早的会话…
        </p>
      ) : null}
    </AppShell>
  );
}
