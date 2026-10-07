/**
 * 模块: features/library/view/LibraryPage
 * 职责: 案例库浏览页——库别切换、检索、就地展开、触底分页与 deep-link 三态
 * 数据来源:
 *   - docs/design/pages/案例库浏览页.md: MUST — 全文（布局、状态覆盖、动效与 token）
 *   - docs/design/components.html: MUST — .subpage-head/.field/.tag.selected/.list-row/.status.off
 * 边界:
 *   - 依赖: features/library/viewModel、shared/ui、react-router
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止编造「热门」排序（无真实行为数据前只用时间序）
 *   - 禁止把检索失败呈现成「没有找到相关内容」
 *   - 禁止在已撤下的来源上显示正文
 */

import { Link, useLocation } from 'react-router';

import type { LibraryListItem, LibraryItem } from '../../../shared/types/library';
import { AppShell } from '../../../shared/ui/AppShell';
import { ListTail } from '../../../shared/ui/ListTail';
import { EmptyState, ErrorCard, Skeleton } from '../../../shared/ui/StatePrimitives';
import type { LibraryPort } from '../application/ports';
import { emptyStateKind, libraryFailureDescription, libraryFailureTitle } from '../domain/failures';
import { isFictional, itemMetaParts, riskClassLabel, statusLabel } from '../domain/labels';
import { useLibraryPage } from '../viewModel/useLibraryPage';
import styles from './libraryPage.module.css';

/** 页面文案（页面设计成稿，逐字呈现）。 */
const COPY = {
  back: '← 返回',
  title: '案例与资料',
  searchPlaceholder: '搜案例、搜资料',
  searchLabel: '检索',
  caseTab: '案例',
  knowledgeTab: '资料',
  noResultsTitle: '没有找到相关内容',
  noResultsDescription: '试试更日常的措辞，比如「超市哭闹」而不是「情绪失调节」。',
  notReadyTitle: '案例库还在准备中',
  notReadyDescription: '一期的案例与资料还在录入中，这里暂时没有可浏览的内容。',
  retry: '重试',
  withdrawn: '该来源已撤下',
  withdrawnBody: '这条资料已不再作为依据使用',
  collapseHint: '收起',
  loadMore: '加载更多',
  loadingMore: '正在加载…',
  loadingMoreLabel: '正在加载更多',
  expandNarrative: '展开内容',
  cardsHeading: '案例卡片',
  locatorLabel: '定位',
} as const;

/** 案例库浏览页 props。 */
export interface LibraryPageProps {
  /** 资料库端口。 */
  port: LibraryPort;
  /** 进入参数（`?item=` / `?section=`）；默认取当前 location 的查询串。 */
  searchOverride?: string;
}

/**
 * 渲染案例库浏览页。
 *
 * 前置: port 已装配
 * 后置: 输出次级页头、吸顶检索行与结果列表；deep-link 三态各有明确形态
 * 异常: 无（端口异常在 hook 内分类成状态）
 */
