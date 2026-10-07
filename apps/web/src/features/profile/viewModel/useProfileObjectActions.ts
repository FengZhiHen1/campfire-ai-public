/**
 * 模块: features/profile/viewModel/useProfileObjectActions
 * 职责: 对象级交互状态——新建对象、改名、归档、恢复（同一 .confirm-sheet 的三种操作行）
 * 数据来源:
 *   - docs/design/pages/档案页.md: MUST — 「新建对象」「对象操作」两节与状态覆盖表的归档行
 *   - docs/技术设计/面/profile/档案面HTTP契约.md: MUST — 第 2.1、2.2 节
 * 边界:
 *   - 依赖: features/profile/application、features/profile/domain
 *   - 被依赖: features/profile/view/ProfilePage
 * 禁止行为:
 *   - 禁止提供「删除对象」入口（支持对象第 4 节：生命周期无删除）
 *   - 禁止归档后弹成功提示（状态即可见——chip 上加「已归档」标）
 *   - 禁止用 `disabled` 当并发闸门（闸门收进动作函数体，FE-12）
 */

import { useCallback, useRef, useState } from 'react';

import type { SupportObject } from '../../../shared/types/profile';
import type { ProfilePort } from '../application/ports';
import { type ObjectAction, CreateObjectUseCase, UpdateObjectUseCase } from '../application/usecases';
import { type ProfileFailure, failureFromError } from '../domain/failures';
import { type ProfileFieldErrors, ProfileValidationError } from '../domain/formValidation';

/** 对象操作单当前朝哪个方向：对象操作菜单 vs 具体动作 vs 新建对象。 */
export type ObjectSheetKind = 'menu' | 'create' | 'rename' | 'archive' | 'restore';

/** 对象操作单的状态。 */
export interface ObjectSheetState {
  kind: ObjectSheetKind;
  /** 改名的草稿（新建与归档/恢复不用）。 */
  name: string;
  errors: ProfileFieldErrors;
  submitting: boolean;
  failure: ProfileFailure | null;
}

/** 对象级交互状态与操作。 */
export interface ProfileObjectActions {
  sheet: ObjectSheetState | null;
  /** 新建成功后的回调值：调用方据此把 chip 自动切到新对象。 */
  openCreate(): void;
  /** 打开当前对象的操作菜单（改名 / 归档 / 恢复）。 */
  openMenu(): void;
  openRename(current: SupportObject): void;
  openArchive(): void;
  openRestore(): void;
  closeSheet(): void;
  updateName(name: string): void;
  submit(): Promise<string | null>;
}

/**
 * 对象级交互状态。
 *
 * @param port 档案端口
 * @param selected 当前选中的对象；`rename/archive/restore` 需要它，为 null 时这些
 *   入口根本不该出现（没有对象就没有「当前对象」）
 * @param onChanged 操作成功后重新加载对象列表与内容区
 */
export function useProfileObjectActions(
  port: ProfilePort,
  selected: SupportObject | null,
  onChanged: () => Promise<void>,
): ProfileObjectActions {
  const [sheet, setSheet] = useState<ObjectSheetState | null>(null);
  // 并发闸门收进动作函数体（FE-12）：单内的提交按钮带 disabled，但它管不住回车与
  // 重复点按（同一 sheet 的提交入口不止一个：新建、改名、归档、恢复共用本函数）。
  const inFlight = useRef(false);

  const openCreate = useCallback((): void => {
    setSheet({ kind: 'create', name: '', errors: {}, submitting: false, failure: null });
  }, []);

  const openMenu = useCallback((): void => {
    setSheet({ kind: 'menu', name: '', errors: {}, submitting: false, failure: null });
  }, []);

  const openRename = useCallback((current: SupportObject): void => {
    setSheet({ kind: 'rename', name: current.display_name, errors: {}, submitting: false, failure: null });
  }, []);

  const openArchive = useCallback((): void => {
    setSheet({ kind: 'archive', name: '', errors: {}, submitting: false, failure: null });
  }, []);

  const openRestore = useCallback((): void => {
    setSheet({ kind: 'restore', name: '', errors: {}, submitting: false, failure: null });
  }, []);

  const closeSheet = useCallback((): void => {
    setSheet(null);
  }, []);

  const updateName = useCallback((name: string): void => {
    setSheet((current) => (current === null ? null : { ...current, name, errors: {} }));
  }, []);

  /**
   * 提交当前 sheet。
   *
   * 前置: sheet 非空且 kind 不是 menu
   * 后置: 新建时返回新对象标识（调用方据此切换 chip）；其余情形返回 null
   * 并发: 已有提交在途时立即返回 null（闸门在函数体内，不看按钮 disabled）
   * 异常: 不抛出——失败分类后留在 sheet 内呈现（归档须在 sheet 内二次确认）
   */
  const submit = useCallback(async (): Promise<string | null> => {
    const current = sheet;
    if (current === null) return null;
    if (current.kind === 'menu') return null;
    // 闸门在函数体内：重复点按 / 回车在这里被拒绝，不依赖按钮是否 disabled。
    if (inFlight.current) return null;
    inFlight.current = true;
    setSheet({ ...current, submitting: true, failure: null, errors: {} });
    try {
      if (current.kind === 'create') {
        const created = await new CreateObjectUseCase(port).execute(current.name);
        setSheet(null);
        await onChanged();
        return created.id;
      }
      if (selected === null) return null;
      const action: ObjectAction =
        current.kind === 'archive'
          ? { kind: 'archive' }
          : current.kind === 'restore'
            ? { kind: 'restore' }
            : { kind: 'rename', displayName: current.name };
      await new UpdateObjectUseCase(port).execute(selected.id, action);
      setSheet(null);
      await onChanged();
      return null;
    } catch (error) {
      if (error instanceof ProfileValidationError) {
        setSheet({ ...current, submitting: false, errors: error.fieldErrors });
        return null;
      }
      setSheet({ ...current, submitting: false, failure: failureFromError(error) });
      return null;
    } finally {
      inFlight.current = false;
    }
  }, [onChanged, port, selected, sheet]);

  return { sheet, openCreate, openMenu, openRename, openArchive, openRestore, closeSheet, updateName, submit };
}
