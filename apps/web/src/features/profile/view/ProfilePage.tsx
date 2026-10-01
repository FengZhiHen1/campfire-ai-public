/**
 * 模块: features/profile/view/ProfilePage
 * 职责: 档案页——对象切换器、一页摘要、待确认分组、领域分组、补充与对象管理
 * 数据来源:
 *   - docs/design/pages/档案页.md: MUST — 全文（布局结构、组件选用、状态覆盖、token 使用）
 *   - docs/design/components.html: MUST — .panel/.tag/.group-collapse/.list-row/.status.unruled
 * 边界:
 *   - 依赖: features/profile/viewModel、shared/ui、react-router
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止未确认条目出现在「待确认」分组以外的地方（候选层视觉不变量，AC-18）
 *   - 禁止用橙色标待确认分组（琥珀 --status-unruled 圆点；橙色留给主动作）
 *   - 禁止为不支持对象建立第二层导航（单页内切换，页面设计布局第 2 条）
 */

import { useState } from 'react';

import type { ProfileItem } from '../../../shared/types/profile';
import { AppShell } from '../../../shared/ui/AppShell';
import { EmptyState, ErrorCard, Skeleton } from '../../../shared/ui/StatePrimitives';
import type { ProfilePort } from '../application/ports';
import { DOMAIN_LABELS, DOMAIN_ORDER } from '../domain/domains';
import { isRetryable, profileFailureDescription, profileFailureInline, profileFailureTitle } from '../domain/failures';
import { formatMonthDay, groupByDomain, isHistorical, isStale, itemMetaLine, originLabel } from '../domain/items';
import { useProfileEntryActions, inlineFailureFor } from '../viewModel/useProfileEntryActions';
import { useProfileObjectActions } from '../viewModel/useProfileObjectActions';
import { useProfilePage } from '../viewModel/useProfilePage';
import styles from './profilePage.module.css';

