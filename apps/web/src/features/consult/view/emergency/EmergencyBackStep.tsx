/**
 * 模块: features/consult/view/emergency/EmergencyBackStep
 * 职责: 采集区里的「上一题」回退——只承担回退，前进与跳过归屏底常驻提交区
 * 数据来源:
 *   - apps/web/src/features/consult/viewModel/useEmergencyForm.ts: MUST — previous / isFirst
 *   - docs/design/pages/应急表单页.md: MUST — 「上一题保留在采集区」，跳过/下一题与提交在底部控制区
 * 边界:
 *   - 依赖: React
 *   - 被依赖: view/EmergencyFormPage
 * 禁止行为:
 *   - 禁止在此再放「跳过」「下一题」：它们归底部常驻区，两处各放一份会把三键语义弄乱
 *   - 禁止在首题渲染「上一题」：首题没有上一题，留一个 44px 的禁用按钮只会抢占第一题首屏
 *     （页面设计第一题要 10 秒内可提交）。后续题才渲染它。
 */

import styles from './emergencyForm.module.css';

/** 上一题 props。 */
export interface EmergencyBackStepProps {
  isFirst: boolean;
  disabled: boolean;
  onPrevious(): void;
}

/**
 * 渲染采集区里的上一题按钮。
 *
 * 前置: 无
 * 后置: 首题不渲染（无上一题）；后续题渲染，提交中禁用
 * 异常: 无
 */
export function EmergencyBackStep({ isFirst, disabled, onPrevious }: EmergencyBackStepProps) {
  if (isFirst) return null;
  return (
    <button type="button" className={styles.pushBack} disabled={disabled} onClick={onPrevious}>
      <span aria-hidden="true">←</span> 上一题
    </button>
  );
}
