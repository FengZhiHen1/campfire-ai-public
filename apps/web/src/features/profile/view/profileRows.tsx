/**
 * 模块: features/profile/view/profileRows
 * 职责: 档案页的行与表单组件——候选行、稳定条目行、补充/纠正表单、对象操作单，以及页面文案
 * 数据来源:
 *   - docs/design/pages/档案页.md: MUST — 组件选用（.list-row/.tag.meta/.status.unruled/.confirm-sheet）、
 *     候选层视觉不变量、纠正/删除语义
 *   - docs/design/components.html: MUST — .list-row/..tag/.status
 * 边界:
 *   - 依赖: shared/types/profile、shared/ui/ConfirmSheet、features/profile/domain
 *   - 被依赖: features/profile/view/ProfilePage
 * 禁止行为:
 *   - 禁止未确认条目出现在「待确认」分组以外的地方（候选行只由 ProfilePage 放进待确认分组）
 *   - 禁止用橙色标待确认（琥珀 --status-unruled 圆点；橙色留给主动作）
 *
 * 为什么单独成文件：这些是纯呈现的叶子组件，与页面装配（数据、打开哪个表单）改动理由不同；
 * 抽出后 ProfilePage 只负责分区与流程接线。语义与样式与拆分前逐字一致。
 */

import { useEffect, useRef } from 'react';

import type { ProfileItem } from '../../../shared/types/profile';
import { ConfirmSheet } from '../../../shared/ui/ConfirmSheet';
import { DOMAIN_LABELS, DOMAIN_ORDER } from '../domain/domains';
import { isHistorical, isStale, itemMetaLine, originLabel } from '../domain/items';

