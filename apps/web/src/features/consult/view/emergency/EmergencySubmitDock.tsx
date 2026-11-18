/**
 * 模块: features/consult/view/emergency/EmergencySubmitDock
 * 职责: 常驻屏底拇指区的提交区——跳过/下一题/提交三键，提交意义与推进明显区分
 * 数据来源:
 *   - apps/web/src/features/consult/viewModel/useEmergencyForm.ts: MUST — submit / submitting / isLast
 *   - docs/design/pages/应急表单页.md: MUST — 底部控制区常驻屏幕、随时提交、拇指可达、安全区预留
 * 边界:
 *   - 依赖: React
 *   - 被依赖: view/EmergencyFormPage
 * 禁止行为:
 *   - 禁止把提交做成与「下一题」同形的次要按钮（页面设计：提交意义须一眼可辨）
 *   - 禁止删掉外层 emergency-controls 钩子（e2e 中和 fixed 用，由页面挂在本区上）
 *   - 禁止在提交中仍可点（三键 disabled，提交键提示「正在提交…」）
 */

import styles from './emergencyForm.module.css';

/** 提交区 props。 */
export interface EmergencySubmitDockProps {
  isLast: boolean;
  submitting: boolean;
  onSkip(): void;
  onNext(): void;
  onSubmit(): void;
}

/**
 * 渲染常驻提交区。
 *
 * 前置: 无
 * 后置: 恒定三键（跳过这题 / 下一题 / 提交，开始分析）；末题时下一题禁用；
 *       提交中三键禁用且提交键文案为「正在提交…」；附一句「随时提交」说明
 * 异常: 无
 *
 * 三键意义
 *   跳过这题（次要）与下一题（次要）都是「不提交、继续」；
 *   提交（主色、整宽、独占一行）是「现在就开始分析」——形状与层级把两者分开。
 */
export function EmergencySubmitDock({ isLast, submitting, onSkip, onNext, onSubmit }: EmergencySubmitDockProps) {
  return (
    <div className={styles.dockInner}>
      <div className={styles.dockPush}>
        <button type="button" className={styles.dockSkip} disabled={submitting} onClick={onSkip}>
          跳过这题
        </button>
        <button type="button" className={styles.dockNext} disabled={isLast || submitting} onClick={onNext}>
          下一题
        </button>
      </div>
      <button type="button" className={styles.dockSubmit} disabled={submitting} onClick={onSubmit}>
        {submitting ? '正在提交…' : '提交，开始分析'}
      </button>
      <p className={styles.dockHint}>随时提交，无需答完八题。</p>
    </div>
  );
}