/** 页面文案（页面设计「数据与文案」节的成稿，逐字呈现）。 */
const COPY = {
  heading: '档案',
  switcherLabel: '支持对象',
  addObject: '+ 新建对象',
  /** 空态里的主按钮：与切换器 chip 同义但不同文案，避免两个同名按钮（也避免「+」出现在主按钮上）。 */
  createObjectAction: '新建对象',
  moreLabel: '⋯',
  archivedTag: '已归档',
  historicalTag: '已更正',
  summaryTitle: '关于 TA 的当前认识',
  summaryHint: '摘要只收你直接说过或确认过的内容',
  summaryEmpty: '摘要中还没有记录，确认或补充后会出现。',
  correct: '纠正',
  delete: '删除',
  confirm: '确认',
  candidateGroup: '待确认',
  addEntry: '补充一条',
  emptyTitle: '还没有记录',
  emptyDescription: '咨询中你说的关于 TA 的事，会自动记在这里；也可以现在补充一条。',
  noObjectTitle: '还没有记录',
  noObjectDescription: '先给 TA 起个称呼，之后咨询中说的相关事情会记在这里。',
  addEntryTitle: '补充一条记录',
  topicLabel: '主题',
  descriptionLabel: '描述',
  domainLabel: '领域',
  submit: '保存',
  submitting: '正在保存…',
  cancel: '取消',
  deleteSheetTitle: '删除这条记录？',
  deleteSheetBody: '删除后咨询和检索都不会再用到它',
  deleteConfirm: '删除',
  createSheetTitle: '给 TA 起个称呼',
  createSheetHint: '只是你在界面上认出 TA 的名字；不知道可以先写个常用的称呼。',
  nameLabel: '称呼',
  createSubmit: '创建',
  renameSubmit: '保存名字',
  archiveTitle: '归档这个对象？',
  archiveBody: '归档后不再用于新会话，记录仍可查看与恢复',
  archiveSubmit: '归档',
  restoreTitle: '恢复使用？',
  restoreBody: '恢复后它重新出现在新会话的默认对象里',
  restoreSubmit: '恢复使用',
  renameRow: '改名字',
  archiveRow: '归档这个对象',
  restoreRow: '恢复使用',
  retry: '重试',
  correctSheetTitle: '新增一条更正',
  correctHint: '更正会新增一条，原记录不再作为依据',
} as const;

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
        <h1 className={styles.heading}>{COPY.heading}</h1>
      </header>

      {/* 对象切换器：横向滚动（切换是平级单选，滚动语义比换行堆叠更准）。 */}
      <div className={styles.switcher} role="group" aria-label={COPY.switcherLabel}>
        {page.objects.map((object) => (
          <button
            aria-pressed={object.id === page.selectedObjectId}
            className={object.id === page.selectedObjectId ? 'tag selected' : 'tag'}
            key={object.id}
            onClick={() => {
              page.selectObject(object.id);
            }}
            type="button"
          >
            {object.display_name}
            {object.archived_at !== null && <span className="tag meta">{COPY.archivedTag}</span>}
          </button>
        ))}
        {selected !== null && (
          <button
            aria-label="对象操作"
            className="btn btn-quiet"
            onClick={objectActions.openMenu}
            type="button"
          >
            {COPY.moreLabel}
          </button>
        )}
        <button className="tag" onClick={objectActions.openCreate} type="button">
          {COPY.addObject}
        </button>
      </div>

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
          {/* 一页摘要区：本页唯一抬升面板，靠海拔而非颜色获得重量。 */}
          <section className="panel" aria-labelledby="profile-summary">
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
                    // 条目列表有服务端上界（档案面契约第 3 节要求未传 limit 时必须有上界，
                    // 当前实现默认 20 条），超出上界的摘要条目就不在列表里——此时宁可不给
                    // 入口，也不给一个会写错条目的入口。
                    const fullItem = itemsById.get(entryItem.item_id);
                    return (
                      <p className={styles.summaryItem} key={entryItem.item_id}>
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
                            className="btn btn-quiet"
                            onClick={() => {
                              entry.openCorrect(fullItem);
                            }}
                            type="button"
                          >
                            {COPY.correct}
                          </button>
                        )}
                      </p>
                    );
                  })}
                </div>
              ))
            )}
          </section>

          {!hasEntries && (
            <EmptyState
              action={
                <button className="btn btn-primary" onClick={entry.openAdd} type="button">
                  {COPY.addEntry}
                </button>
              }
              description={COPY.emptyDescription}
              title={COPY.emptyTitle}
            />
          )}

          {/* 待确认分组固定在完整条目区最顶部（候选层视觉不变量）。 */}
          {page.candidates.length > 0 && (
            <details className="tile group-collapse" open>
              <summary>
                <span className="status unruled">
                  {COPY.candidateGroup}（{page.candidates.length}）
                </span>
              </summary>
              <div className="gc-body">
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

          {groups.map((group) => (
            <details className="tile group-collapse" key={group.domain} open>
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
                      entry.openCorrect(item);
                    }}
                    onDelete={() => {
                      entry.askDelete(item);
                    }}
                  />
                ))}
              </div>
            </details>
          ))}

          {/* 纠正表单展开在被纠正的那一条下方（不是弹层）。 */}
          {entry.correct !== null && (
            <EntryForm
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
            <button className="btn btn-secondary block" onClick={entry.openAdd} type="button">
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

      {entry.deleteTarget !== null && (
        <div className="confirm-sheet" role="dialog" aria-modal="false" aria-labelledby="profile-delete-title">
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
        </div>
      )}

      {objectActions.sheet !== null && (
        <ObjectSheet
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

/** 稳定层条目行。 */
interface StableRowProps {
  item: ProfileItem;
  busy: boolean;
  failure: string | null;
  onCorrect(): void;
  onDelete(): void;
}

/**
 * 渲染一条完整条目区的条目（稳定层条目，或历史（已被取代）条目）。
 *
 * 这一行不判降权：`isStale` 只对 `freshness = current` 的条目成立（降权由服务端的
 * `effective_freshness` 在取数期算，历史条目带的是 `historical`），因此落在本行的
 * `isStale` 恒为假——在这里判就是一条死分支。「已降权」标与描述默认收起挂在候选行上（见 CandidateRow）。
 *
 * 历史条目由 `include_superseded = true` 随条目流返回（`LoadProfileUseCase.loadObject`
 * 显式打开该开关），归 `items` 的那些落在本行、行首出「已更正」标（档案页第 33、62 行），
 * 落位与候选行的「已降权」标一致：标题之后、描述之前；未确认的系统推断即便已被取代
 * 也归 `candidates`，由候选行呈现（见 CandidateRow）。
 *
 * 历史条目不给「纠正」：已被取代的条目不再是纠正的对象（服务端 `mark_superseded`
 * 的判据要求 `freshness = current` 且 `superseded_by` 为空），这个入口必然失败；
 * 它又能经 `include_superseded` 真的出现在页面上，因此要在行上判掉而不是指望它不出现。
 * 判据用 `isHistorical`，不在这里新写时效判断——同一判据的第二份出口已经栽过三次。
 * 「删除」保留：服务端的删除路径只有归属判据（契约第 1 节还写明已归档对象仍可删除条目），
 * 对被取代的条目照常生效，删自己的条目是正当能力（`RQ-MEM-03` 的查/纠/删）。
 */
function StableRow({ item, busy, failure, onCorrect, onDelete }: StableRowProps) {
  return (
    <article className="list-row">
      <strong className="lr-title">{item.topic}</strong>
      {isHistorical(item) && <span className="tag meta">{COPY.historicalTag}</span>}
      <p className="lr-sub">{item.description}</p>
      <p className="lr-meta">{itemMetaLine(item)}</p>
      <div className="lr-actions">
        {!isHistorical(item) && (
          <button className="btn btn-secondary" disabled={busy} onClick={onCorrect} type="button">
            {COPY.correct}
          </button>
        )}
        <button className="btn btn-quiet" disabled={busy} onClick={onDelete} type="button">
          {COPY.delete}
        </button>
      </div>
      {failure !== null && (
        <p className="field-error" role="alert">
          {failure}
        </p>
      )}
    </article>
  );
}

/** 候选（待确认）条目行。 */
interface CandidateRowProps {
  item: ProfileItem;
  busy: boolean;
  expanded: boolean;
  failure: string | null;
  onConfirm(): void;
  onDelete(): void;
  onToggleExpand(): void;
}

/**
 * 渲染一条候选条目。
 *
 * 与稳定条目的差别不是样式而是位置与操作集合：只出现在「待确认」分组、
 * 只带「待确认」标、只给「确认」与「删除」两个操作（档案页第 89 行的三个呈现位置）。
 *
 * 已降权（stale，90 天）的条目在本行上带「已降权」标、且描述默认收起（档案页第 25 行）：
 * 降权是「可能不再准」的信号，把描述折起来能让人先看到别的，需要核对时再点开。
 * 降权只可能是候选条目：降权判定只作用于 `freshness = current` 的未确认条目（服务端的
 * `effective_freshness`），而完整条目区里的行要么是 `current` 的稳定层、要么是 `historical`
 * 的历史条目，两者都不是 `stale`。该标是本行唯一的一处时效出口：元信息行（`itemMetaLine`）
 * 不再重复写时效措辞。
 *
 * 「已被取代的候选」（历史条目落在候选组，可达：纠正一条未确认的候选）不给「确认」：
 * 服务端 `confirm_item` 的 `WHERE` 要求 `superseded_by IS NULL`，对已被取代的条目一律失败
 * （`ProfileItemNotFoundError`，档案面契约第 1 节映射为 422 `invalid_payload`），是必败入口。
 * 判据仍是 `isHistorical`，不在这里另写一条取代判断。
 * 「删除」不动：删除路径只判归属，对本行照常生效。
 */
function CandidateRow({ item, busy, expanded, failure, onConfirm, onDelete, onToggleExpand }: CandidateRowProps) {
  const stale = isStale(item);
  const historical = isHistorical(item);
  const showDescription = !stale || expanded;
  return (
    <article className="list-row candidate-record">
      <span className="status unruled">待确认 · {originLabel(item.origin)}</span>
      <strong className="lr-title">{item.topic}</strong>
      {historical && <span className="tag meta">{COPY.historicalTag}</span>}
      {stale && <span className="tag meta">已降权</span>}
      {showDescription ? (
        <p className="lr-sub">{item.description}</p>
      ) : (
        <button className="text-button" onClick={onToggleExpand} type="button">
          展开内容
        </button>
      )}
      <p className="lr-meta">{itemMetaLine(item)}</p>
      <div className="lr-actions">
        {/* 确认是高频正向操作、删除是低频危险操作：并排但间距 ≥12px（.lr-actions 的 gap）。 */}
        {!historical && (
          <button className="btn btn-secondary" disabled={busy} onClick={onConfirm} type="button">
            {COPY.confirm}
          </button>
        )}
        <button className="btn btn-quiet" disabled={busy} onClick={onDelete} type="button">
          {COPY.delete}
        </button>
      </div>
      {failure !== null && (
        <p className="field-error" role="alert">
          {failure}
        </p>
      )}
    </article>
  );
}

/** 补充/纠正表单 props。 */
interface EntryFormProps {
  title: string;
  hint?: string;
  submitting: boolean;
  failure: string | null;
  errors: { topic?: string; description?: string; domain?: string };
  draft: { domain: string; topic: string; description: string };
  submitLabel: string;
  onSubmit(): void;
  onCancel(): void;
  onChange(patch: { domain?: string; topic?: string; description?: string }): void;
}

/**
 * 渲染补充/纠正内联表单。
 *
 * 前置: draft 已由调用方持有（提交失败时保留原内容，不清空）
 * 后置: 输出领域下拉、主题与描述输入、提交与取消；错误内联呈现且不清空输入
 * 异常: 无
 */
function EntryForm({ title, hint, submitting, failure, errors, draft, submitLabel, onSubmit, onCancel, onChange }: EntryFormProps) {
  return (
    <section className="tile" aria-labelledby="profile-entry-form">
      <h2 id="profile-entry-form">{title}</h2>
      {hint !== undefined && <p className="hint">{hint}</p>}
      <label className="field">
        <span>{COPY.domainLabel}</span>
        <select
          aria-invalid={errors.domain !== undefined}
          onChange={(event) => {
            onChange({ domain: event.target.value });
          }}
          value={draft.domain}
        >
          {DOMAIN_ORDER.map((domain) => (
            <option key={domain} value={domain}>
              {DOMAIN_LABELS[domain]}
            </option>
          ))}
        </select>
      </label>
      {errors.domain !== undefined && <p className="field-error">{errors.domain}</p>}
      <label className="field">
        <span>{COPY.topicLabel}</span>
        <input
          aria-invalid={errors.topic !== undefined}
          onChange={(event) => {
            onChange({ topic: event.target.value });
          }}
          value={draft.topic}
        />
      </label>
      {errors.topic !== undefined && <p className="field-error">{errors.topic}</p>}
      <label className="field">
        <span>{COPY.descriptionLabel}</span>
        <textarea
          aria-invalid={errors.description !== undefined}
          onChange={(event) => {
            onChange({ description: event.target.value });
          }}
          rows={4}
          value={draft.description}
        />
      </label>
      {errors.description !== undefined && <p className="field-error">{errors.description}</p>}
      {failure !== null && (
        <p className="field-error" role="alert">
          {failure}
        </p>
      )}
      <div className="button-row">
        <button className="btn btn-quiet" disabled={submitting} onClick={onCancel} type="button">
          {COPY.cancel}
        </button>
        <button className="btn btn-primary" disabled={submitting} onClick={onSubmit} type="button">
          {submitting ? COPY.submitting : submitLabel}
        </button>
      </div>
    </section>
  );
}

/** 对象操作单 props。 */
interface ObjectSheetProps {
  kind: 'menu' | 'create' | 'rename' | 'archive' | 'restore';
  displayName: string;
  archived: boolean;
  name: string;
  submitting: boolean;
  failure: string | null;
  errors: { displayName?: string };
  onChangeName(name: string): void;
  onSubmit(): void;
  onCancel(): void;
  onRename(): void;
  onArchive(): void;
  onRestore(): void;
}

/**
 * 渲染对象操作单（契约组件 .confirm-sheet，底部滑入）。
 *
 * 为什么不用原生 `<dialog>.showModal()`：jsdom 未实现 showModal（T10 实测），
 * 而前端测试环境是 jsdom；`role="dialog"` + `aria-modal="false"` 与设置页的登出确认
 * 同一做法，不声称模态语义（焦点陷阱、Esc 关闭未实现也未验证）。
 *
 * 为什么归档要在单内二次确认、改名与恢复不用：归档改变后续会话的默认对象，
 * 而改名可再改、恢复可逆。
 */
function ObjectSheet(props: ObjectSheetProps) {
  const { kind } = props;
  if (kind === 'menu') {
    return (
      <div className="confirm-sheet" role="dialog" aria-modal="false" aria-labelledby="profile-object-title">
        <h2 id="profile-object-title">{props.displayName}</h2>
        <div className="button-row">
          <button className="btn btn-secondary" onClick={props.onRename} type="button">
            {COPY.renameRow}
          </button>
          {props.archived ? (
            <button className="btn btn-secondary" onClick={props.onRestore} type="button">
              {COPY.restoreRow}
            </button>
          ) : (
            <button className="btn btn-quiet" onClick={props.onArchive} type="button">
              {COPY.archiveRow}
            </button>
          )}
        </div>
        <div className="button-row">
          <button className="btn btn-quiet" onClick={props.onCancel} type="button">
            {COPY.cancel}
          </button>
        </div>
      </div>
    );
  }

  const title =
    kind === 'create'
      ? COPY.createSheetTitle
      : kind === 'rename'
        ? COPY.renameRow
        : kind === 'archive'
          ? COPY.archiveTitle
          : COPY.restoreTitle;
  const body =
    kind === 'create'
      ? COPY.createSheetHint
      : kind === 'archive'
        ? COPY.archiveBody
        : kind === 'restore'
          ? COPY.restoreBody
          : null;

  return (
    <div className="confirm-sheet" role="dialog" aria-modal="false" aria-labelledby="profile-object-form-title">
      <h2 id="profile-object-form-title">{title}</h2>
      {body !== null && <p>{body}</p>}
      {kind === 'create' || kind === 'rename' ? (
        <label className="field">
          <span>{COPY.nameLabel}</span>
          <input
            aria-invalid={props.errors.displayName !== undefined}
            onChange={(event) => {
              props.onChangeName(event.target.value);
            }}
            value={props.name}
          />
        </label>
      ) : null}
      {props.errors.displayName !== undefined && <p className="field-error">{props.errors.displayName}</p>}
      {props.failure !== null && (
        <p className="field-error" role="alert">
          {props.failure}
        </p>
      )}
      <div className="button-row">
        <button className="btn btn-quiet" disabled={props.submitting} onClick={props.onCancel} type="button">
          {COPY.cancel}
        </button>
        <button
          className={kind === 'archive' ? 'btn btn-danger' : 'btn btn-primary'}
          disabled={props.submitting || ((kind === 'create' || kind === 'rename') && props.name.trim() === '')}
          onClick={props.onSubmit}
          type="button"
        >
          {kind === 'create'
            ? COPY.createSubmit
            : kind === 'rename'
              ? COPY.renameSubmit
              : kind === 'archive'
                ? COPY.archiveSubmit
                : COPY.restoreSubmit}
        </button>
      </div>
    </div>
  );
}
