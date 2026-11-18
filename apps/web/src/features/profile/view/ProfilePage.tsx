/**
 * 模块: features/profile/view/ProfilePage
 * 职责: 档案页——对象切换器、一页摘要、待确认分组、领域分组、补充与对象管理
 * 数据来源:
 *   - docs/design/pages/档案页.md: MUST — 全文（布局结构、组件选用、状态覆盖、token 使用）
 *   - docs/design/components.html: MUST — .panel/.tag/.group-collapse/.list-row/.status.unruled
 * 边界:
 *   - 依赖: features/profile/viewModel（useProfilePage / useProfileEditors / 两个动作 hook）、
 *     shared/ui、react-router
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止未确认条目出现在「待确认」分组以外的地方（候选层视觉不变量，AC-18）
 *   - 禁止用橙色标待确认分组（琥珀 --status-unruled 圆点；橙色留给主动作）
 *   - 禁止为不支持对象建立第二层导航（单页内切换，页面设计布局第 2 条）
 */

import { useState } from 'react';

import { AppShell } from '../../../shared/ui/AppShell';
import { ConfirmSheet } from '../../../shared/ui/ConfirmSheet';
import { EmptyState, ErrorCard, Skeleton } from '../../../shared/ui/StatePrimitives';
import type { ProfilePort } from '../application/ports';
import { DOMAIN_LABELS } from '../domain/domains';
import { isRetryable, profileFailureDescription, profileFailureInline, profileFailureTitle } from '../domain/failures';
import { formatMonthDay, groupByDomain, originLabel } from '../domain/items';
import { useProfileEditors } from '../viewModel/useEditors';
import { useProfileEntryActions, inlineFailureFor } from '../viewModel/useProfileEntryActions';
import { useProfileObjectActions } from '../viewModel/useProfileObjectActions';
import { useProfilePage } from '../viewModel/useProfilePage';
import styles from './profilePage.module.css';
import { CandidateRow, Copy, EntryForm, ObjectSheet, StableRow } from './profileRows';

/** 页面文案（页面设计「数据与文案」节的成稿，逐字呈现）。 */
const COPY = Copy;

/** 档案页 props：端口经 props 注入（页面在测试里可用替身端口渲染）。 */
export interface ProfilePageProps {
  /** 档案端口。 */
  port: ProfilePort;
}

/**
 * 渲染档案页。
 *
 * 前置: port 已装配
 * 后置: 输出对象切换器与内容区；加载/空/错误三态都有明确形态
 * 异常: 无（端口异常在 hook 内分类成状态）
 */