export function LibraryPage({ port, searchOverride }: LibraryPageProps) {
  const location = useLocation();
  const page = useLibraryPage(port, searchOverride ?? location.search);
  const showWithdrawnCard = page.deepLink.kind === 'withdrawn';
  const focused = page.deepLink.kind === 'in-library' ? page.deepLink.item : null;
  // 定位到的条目可能落在未加载的页里：那样它在列表里找不到，就要单独出一张定位卡，
  // 否则从引用跳过来会落在一片「不在这里」的空列表上。
  const focusedInList = focused !== null && page.items.some((item) => item.item_id === focused.item_id);

  return (
    <AppShell>
      <header className="subpage-head">
        <Link className="sp-back" to="/">
          {COPY.back}
        </Link>
        <span className="sp-title">{COPY.title}</span>
      </header>

      {/* 检索行：滚动时吸顶，因此它必须在内容之前、且不随结果区重建。 */}
      <div className={styles.searchRow}>
        <label className="field">
          <span className="sr-only">{COPY.searchLabel}</span>
          <input
            className={styles.searchInput}
            onChange={(event) => {
              page.setQuery(event.target.value);
            }}
            placeholder={COPY.searchPlaceholder}
            type="search"
            value={page.query}
          />
        </label>
        <div className={styles.tabs} role="group" aria-label="检索范围">
          {(['case', 'knowledge'] as const).map((kind) => (
            <button
              aria-pressed={page.library === kind}
              className={page.library === kind ? 'tag selected' : 'tag'}
              key={kind}
              onClick={() => {
                page.setLibrary(kind);
              }}
              type="button"
            >
              {kind === 'case' ? COPY.caseTab : COPY.knowledgeTab}
            </button>
          ))}
        </div>
        {/* 检索中的呼吸点：结果区保持旧结果，避免闪空。 */}
        {page.status === 'loading' && page.items.length > 0 && (
          <span className="flame-dot sm breathing" aria-hidden="true" data-testid="library-searching" />
        )}
      </div>

      {showWithdrawnCard && page.deepLink.kind === 'withdrawn' && (
        // 已撤下：只带标题，不显示正文与其他字段（契约第 5 节）。
        <article className="tile" aria-label="已撤下的来源">
          <span className="status off">{COPY.withdrawn}</span>
          <h2 className={styles.withdrawnTitle}>{page.deepLink.title}</h2>
          <p className="hint">{COPY.withdrawnBody}</p>
        </article>
      )}

      {focused !== null && !focusedInList && (
        <article className={`panel ${styles.focused}`}>
          <span className="tag meta">{COPY.locatorLabel}</span>
          <ItemRowBody item={focused} expanded={false} onToggle={undefined} />
        </article>
      )}

      {page.status === 'error' && page.failure !== null && (
        <ErrorCard
          actions={
            <button
              className="btn btn-secondary"
              onClick={() => {
                void page.reload();
              }}
              type="button"
            >
              {COPY.retry}
            </button>
          }
          description={libraryFailureDescription(page.failure)}
          title={libraryFailureTitle(page.failure)}
        />
      )}

      {page.status === 'loading' && page.items.length === 0 && <Skeleton rows={4} />}

      {page.status === 'ready' && page.items.length === 0 && (
        <EmptyState
          description={
            emptyStateKind(page.query) === 'no-results' ? COPY.noResultsDescription : COPY.notReadyDescription
          }
          title={emptyStateKind(page.query) === 'no-results' ? COPY.noResultsTitle : COPY.notReadyTitle}
        />
      )}

      {page.items.length > 0 && (
        <>
          <div className={styles.results}>
            {page.items.map((item) => (
              <ItemRow
                expanded={page.expandedId === item.item_id}
                focused={focused !== null && focused.item_id === item.item_id}
                item={item}
                key={item.item_id}
                onToggle={() => {
                  void page.toggleExpand(item.item_id);
                }}
              />
            ))}
          </div>
          {/* 尾部只有一种形态：还有下一页时给加载入口，失败时给错误卡 + 重试。
           * 分页失败过去只写进整页 `failure` 而 status 仍为 ready，而错误卡只在
           * status==='error' 渲染——失败因此在界面上零反馈（禁止静默兜底）。 */}
          {page.loadMoreFailure !== null ? (
            <ErrorCard
              actions={
                <button
                  className="btn btn-secondary"
                  onClick={() => {
                    void page.loadMore();
                  }}
                  type="button"
                >
                  {COPY.retry}
                </button>
              }
              description={libraryFailureDescription(page.loadMoreFailure)}
              title={libraryFailureTitle(page.loadMoreFailure)}
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
    </AppShell>
  );
}

/** 结果行 props。 */
interface ItemRowProps {
  item: LibraryListItem;
  expanded: boolean;
  focused: boolean;
  onToggle(): void;
}

/**
 * 渲染一条结果（整卡可点，就地展开）。
 *
 * 展开时卡片边框转 `--fg-2` 色以示「进入阅读」，由 styles.reading 承担；
 * 定位高亮（`--focus-ring`）是一次性的，由 styles.focused 承担。
 */
function ItemRow({ item, expanded, focused, onToggle }: ItemRowProps) {
  return (
    <article
      className={`list-row ${styles.card} ${expanded ? styles.reading : ''} ${focused ? styles.focused : ''}`}
    >
      <button className={styles.cardButton} onClick={onToggle} type="button">
        <ItemRowBody expanded={expanded} item={item} onToggle={onToggle} />
      </button>
      {expanded && item.narrative !== null && (
        <div className="gc-body">
          {item.narrative.sections.map((section) => (
            <section key={section.key}>
              <h3 className={styles.sectionHeading}>{section.heading}</h3>
              <p>{section.text}</p>
            </section>
          ))}
        </div>
      )}
      {expanded && item.cards !== null && item.cards.length > 0 && (
        <div className="gc-body">
          <h3 className={styles.sectionHeading}>{COPY.cardsHeading}</h3>
          {item.cards.map((card) => (
            <div className={styles.cardBody} key={card.card_id}>
              <p>{card.scenario}</p>
              {/* 高风险字段照旧返回，呈现纪律在技能与页面层：这里只如实标出风险档，
               * 不把处置建议改写成转述语之外的形态（契约第 4 节）。 */}
              <p className="meta">
                {riskClassLabel(card.risk_class)}
                {card.inferred_fields.length > 0 && ` · 含推断字段：${card.inferred_fields.join('、')}`}
              </p>
            </div>
          ))}
        </div>
      )}
    </article>
  );
}

/** 行内可读内容（标题、摘要、元信息）。 */
function ItemRowBody({
  item,
  expanded,
  onToggle,
}: {
  /** 只接基础条目：deep-link 定位卡拿到的是不带展开内容的那一份。 */
  item: LibraryItem;
  expanded: boolean;
  /**
   * 行所在卡片是否可点（提示的开关）。
   *
   * 点击动作挂在卡片按钮上，本组件不调用它；传入即表示这一行位于可点卡片内，
   * 于是展开/收起提示随之出现。deep-link 定位卡不是可点卡片，显式传 undefined。
   */
  onToggle?: (() => void) | undefined;
}) {
  return (
    <>
      <strong className="lr-title">{item.title}</strong>
      <p className={`lr-sub ${styles.clamp}`}>{item.snippet}</p>
      {/* 状态徽章直出三态之一：虚构样例用灰调（.status.off）+ 文字，与真实案例混列但可辨。 */}
      <span className={isFictional(item.status) ? 'status off' : 'tag meta'}>{statusLabel(item.status)}</span>
      <p className="lr-meta">{itemMetaParts(item).join(' · ')}</p>
      {item.applicable_scope !== '' && <p className="lr-meta">适用：{item.applicable_scope}</p>}
      {onToggle !== undefined && (
        <span className="meta">{expanded ? COPY.collapseHint : COPY.expandNarrative}</span>
      )}
    </>
  );
}
