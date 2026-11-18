/**
 * 模块: features/memory/view/MemoryPage
 * 职责: 记忆页（设置页下的次级页）——归属说明、按日期倒序的时间线、纠正与删除
 * 数据来源:
 *   - docs/design/pages/记忆页.md: MUST — 全文（放置、布局、状态覆盖、动效与 token）
 *   - docs/design/components.html: MUST — .subpage-head/.list-row/.group-collapse/.confirm-sheet
 * 边界:
 *   - 依赖: features/memory/viewModel、shared/ui、react-router
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止渲染 tab 栏（次级页）
 *   - 禁止出现支持对象切换器（记忆属账号、不随对象分区——切换器的缺席本身在传达归属）
 *   - 禁止使用 accent（本页是工具页，纠正走 secondary；页面设计 token 使用节）
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { AppShell } from '../../../shared/ui/AppShell';
import { BackLink } from '../../../shared/ui/BackLink';
import { ConfirmSheet } from '../../../shared/ui/ConfirmSheet';
import { ListTail } from '../../../shared/ui/ListTail';
import { EmptyState, ErrorCard, Skeleton } from '../../../shared/ui/StatePrimitives';
import type { MemoryPort } from '../application/ports';
import { dateHeading, groupByDate, occurredAtLabel, sourceLabel } from '../domain/episodes';
import { isRetryable, memoryFailureDescription, memoryFailureTitle } from '../domain/failures';
import { useMemoryPage } from '../viewModel/useMemoryPage';
import styles from './memoryPage.module.css';

/** 页面文案（页面设计「数据与文案」与状态覆盖表的成稿，逐字呈现）。 */
const COPY = {
  title: '我提过的事',
  ownership: '这些是你自己在咨询中说过或经历过的事，关于你本人；与支持对象的档案分开保存，不随切换对象变化。',
  emptyTitle: '还没有记录',
  emptyDescription: '你在咨询中说过的事，会记在这里',
  retry: '重试',
  correct: '纠正',
  delete: '删除',
  deleteSheetTitle: '删除这条记录？',
  deleteSheetBody: '删除后咨询和历史都不会再用到它',
  deleteConfirm: '删除',
  cancel: '取消',
  correctionTitle: '新增一条更正',
  correctionBody: '更正会新增一条，原记录不再作为依据',
  contentLabel: '内容',
  occurredAtLabel: '发生时间',
  submitCorrection: '更正',
  submitting: '正在提交…',
  expand: '看完整内容',
  collapse: '收起',
  loadMore: '加载更多',
  loadingMore: '正在加载…',
  loadingMoreLabel: '正在加载更多',
} as const;

/** 记忆页 props：端口经 props 注入。 */
export interface MemoryPageProps {
  /** 记忆端口。 */
  port: MemoryPort;
}

/**
 * 渲染记忆页。
 *
 * 前置: port 已装配
 * 后置: 输出次级页头、归属说明行与时间线；空态与失败态可区分
 * 异常: 无（端口异常在 hook 内分类成状态）
 */
