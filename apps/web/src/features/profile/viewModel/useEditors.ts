/**
 * 模块: features/profile/viewModel/useEditors
 * 职责: 补充与纠正两个互斥表单的「打开 / 切换」协调——未保存草稿的丢弃确认、切换对象时的草稿保护
 * 数据来源:
 *   - docs/design/pages/档案页.md: MUST — 功能语义审查修订（纠正领域只读；补充与纠正互斥；
 *     对象切换保护未保存草稿）
 * 边界:
 *   - 依赖: features/profile/viewModel/useProfileEntryActions（两个表单的状态与动作）、
 *     features/profile/domain/formValidation（空草稿判据）
 *   - 被依赖: features/profile/view/ProfilePage
 * 禁止行为:
 *   - 禁止在这里另写一份「是否已编辑」的判断（复用 domain 的空草稿判据，档案页第 98 行）
 *   - 禁止在 view 里散落「先关一个再开另一个」的顺序（互斥是流程控制，不是排版）
 *
 * 为什么抽出来：这段逻辑（打开哪个表单、何时弹丢弃确认、切换对象前是否拦下）是档案页里
 * 唯一的复合流程控制；原本与绘制混在 800 余行的视图组件里，两者改动理由不同。
 * 表单状态本身仍归 useProfileEntryActions（写路径与并发闸门在那里）。
 */

import { useCallback, useState } from 'react';

import type { ProfileItem } from '../../../shared/types/profile';
import { itemDraftChanged } from '../domain/formValidation';
import type { ProfileEntryActions } from './useProfileEntryActions';

/** 编辑器目标：补充表单，或针对某一条的纠正表单。 */
type EditorTarget = { kind: 'add' } | { kind: 'correct'; item: ProfileItem };

/** 一次待确认的「放弃当前编辑」动作。 */
export type PendingEditorSwitch =
  | { kind: 'open-editor'; target: EditorTarget }
  | { kind: 'switch-object'; objectId: string };

/** 补充与纠正的表单协调状态与操作。 */
export interface ProfileEditors {
  /** 有未保存草稿又要求切换编辑器时，待确认的动作；非空即渲染放弃确认单。 */
  pendingSwitch: PendingEditorSwitch | null;
  /** 两个表单任一在提交中（切换器据此禁用，避免提交中切换对象）。 */
  busy: boolean;
  /** 切换支持对象；有草稿时先挂起并弹确认。 */
  requestSwitchObject(objectId: string): void;
  /** 打开纠正表单（有草稿时先弹确认）。 */
  requestCorrect(item: ProfileItem): void;
  /** 打开补充表单（有草稿时先弹确认）。 */
  requestAdd(): void;
  /** 放弃当前编辑并继续挂起的动作。 */
  discardAndContinue(): void;
  /** 视为继续编辑：清掉待确认，保留草稿。 */
  keepEditing(): void;
}

/**
 * 补充与纠正的表单协调。
 *
 * @param entry 条目级动作 hook（持有两个表单的状态与开关）
 * @param onSwitchObject 确认丢弃草稿后真正执行的对象切换
 */
export function useProfileEditors(
  entry: ProfileEntryActions,
  onSwitchObject: (objectId: string) => void,
): ProfileEditors {
  const [pendingSwitch, setPendingSwitch] = useState<PendingEditorSwitch | null>(null);

  // 「已编辑」用 domain 的空草稿判据，不在这里另写一份比较：补充分支的领域默认落在兜底项
  // 且可以改，只比主题与描述会漏掉「先选好领域」这一次显式选择（档案页第 98 行要求保护
  // 未保存草稿）。纠正流的领域是只读的，因此那一边只需比可改的两个字段。
  const hasDraft =
    (entry.add !== null && itemDraftChanged(entry.add.draft)) ||
    (entry.correct !== null &&
      (entry.correct.draft.topic !== entry.correct.target.topic ||
        entry.correct.draft.description !== entry.correct.target.description));

  const busy =
    entry.busyItemId !== null || entry.correct?.submitting === true || entry.add?.submitting === true;

  const requestSwitchObject = useCallback(
    (objectId: string): void => {
      if (hasDraft) {
        setPendingSwitch({ kind: 'switch-object', objectId });
        return;
      }
      onSwitchObject(objectId);
    },
    [hasDraft, onSwitchObject],
  );

  const requestCorrect = useCallback(
    (item: ProfileItem): void => {
      if (entry.correct?.target.item_id === item.item_id) return;
      if (hasDraft) {
        setPendingSwitch({ kind: 'open-editor', target: { kind: 'correct', item } });
        return;
      }
      entry.closeAdd();
      entry.openCorrect(item);
    },
    [entry, hasDraft],
  );

  const requestAdd = useCallback((): void => {
    if (entry.add !== null) return;
    if (hasDraft) {
      setPendingSwitch({ kind: 'open-editor', target: { kind: 'add' } });
      return;
    }
    entry.closeCorrect();
    entry.openAdd();
  }, [entry, hasDraft]);

  const discardAndContinue = useCallback((): void => {
    const pending = pendingSwitch;
    setPendingSwitch(null);
    if (pending === null) return;
    if (pending.kind === 'switch-object') {
      entry.closeAdd();
      entry.closeCorrect();
      onSwitchObject(pending.objectId);
      return;
    }
    entry.closeAdd();
    entry.closeCorrect();
    if (pending.target.kind === 'add') entry.openAdd();
    else entry.openCorrect(pending.target.item);
  }, [entry, onSwitchObject, pendingSwitch]);

  const keepEditing = useCallback((): void => {
    setPendingSwitch(null);
  }, []);

  return {
    pendingSwitch,
    busy,
    requestSwitchObject,
    requestCorrect,
    requestAdd,
    discardAndContinue,
    keepEditing,
  };
}
