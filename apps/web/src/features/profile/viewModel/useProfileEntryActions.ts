/**
 * 模块: features/profile/viewModel/useProfileEntryActions
 * 职责: 条目级交互状态——确认/否定候选、纠正、删除二次确认、补充条目
 * 数据来源:
 *   - docs/design/pages/档案页.md: MUST — 状态覆盖表（删除确认/纠正流/写入失败保留已填内容）
 *   - docs/技术设计/面/profile/档案面HTTP契约.md: MUST — 第 4、5 节（确认/纠正/删除/补充）
 * 边界:
 *   - 依赖: features/profile/application、features/profile/domain
 *   - 被依赖: features/profile/view/ProfilePage
 * 禁止行为:
 *   - 禁止在失败时清空已填内容（档案页状态覆盖表：保留已填内容，不清空）
 *   - 禁止把纠正写成「修改」（纠正 = 新增更正，原记录不再作为依据）
 *   - 禁止用 `disabled` 当并发闸门（闸门收进动作函数体，FE-12）
 */

import { useCallback, useRef, useState } from 'react';

import type { ProfileItem } from '../../../shared/types/profile';
import type { ProfilePort } from '../application/ports';
import { AddItemUseCase, ConfirmItemUseCase, CorrectItemUseCase, DeleteItemUseCase } from '../application/usecases';
import { type ProfileFailure, failureFromError, profileFailureInline } from '../domain/failures';
import { DOMAIN_FALLBACK } from '../domain/domains';
import { type ItemDraft, type ProfileFieldErrors, ProfileValidationError } from '../domain/formValidation';
/** 纠正流的状态：草稿在提交失败后必须原样保留。 */
export interface CorrectFlowState {
  target: ProfileItem;
  draft: ItemDraft;
  errors: ProfileFieldErrors;
  submitting: boolean;
  failure: ProfileFailure | null;
}

/** 补充条目的状态。 */
export interface AddFlowState {
  draft: ItemDraft;
  errors: ProfileFieldErrors;
  submitting: boolean;
  failure: ProfileFailure | null;
}

/** 条目级交互状态与操作。 */
export interface ProfileEntryActions {
  /**
   * 正在处理的行（确认/否定/删除共用一处，避免同一行并发两个写操作）。
   * 它只作展示提示：真正的闸门在动作函数体内（见 `inFlight`）。
   */
  busyItemId: string | null;
  /** 行内错误：哪一行、什么原因。 */
  rowFailure: { itemId: string; failure: ProfileFailure } | null;
  /** 待删除确认的条目；非空即渲染 .confirm-sheet。 */
  deleteTarget: ProfileItem | null;
  correct: CorrectFlowState | null;
  add: AddFlowState | null;
  /** 一次性提示（纠正成功等）；它不是错误，因此与 rowFailure 分开。 */
  notice: string | null;

  confirmCandidate(itemId: string): Promise<void>;
  /** 逐字对应档案页第 24 行的「删除」；否定（契约 4.1）没有界面入口，见端口说明。 */
  askDelete(item: ProfileItem): void;
  cancelDelete(): void;
  confirmDelete(): Promise<void>;

  openCorrect(item: ProfileItem): void;
  closeCorrect(): void;
  updateCorrectDraft(patch: Partial<ItemDraft>): void;
  submitCorrect(): Promise<void>;

  openAdd(): void;
  closeAdd(): void;
  updateAddDraft(patch: Partial<ItemDraft>): void;
  submitAdd(): Promise<void>;

  dismissNotice(): void;
}

/** 空草稿：领域默认落在兜底项，使用者可以改。 */
function emptyDraft(): ItemDraft {
  return { domain: DOMAIN_FALLBACK, topic: '', description: '' };
}

/**
 * 条目级交互状态。
 *
 * @param port 档案端口
 * @param objectId 当前对象；为 null 时所有提交都会被拒（没有对象可写）
 * @param archived 当前对象是否已归档；为真时新增与纠正按契约第 1 节返回 409，
 *   这里不预先禁用按钮——禁用会让使用者看不到原因，而 409 的文案正是解释
 * @param onChanged 条目发生变化后重新加载内容区（确认/否定/删除/纠正/补充都走它）
 */