export function MemoryPage({ port }: MemoryPageProps) {
  const page = useMemoryPage(port);
  const correctionHeading = useRef<HTMLHeadingElement>(null);
  const correcting = page.correction !== null;
  useEffect(() => {
    if (!correcting) return;
    correctionHeading.current?.scrollIntoView?.({ block: 'start' });
    correctionHeading.current?.focus({ preventScroll: true });
  }, [correcting]);
  // 纠正成功后的落点：新条目落到它自己的日期位置，原行已消失。刷新后把新行滚进视野并聚焦，
  // 让「结果落在哪」当场可读；只在该条目确实出现在当前列表里时执行。
  // 依赖 page.items：新行是在 loadFirstPage 更新 items 之后才出现的，因此必须随 items 变化再跑一次。
  const correctedFocus = page.correctedFocus;
  const itemCount = page.items.length;
  useEffect(() => {
    if (correctedFocus === null || itemCount === 0) return;
    const row = document.querySelector<HTMLElement>(`[data-episode-key="${correctedFocus}"]`);
    if (row === null) return;
    row.scrollIntoView?.({ block: 'center' });
    row.focus({ preventScroll: true });
  }, [correctedFocus, itemCount]);
  // 展开的行（默认两行截断；核对场景不得因截断丢信息，展开可见完整原文）。
  const [expanded, toggleExpanded] = useExpanded();

  return (
    <AppShell>
      <header className="subpage-head">
        {/*
          固定回「我的」而不是浏览器历史上一页：记忆页是从设置页进入的次级页，
          但同一路径也可能在别的上下文里打开（例如纠正后返回），用历史反回会落到
          一个与「我提过的事」无关的页面。direct 让落点始终是入口本身。
        */}
        <BackLink direct fallback="/settings" />
        <span className="sp-title">{COPY.title}</span>
      </header>

      {/* 归属说明行：回答本页最容易被误解的一件事（记忆与档案的归属不同）。 */}
      <p className={styles.ownership}>{COPY.ownership}</p>

      {/* 纠正结果提示是页面级状态而不是列表级：中间态下旧记录已从列表移除，
       * 若把它放进「有条目」分支里，唯一那条被移除后提示会跟着消失——
       * 而「原记录已不再作为依据」正是使用者此刻最需要看到的信息。
       * 中间态（只撤下、没写成）是「部分成功」，必须与成功、与读取失败三者可区分：
       * 它不是成功（新记录没写成），也不是单纯的失败（旧记录确实已撤下），
       * 因此用独立的重音块承担，不用 hint 的轻提示形态。 */}
      {page.notice !== null && (
        <p
          className={page.notice.kind === 'written' ? 'hint' : 'field-error'}
          role={page.notice.kind === 'written' ? 'status' : 'alert'}
        >
          {page.notice.text}{' '}
          <button className="text-button" onClick={page.dismissNotice} type="button">
            知道了
          </button>
        </p>
      )}

      {page.status === 'error' && page.failure !== null && (
        <ErrorCard
          actions={
            isRetryable(page.failure) ? (
              <button
                className="btn btn-secondary"
                onClick={() => {
                  void page.retry();
                }}
                type="button"
              >
                {COPY.retry}
              </button>
            ) : undefined
          }
          description={memoryFailureDescription(page.failure)}
          title={memoryFailureTitle(page.failure)}
        />
      )}

      {page.status === 'loading' && <Skeleton rows={4} />}

      {page.status === 'ready' && page.items.length === 0 && (
        // 空态不放「去做咨询」的引导（本页不是获客位，记忆页第 58 行）。
        <EmptyState description={COPY.emptyDescription} title={COPY.emptyTitle} />
      )}

      {page.status === 'ready' && page.items.length > 0 && (
        <>
          {groupByDate(page.items).map((group) => (
            <details className={"tile group-collapse " + styles.dateGroup} key={group.key} open>
              <summary>
                {dateHeading(group.key)}（{group.items.length}）
              </summary>
              <div className="gc-body">
                {group.items.map((episode) => {
                  const isExpanded = expanded.includes(episode.episode_key);
                  return (
                    <article className={`list-row ${styles.episode}`} key={episode.episode_key} data-episode-key={episode.episode_key} tabIndex={-1}>
                      <div className={styles.episodeHead}>
                        <strong className={`lr-title ${isExpanded ? styles.fullContent : styles.title}`}>{episode.content}</strong>
                        <p className={`lr-meta ${styles.episodeMeta}`}>
                          {occurredAtLabel(episode.occurred_at)} · {sourceLabel()}
                        </p>
                        <button
                          className={`text-button ${styles.toggle}`}
                          aria-expanded={isExpanded}
                          onClick={() => {
                            toggleExpanded(episode.episode_key);
                          }}
                          type="button"
                        >
                          {isExpanded ? COPY.collapse : COPY.expand}
                        </button>
                      </div>
                      <div className="lr-actions">
                        <button
                          className="btn btn-secondary"
                          onClick={() => {
                            page.openCorrection(episode);
                          }}
                          type="button"
                        >
                          {COPY.correct}
                        </button>
                        <button
                          className="btn btn-quiet"
                          disabled={page.deletingId === episode.episode_key}
                          onClick={() => {
                            page.askDelete(episode);
                          }}
                          type="button"
                        >
                          {COPY.delete}
                        </button>
                      </div>
                      {/* 行内错误只属于删除失败：它按条目键归属，因此只在这一行渲染。
                       * 触底分页失败没有对应的行，走尾部的错误卡（见下）。 */}
                      {page.rowFailure !== null && page.rowFailure.episodeKey === episode.episode_key && (
                        <p className="field-error" role="alert">
                          {page.rowFailure.failure.kind === 'unknown'
                            ? '这条记录没有删除成功，请重试'
                            : memoryFailureTitle(page.rowFailure.failure)}
                        </p>
                      )}
                    </article>
                  );
                })}
              </div>
            </details>
          ))}

          {page.correction !== null && (
            <section className="tile stack" aria-labelledby="memory-correction-title">
              <h2 id="memory-correction-title" ref={correctionHeading} tabIndex={-1}>{COPY.correctionTitle}</h2>
              <p className="hint">{COPY.correctionBody}</p>
              <label className="field">
                <span>{COPY.occurredAtLabel}</span>
                <input
                  aria-invalid={page.correction.errors.occurredAt !== undefined}
                  onChange={(event) => {
                    page.updateCorrectionDraft({ occurredAtLocal: event.target.value });
                  }}
                  type="datetime-local"
                  value={page.correction.draft.occurredAtLocal}
                />
              </label>
              {page.correction.errors.occurredAt !== undefined && (
                <p className="field-error">{page.correction.errors.occurredAt}</p>
              )}
              <label className="field">
                <span>{COPY.contentLabel}</span>
                <textarea
                  aria-invalid={page.correction.errors.content !== undefined}
                  onChange={(event) => {
                    page.updateCorrectionDraft({ content: event.target.value });
                  }}
                  rows={4}
                  value={page.correction.draft.content}
                />
              </label>
              {page.correction.errors.content !== undefined && (
                <p className="field-error">{page.correction.errors.content}</p>
              )}
              {page.correction.failure !== null && (
                <p className="field-error" role="alert">
                  {memoryFailureTitle(page.correction.failure)}
                </p>
              )}
              <div className="button-row">
                <button className="btn btn-quiet" disabled={page.correction.submitting} onClick={page.closeCorrection} type="button">
                  {COPY.cancel}
                </button>
                <button
                  className="btn btn-secondary"
                  disabled={page.correction.submitting}
                  onClick={() => {
                    void page.submitCorrection();
                  }}
                  type="button"
                >
                  {page.correction.submitting ? COPY.submitting : COPY.submitCorrection}
                </button>
              </div>
            </section>
          )}

          {/* 尾部只有一种形态：还有下一页时给加载入口，失败时给错误卡 + 重试。
           * 触底失败曾经被写进行内错误（空键占位），而渲染条件要求键匹配真实条目，
           * 于是失败在界面上零反馈——这条路径必须可见（禁止静默兜底）。 */}
          {page.loadMoreFailure !== null ? (
            <ErrorCard
              actions={
                isRetryable(page.loadMoreFailure) ? (
                  <button
                    className="btn btn-secondary"
                    onClick={() => {
                      void page.loadMore();
                    }}
                    type="button"
                  >
                    {COPY.retry}
                  </button>
                ) : undefined
              }
              description={memoryFailureDescription(page.loadMoreFailure)}
              title={memoryFailureTitle(page.loadMoreFailure)}
            />
          ) : (
            page.hasMore && (
              <ListTail
                loading={page.loadingMore}
                loadingLabel={COPY.loadingMoreLabel}
                loadMoreLabel={COPY.loadMore}
                onReachEnd={page.loadMore}
              />
            )
          )}
        </>
      )}

      {page.deleteTarget !== null && (
        <ConfirmSheet labelledBy="memory-delete-title" onDismiss={page.cancelDelete}>
          <h2 id="memory-delete-title">{COPY.deleteSheetTitle}</h2>
          <p>{COPY.deleteSheetBody}</p>
          <div className="button-row">
            <button className="btn btn-quiet" onClick={page.cancelDelete} type="button">
              {COPY.cancel}
            </button>
            <button
              className="btn btn-danger"
              onClick={() => {
                void page.confirmDelete();
              }}
              type="button"
            >
              {COPY.deleteConfirm}
            </button>
          </div>
        </ConfirmSheet>
      )}
    </AppShell>
  );
}

/** 展开行状态的小 hook（页面内视觉状态归 view）。 */
function useExpanded(): [readonly string[], (key: string) => void] {
  const [keys, setKeys] = useState<readonly string[]>([]);
  const toggle = useCallback((key: string): void => {
    setKeys((current) => (current.includes(key) ? current.filter((item) => item !== key) : [...current, key]));
  }, []);
  return [keys, toggle];
}