export function ProfilePage({ port }: ProfilePageProps) {
  const page = useProfilePage(port);
  const entry = useProfileEntryActions(port, page.selectedObjectId, page.reloadObject);
  const objectActions = useProfileObjectActions(
    port,
    page.objects.find((object) => object.id === page.selectedObjectId) ?? null,
    page.reload,
  );
  // 描述展开状态：已降权（stale）条目默认收起（档案页第 25 行）。存的是被展开的行，
  // 不是被收起的行——这样默认值（不收）不必随条目增删同步。
  const [expanded, setExpanded] = useState<readonly string[]>([]);
  const editors = useProfileEditors(entry, page.selectObject);

  const selected = page.objects.find((object) => object.id === page.selectedObjectId) ?? null;
  const groups = groupByDomain(page.items);
  const hasEntries = page.items.length > 0 || page.candidates.length > 0;
  // 摘要条目的纠正入口要靠条目列表里的那一条完整记录：摘要载荷只带 item_id、origin
  // 与时间（档案面契约第 3 节），而纠正流要预填原主题与原描述。摘要只取稳定层，
  // 稳定层条目必在 `page.items` 里（该列表是稳定层加上 opt-in 取回的历史条目），
  // 因此按 item_id 就能对上；历史条目不会出现在摘要里，只会多出来，不会对错。
  const itemsById = new Map(page.items.map((item) => [item.item_id, item]));

  return (
    <AppShell tab="profile">
      <header className="page-head">
        <div><h1 className={styles.heading}>{COPY.heading}</h1><p className="hint">了解 TA，也让每一次咨询更有上下文。</p></div>
      </header>

      {/*
        对象区：切换（谁）与管理（对当前对象做什么）分成两层。
        切换是平级单选，用横向滚动的 chip；管理是低频动作，放在切换条下方、
        用一条分隔线与 chip 分开——两者混在同一行时，「⋯」读起来像又一个对象。
      */}
      <section className={styles.objects}>
        <div className={styles.objectsHead}>
          <p className={styles.objectsLabel}>{COPY.switcherLabel}</p>
          <span className="meta">{page.objects.length} 个对象</span>
        </div>
        <div className={styles.switcher} role="group" aria-label={COPY.switcherLabel}>
          {page.objects.map((object) => (
            <button
              aria-pressed={object.id === page.selectedObjectId}
              disabled={editors.busy}
              className={object.id === page.selectedObjectId ? 'tag selected' : 'tag'}
              key={object.id}
              onClick={() => {
                if (object.id === page.selectedObjectId) return;
                editors.requestSwitchObject(object.id);
              }}
              type="button"
            >
              {object.display_name}
              {object.archived_at !== null && <span className={styles.archived}>{COPY.archivedTag}</span>}
            </button>
          ))}
        </div>
        <div className={styles.objectTools}>
          {selected !== null && (
            <button
              aria-label="对象操作"
              className={styles.objectTool}
              onClick={objectActions.openMenu}
              type="button"
            >
              <span aria-hidden="true">{COPY.moreLabel}</span> 管理当前对象
            </button>
          )}
          <button className={styles.objectTool} onClick={objectActions.openCreate} type="button">
            {COPY.addObject}
          </button>
        </div>
      </section>

      {page.status === 'ready' && selected !== null && (
        <nav className={styles.sectionNav} aria-label="档案分区">
          <a href="#profile-summary">当前认识</a>
          {page.candidates.length > 0 && <a href="#profile-candidates">待确认 {page.candidates.length}</a>}
          {groups.length > 0 && <a href="#profile-records">全部记录</a>}
        </nav>
      )}

      {entry.notice !== null && (
        <p className="hint" role="status">
          {entry.notice}{' '}
          <button className="text-button" onClick={entry.dismissNotice} type="button">
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
                  void page.reload();
                }}
                type="button"
              >
                {COPY.retry}
              </button>
            ) : undefined
          }
          description={profileFailureDescription(page.failure)}
          title={profileFailureTitle(page.failure)}
        />
      )}

      {page.status === 'loading' && (
        <section className="panel" aria-busy="true">
          <Skeleton rows={3} />
        </section>
      )}

      {page.status === 'ready' && page.objects.length === 0 && (
        <EmptyState
          action={
            <button className="btn btn-primary" onClick={objectActions.openCreate} type="button">
              {COPY.createObjectAction}
            </button>
          }
          description={COPY.noObjectDescription}
          title={COPY.noObjectTitle}
        />
      )}

      {page.status === 'ready' && page.objects.length > 0 && (
        <>
          {/* 一页摘要区：靠左侧细线与留白获得重量，不再嵌套抬升大卡。 */}
          <section className={styles.summary} role="region" aria-labelledby="profile-summary">
            <div className="record-head">
              <h2 id="profile-summary">{COPY.summaryTitle}</h2>
              <p className="hint">{COPY.summaryHint}</p>
            </div>
            {page.summary.length === 0 ? (
              <p className="hint">{COPY.summaryEmpty}</p>
            ) : (
              page.summary.map((field) => (
                <div className={styles.summaryField} key={field.key}>
                  <h3 className={styles.summaryLabel}>{field.label}</h3>
                  {field.items.map((entryItem) => {
                    // 取不到完整条目时不放这个按钮：纠正流要预填原主题与原描述，
                    // 只有 item_id 的摘要条目开出来的会是一张改错对象的表单。
                    // 条目列表有服务端上界（档案面契约第 3 节），超出上界的摘要条目就不在
                    // 列表里——此时宁可不给入口，也不给一个会写错条目的入口。
                    const fullItem = itemsById.get(entryItem.item_id);
                    return (
                      <div className={styles.summaryItem} key={entryItem.item_id}>
                        <span>{entryItem.text}</span>
                        <span className="meta">
                          {originLabel(entryItem.origin)}
                          {entryItem.last_confirmed_at === null
                            ? ' · 时间未知'
                            : ` · ${formatMonthDay(entryItem.last_confirmed_at)} 确认`}
                        </span>
                        {fullItem !== undefined && (
                          // aria-label 让同名的多个「纠正」各有可区分的可访问名
                          // （可见文字仍是设计里的「纠正」）。
                          <button
                            aria-label={`${COPY.correct}：${entryItem.text}`}
                            className={"text-button " + styles.summaryCorrect}
                            onClick={() => {
                              editors.requestCorrect(fullItem);
                            }}
                            type="button"
                          >
                            {COPY.correct}
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              ))
            )}
          </section>

          {!hasEntries && (
            <EmptyState
              action={
                <button className="btn btn-primary" onClick={editors.requestAdd} type="button">
                  {COPY.addEntry}
                </button>
              }
              description={COPY.emptyDescription}
              title={COPY.emptyTitle}
            />
          )}

          {/* 待确认分组固定在完整条目区最顶部（候选层视觉不变量）。 */}
          {page.candidates.length > 0 && (
            <details id="profile-candidates" className={`group-collapse ${styles.candidateGroup}`} open>
              <summary>
                <span className="status unruled">
                  {COPY.candidateGroup}（{page.candidates.length}）
                </span>
              </summary>
              <div className="gc-body">
                {/* 候选与稳定记录的差别必须先说清楚再列条目：候选是系统推断，
                    确认后才进入摘要；否则「待确认」只是一个小标签，容易被读成已生效。 */}
                <p className={styles.candidateHint}>还没确认的内容。确认后才会进入「当前认识」，也可以直接删除。</p>
                {page.candidates.map((candidate) => (
                  <CandidateRow
                    busy={entry.busyItemId === candidate.item_id}
                    expanded={expanded.includes(candidate.item_id)}
                    failure={inlineFailureFor(entry.rowFailure, candidate.item_id)}
                    item={candidate}
                    key={candidate.item_id}
                    onConfirm={() => {
                      void entry.confirmCandidate(candidate.item_id);
                    }}
                    onDelete={() => {
                      entry.askDelete(candidate);
                    }}
                    onToggleExpand={() => {
                      setExpanded((current) =>
                        current.includes(candidate.item_id)
                          ? current.filter((id) => id !== candidate.item_id)
                          : [...current, candidate.item_id],
                      );
                    }}
                  />
                ))}
              </div>
            </details>
          )}

          <div id="profile-records" className="stack">{groups.map((group) => (
            <details className={`group-collapse ${styles.domainGroup}`} key={group.domain} open>
              <summary>
                {DOMAIN_LABELS[group.domain]}（{group.items.length}）
              </summary>
              <div className="gc-body">
                {group.items.map((item) => (
                  <StableRow
                    busy={entry.busyItemId === item.item_id}
                    failure={inlineFailureFor(entry.rowFailure, item.item_id)}
                    item={item}
                    key={item.item_id}
                    onCorrect={() => {
                      editors.requestCorrect(item);
                    }}
                    onDelete={() => {
                      entry.askDelete(item);
                    }}
                  />
                ))}
              </div>
            </details>
          ))}</div>

          {page.loadMoreFailure !== null ? (
            <ErrorCard title="后续记录没有加载成功" description={profileFailureDescription(page.loadMoreFailure)}
              actions={<button className="btn btn-secondary" type="button" onClick={() => void page.loadMore()}>重试加载记录</button>} />
          ) : page.hasMore && (
            <button className="btn btn-secondary block" type="button" disabled={page.loadingMore} onClick={() => void page.loadMore()}>
              {page.loadingMore ? '正在加载记录…' : '加载更多记录'}
            </button>
          )}

          {/* 纠正表单展开在被纠正的那一条下方（不是弹层）。 */}
          {entry.correct !== null && (
            <EntryForm
              key={entry.correct.target.item_id}
              readonlyDomain
              draft={entry.correct.draft}
              errors={entry.correct.errors}
              failure={entry.correct.failure === null ? null : profileFailureInline(entry.correct.failure)}
              hint={COPY.correctHint}
              onCancel={entry.closeCorrect}
              onChange={entry.updateCorrectDraft}
              onSubmit={() => {
                void entry.submitCorrect();
              }}
              submitting={entry.correct.submitting}
              submitLabel={COPY.correct}
              title={COPY.correctSheetTitle}
            />
          )}

          {entry.add === null ? (
            <button className="btn btn-secondary block" disabled={editors.busy} onClick={editors.requestAdd} type="button">
              {COPY.addEntry}
            </button>
          ) : (
            <EntryForm
              draft={entry.add.draft}
              errors={entry.add.errors}
              failure={entry.add.failure === null ? null : profileFailureInline(entry.add.failure)}
              onCancel={entry.closeAdd}
              onChange={entry.updateAddDraft}
              onSubmit={() => {
                void entry.submitAdd();
              }}
              submitting={entry.add.submitting}
              submitLabel={COPY.submit}
              title={COPY.addEntryTitle}
            />
          )}
        </>
      )}

      {editors.pendingSwitch !== null && (
        <ConfirmSheet
          labelledBy={editors.pendingSwitch.kind === 'switch-object' ? 'profile-switch-title' : 'profile-editor-title'}
          onDismiss={editors.keepEditing}
        >
          {editors.pendingSwitch.kind === 'switch-object' ? (
            <>
              <h2 id="profile-switch-title">切换支持对象？</h2>
              <p>当前编辑尚未保存，切换后将丢弃这份草稿。</p>
              <div className="button-row">
                <button className="btn btn-secondary" type="button" onClick={editors.keepEditing}>继续编辑</button>
                <button className="btn btn-danger" type="button" onClick={editors.discardAndContinue}>切换并丢弃</button>
              </div>
            </>
          ) : (
            <>
              <h2 id="profile-editor-title">放弃当前编辑？</h2>
              <p>新的编辑操作会替换尚未保存的草稿。</p>
              <div className="button-row">
                <button className="btn btn-secondary" type="button" onClick={editors.keepEditing}>继续编辑</button>
                <button className="btn btn-danger" type="button" onClick={editors.discardAndContinue}>放弃并继续</button>
              </div>
            </>
          )}
        </ConfirmSheet>
      )}
      {entry.deleteTarget !== null && (
        <ConfirmSheet labelledBy="profile-delete-title" onDismiss={entry.cancelDelete}>
          <h2 id="profile-delete-title">{COPY.deleteSheetTitle}</h2>
          <p>{COPY.deleteSheetBody}</p>
          <div className="button-row">
            <button className="btn btn-quiet" onClick={entry.cancelDelete} type="button">
              {COPY.cancel}
            </button>
            <button
              className="btn btn-danger"
              onClick={() => {
                void entry.confirmDelete();
              }}
              type="button"
            >
              {COPY.deleteConfirm}
            </button>
          </div>
        </ConfirmSheet>
      )}

      {objectActions.sheet !== null && (
        /*
          key 必须是 kind：菜单单与表单单是两张用途不同的单，共用同一个 ObjectSheet
          位置。不加 key 时 React 复用同一个 DOM 节点，ConfirmSheet 的挂载副作用不会重跑，
          于是「点改名字」把内容换成表单后焦点留在被替换掉的按钮上（浏览器实测：
          activeElement 变成 body，焦点不在单内）。加 key 让它重新挂载——与「新的单滑入」
          的语义一致，焦点也随之进入新单的第一个可聚焦元素。
        */
        <ObjectSheet
          key={objectActions.sheet.kind}
          archived={selected !== null && selected.archived_at !== null}
          displayName={selected?.display_name ?? ''}
          errors={objectActions.sheet.errors}
          failure={objectActions.sheet.failure === null ? null : profileFailureInline(objectActions.sheet.failure)}
          kind={objectActions.sheet.kind}
          name={objectActions.sheet.name}
          onArchive={objectActions.openArchive}
          onCancel={objectActions.closeSheet}
          onChangeName={objectActions.updateName}
          onRename={() => {
            if (selected !== null) objectActions.openRename(selected);
          }}
          onRestore={objectActions.openRestore}
          onSubmit={() => {
            void objectActions.submit();
          }}
          submitting={objectActions.sheet.submitting}
        />
      )}
    </AppShell>
  );
}