export function useProfileEntryActions(
  port: ProfilePort,
  objectId: string | null,
  onChanged: () => Promise<void>,
): ProfileEntryActions {
  const [busyItemId, setBusyItemId] = useState<string | null>(null);
  const [rowFailure, setRowFailure] = useState<{ itemId: string; failure: ProfileFailure } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ProfileItem | null>(null);
  const [correct, setCorrect] = useState<CorrectFlowState | null>(null);
  const [add, setAdd] = useState<AddFlowState | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  /*
    并发闸门收进动作函数体（FE-12）：`disabled` 管不住重复点按、回车与程序化调用，
    而同一个动作函数有多个入口（行内按钮、确认单、表单提交）。
    闸门覆盖全部条目写操作：同一时刻只允许一个在途（同一行的并发写、跨行的并发写都会
    互相覆盖 busyItemId 或与随后的重载竞争，因此不按行分闸门）。
  */
  const inFlight = useRef(false);

  /** 行内单条目操作的共用骨架：置忙 → 执行 → 失败分类 → 成功重载。 */
  const runRowAction = useCallback(
    async (itemId: string, action: () => Promise<void>): Promise<void> => {
      // 闸门在函数体内：所有入口（行内按钮 / 确认单）都过同一道，不看按钮是否 disabled。
      if (inFlight.current) return;
      inFlight.current = true;
      setBusyItemId(itemId);
      setRowFailure(null);
      try {
        await action();
        await onChanged();
      } catch (error) {
        setRowFailure({ itemId, failure: failureFromError(error) });
      } finally {
        inFlight.current = false;
        setBusyItemId(null);
      }
    },
    [onChanged],
  );

  const confirmCandidate = useCallback(
    async (itemId: string): Promise<void> => {
      await runRowAction(itemId, () => new ConfirmItemUseCase(port).execute(itemId));
    },
    [port, runRowAction],
  );

  const askDelete = useCallback((item: ProfileItem): void => {
    setDeleteTarget(item);
  }, []);

  const cancelDelete = useCallback((): void => {
    setDeleteTarget(null);
  }, []);

  const confirmDelete = useCallback(async (): Promise<void> => {
    const target = deleteTarget;
    if (target === null) return;
    setDeleteTarget(null);
    await runRowAction(target.item_id, () => new DeleteItemUseCase(port).execute(target.item_id));
  }, [deleteTarget, port, runRowAction]);

  const openCorrect = useCallback((item: ProfileItem): void => {
    // 预填原描述（档案页第 62 行）：纠正是在原文上改，不是从空白写起。
    setCorrect({
      target: item,
      draft: { domain: item.domain, topic: item.topic, description: item.description },
      errors: {},
      submitting: false,
      failure: null,
    });
  }, []);

  const closeCorrect = useCallback((): void => {
    setCorrect(null);
  }, []);

  const updateCorrectDraft = useCallback((patch: Partial<ItemDraft>): void => {
    setCorrect((current) => (current === null ? null : { ...current, draft: { ...current.draft, ...patch }, errors: {} }));
  }, []);

  const submitCorrect = useCallback(async (): Promise<void> => {
    const current = correct;
    if (current === null) return;
    // 闸门（FE-12）：提交按钮的 disabled 之外还有回车键与重复点按。
    if (inFlight.current) return;
    inFlight.current = true;
    setCorrect({ ...current, submitting: true, failure: null, errors: {} });
    try {
      await new CorrectItemUseCase(port).execute(current.target.item_id, current.draft, current.target.description);
      setCorrect(null);
      // 纠正 = 新增一条更正，旧记录不再作为依据（档案文档第 3 节不变量 3：不物理覆盖）。
      setNotice('已新增一条更正，原记录不再作为依据');
      await onChanged();
    } catch (error) {
      if (error instanceof ProfileValidationError) {
        // 校验失败是「这次表单没填对」，按钮可立即再按——因此不留在提交中状态。
        setCorrect({ ...current, submitting: false, failure: null, errors: error.fieldErrors });
        return;
      }
      // 提交失败保留已填内容（档案页状态覆盖表）：只加失败原因，草稿不动。
      setCorrect({ ...current, submitting: false, failure: failureFromError(error) });
    } finally {
      inFlight.current = false;
    }
  }, [correct, onChanged, port]);

  const openAdd = useCallback((): void => {
    setAdd({ draft: emptyDraft(), errors: {}, submitting: false, failure: null });
  }, []);

  const closeAdd = useCallback((): void => {
    setAdd(null);
  }, []);

  const updateAddDraft = useCallback((patch: Partial<ItemDraft>): void => {
    setAdd((current) => (current === null ? null : { ...current, draft: { ...current.draft, ...patch }, errors: {} }));
  }, []);

  const submitAdd = useCallback(async (): Promise<void> => {
    const current = add;
    if (current === null || objectId === null) return;
    // 闸门（FE-12）：与纠正共用同一道——两个表单不会同时在途。
    if (inFlight.current) return;
    inFlight.current = true;
    setAdd({ ...current, submitting: true, failure: null, errors: {} });
    try {
      await new AddItemUseCase(port).execute(objectId, current.draft);
      setAdd(null);
      setNotice('已补充一条记录');
      await onChanged();
    } catch (error) {
      if (error instanceof ProfileValidationError) {
        setAdd({ ...current, submitting: false, failure: null, errors: error.fieldErrors });
        return;
      }
      setAdd({ ...current, submitting: false, failure: failureFromError(error) });
    } finally {
      inFlight.current = false;
    }
  }, [add, objectId, onChanged, port]);

  const dismissNotice = useCallback((): void => {
    setNotice(null);
  }, []);

  return {
    busyItemId,
    rowFailure,
    deleteTarget,
    correct,
    add,
    notice,
    confirmCandidate,
    askDelete,
    cancelDelete,
    confirmDelete,
    openCorrect,
    closeCorrect,
    updateCorrectDraft,
    submitCorrect,
    openAdd,
    closeAdd,
    updateAddDraft,
    submitAdd,
    dismissNotice,
  };
}

/**
 * 取某一行的行内错误文案；不是这一行的失败返回 null。
 *
 * 为什么单独出一个函数而不是在 JSX 里用可选链比较：`entry.rowFailure?.itemId === id`
 * 无法把 `entry.rowFailure` 收窄成非空（比较的结果不携带这个信息），
 * 于是取 `.failure` 时类型上仍是可能为空的引用。收在一处后，判空与取值在同一个
 * 能收窄的分支里完成。
 */
export function inlineFailureFor(
  rowFailure: { itemId: string; failure: ProfileFailure } | null,
  itemId: string,
): string | null {
  if (rowFailure === null || rowFailure.itemId !== itemId) return null;
  return profileFailureInline(rowFailure.failure);
}