/** 页面文案（页面设计「数据与文案」节的成稿，逐字呈现）。 */
export const Copy = {
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
  emptyDescription: '咨询中你说的关于 TA 的事，会自动记在这里；也可以现在补充一条',
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
export function StableRow({ item, busy, failure, onCorrect, onDelete }: StableRowProps) {
  return (
    <article className="list-row">
      <strong className="lr-title">{item.topic}</strong>
      {isHistorical(item) && <span className="tag meta">{Copy.historicalTag}</span>}
      <p className="lr-sub">{item.description}</p>
      <p className="lr-meta">{itemMetaLine(item)}</p>
      <div className="lr-actions">
        {!isHistorical(item) && (
          <button className="btn btn-secondary" disabled={busy} onClick={onCorrect} type="button">
            {Copy.correct}
          </button>
        )}
        <button className="btn btn-quiet" disabled={busy} onClick={onDelete} type="button">
          {Copy.delete}
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
 * 与稳定条目的差别不在样式，而在位置、行首标与操作集合三处：
 * 只出现在「待确认」分组（档案页第 89 行的三个呈现位置）；
 * 行首状态标是「待确认」，此外还会出「已更正」与「已降权」两个时效标；
 * 操作是「确认」与「删除」，例外见下面「已被取代的候选」一段。
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
export function CandidateRow({ item, busy, expanded, failure, onConfirm, onDelete, onToggleExpand }: CandidateRowProps) {
  const stale = isStale(item);
  const historical = isHistorical(item);
  const showDescription = !stale || expanded;
  return (
    <article className="list-row candidate-record">
      <span className="status unruled">待确认 · {originLabel(item.origin)}</span>
      <strong className="lr-title">{item.topic}</strong>
      {historical && <span className="tag meta">{Copy.historicalTag}</span>}
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
            {Copy.confirm}
          </button>
        )}
        <button className="btn btn-quiet" disabled={busy} onClick={onDelete} type="button">
          {Copy.delete}
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
  readonlyDomain?: boolean;
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
export function EntryForm({ title, hint, submitting, failure, errors, draft, submitLabel, onSubmit, onCancel, onChange, readonlyDomain = false }: EntryFormProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.scrollIntoView?.({ block: 'start' });
    heading.current?.focus({ preventScroll: true });
  }, []);
  return (
    <section className="tile stack" aria-labelledby="profile-entry-form">
      <h2 id="profile-entry-form" ref={heading} tabIndex={-1}>{title}</h2>
      {hint !== undefined && <p className="hint">{hint}</p>}
      <label className="field">
        <span>{Copy.domainLabel}</span>
        <select
          disabled={submitting || readonlyDomain}
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
        <span>{Copy.topicLabel}</span>
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
        <span>{Copy.descriptionLabel}</span>
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
          {Copy.cancel}
        </button>
        <button className="btn btn-primary" disabled={submitting} onClick={onSubmit} type="button">
          {submitting ? Copy.submitting : submitLabel}
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
 * 为什么不用原生 `<dialog>.showModal()`：jsdom 未实现 showModal/close/show
 * （三者全为 undefined），而前端测试环境是 jsdom；且 `showModal()` 的 top layer
 * 会把包含块从 .device-screen 换成视口，确认单在宽视口下变成 `--phone-shell-max` 宽
 * （实测 left 445 → 400、width 390 → 480）而甩出手机外壳——那条 transform 是
 * global.css 的承重属性，其注释明文点名它存在的目的之一就是让 .confirm-sheet 收进外壳。
 * 模态语义由 shared/ui/ConfirmSheet 手工补齐（遮罩、焦点进入、焦点陷阱、Esc 关闭、背景 inert），
 * 并如实声称 `aria-modal="true"`。已知残余（比原生模态少一项）：层级由 z-index 而非 top layer 保证。
 *
 * 为什么归档要在单内二次确认、改名与恢复不用：归档改变后续会话的默认对象，
 * 而改名可再改、恢复可逆。
 */
export function ObjectSheet(props: ObjectSheetProps) {
  const { kind } = props;
  if (kind === 'menu') {
    return (
      <ConfirmSheet labelledBy="profile-object-title" onDismiss={props.onCancel}>
        <h2 id="profile-object-title">{props.displayName}</h2>
        <div className="button-row">
          <button className="btn btn-secondary" onClick={props.onRename} type="button">
            {Copy.renameRow}
          </button>
          {props.archived ? (
            <button className="btn btn-secondary" onClick={props.onRestore} type="button">
              {Copy.restoreRow}
            </button>
          ) : (
            <button className="btn btn-quiet" onClick={props.onArchive} type="button">
              {Copy.archiveRow}
            </button>
          )}
        </div>
        <div className="button-row">
          <button className="btn btn-quiet" onClick={props.onCancel} type="button">
            {Copy.cancel}
          </button>
        </div>
      </ConfirmSheet>
    );
  }

  const title =
    kind === 'create'
      ? Copy.createSheetTitle
      : kind === 'rename'
        ? Copy.renameRow
        : kind === 'archive'
          ? Copy.archiveTitle
          : Copy.restoreTitle;
  const body =
    kind === 'create'
      ? Copy.createSheetHint
      : kind === 'archive'
        ? Copy.archiveBody
        : kind === 'restore'
          ? Copy.restoreBody
          : null;

  return (
    <ConfirmSheet labelledBy="profile-object-form-title" onDismiss={props.onCancel}>
      <h2 id="profile-object-form-title">{title}</h2>
      {body !== null && <p>{body}</p>}
      {kind === 'create' || kind === 'rename' ? (
        <label className="field">
          <span>{Copy.nameLabel}</span>
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
          {Copy.cancel}
        </button>
        <button
          className={kind === 'archive' ? 'btn btn-danger' : 'btn btn-primary'}
          disabled={props.submitting || ((kind === 'create' || kind === 'rename') && props.name.trim() === '')}
          onClick={props.onSubmit}
          type="button"
        >
          {kind === 'create'
            ? Copy.createSubmit
            : kind === 'rename'
              ? Copy.renameSubmit
              : kind === 'archive'
                ? Copy.archiveSubmit
                : Copy.restoreSubmit}
        </button>
      </div>
    </ConfirmSheet>
  );
}
