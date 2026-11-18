/**
 * 模块: features/consult/view/emergency/EmergencyProgress
 * 职责: 应急采集的进度——每一步一个小段，标出已作答、已跳过与当前题；满足「进度一眼可读」
 * 数据来源:
 *   - apps/web/src/features/consult/viewModel/useEmergencyForm.ts: MUST — steps / index / currentStatus
 *   - docs/design/pages/应急表单页.md: MUST — 进度条位置感、截图断言的 role="progressbar"
 *     与 aria-valuemin/max/now（e2e 依赖这些属性与 `.progress-track` 字面类名）
 * 边界:
 *   - 依赖: React、useEmergencyForm 的 EmergencyStepStatus
 *   - 被依赖: view/EmergencyFormPage
 * 禁止行为:
 *   - 禁止显示百分比数字（页面设计布局结构第 2 条）
 *   - 禁止把 role/aria 放在探测用的隐藏元素上：语义必须挂在真正可见的分段条上
 *     （用 CSS Modules 的 :global 局部声明把契约 .progress-track 的 2px 细条改成 6px 分段容器）
 *   - 禁止只靠颜色区分三种状态（再叠形状：实心=已作答、斜纹=已跳过、空心=未作答）
 */

import type { EmergencyStepStatus } from '../../viewModel/useEmergencyForm';
import styles from './emergencyForm.module.css';

/** 进度组件 props。 */
export interface EmergencyProgressProps {
  /** 八题各自的现场状态（含题 key；顺序即题号顺序）。 */
  steps: readonly { key: string; status: EmergencyStepStatus }[];
  /** 当前题下标（0 起）。 */
  index: number;
  /** 当前题是否已跳过（用于在进度行标注「本题已跳过（按未排除处理）」）。 */
  currentSkipped: boolean;
}

/** 每个状态对应的可读标签，给段落的辅助文本用（读屏能听到「第 N 题 已跳过」）。 */
function statusLabel(status: EmergencyStepStatus): string {
  if (status === 'answered') return '已作答';
  if (status === 'skipped') return '已跳过';
  return '未作答';
}

/**
 * 渲染分段进度。
 *
 * 前置: steps 非空且顺序与题号一致
 * 后置:
 *   - 可见的分段条本身承载 role="progressbar" 与 aria-valuemin/max/now，
 *     同时带契约字面类名 `progress-track`（e2e 靠它取位置量）；
 *   - 每段用 data-status 表达状态（实心/斜纹/空心 + 当前题外描边）给人一眼读出进展；
 *   - 一行文字「第 N / 8 题」与「已处理 X / 8 题」及逐题读屏摘要。
 * 异常: 无
 */
export function EmergencyProgress({ steps, index, currentSkipped }: EmergencyProgressProps) {
  const current = index + 1;
  const handled = steps.filter((step) => step.status !== 'unanswered').length;

  return (
    <div className={styles.progress}>
      {/* 语义与可见分段合为一体：role/aria 与字面类名落在真正可见的这一层。 */}
      <div
        className={`progress-track ${styles.progressTrack}`}
        role="progressbar"
        aria-label="采集题目位置"
        aria-valuemin={1}
        aria-valuemax={steps.length}
        aria-valuenow={current}
      >
        {steps.map((step, position) => (
          <span
            key={step.key}
            className={styles.segment}
            data-status={step.status}
            data-current={position === index ? 'true' : undefined}
            aria-hidden="true"
          />
        ))}
      </div>
      <p className={styles.progressText}>
        {/* 题号保持单一文本节点「第 N / 8 题」：demo 截图场景按 exact 文本断言它，
            拆成多个 span 会让 getByText 匹配不到（测试与演示都会红）。 */}
        <span className={styles.progressPosition}>{`第 ${current} / ${steps.length} 题`}</span>
        {/* 「已处理 N / 8 题」是 demo 场景按 `^已处理 ` 锚定读取的一行（含跳过标记）。 */}
        <span className={styles.progressTally} aria-live="polite">
          已处理 {handled} / {steps.length} 题
          {currentSkipped ? ' · 本题已跳过（按未排除处理）' : ''}
        </span>
      </p>
      {/* 逐题状态的读屏摘要：视觉上分段已表达，这里补文字，避免只靠颜色。 */}
      <p className={styles.srOnly}>
        {steps.map((step, position) => `第 ${position + 1} 题${statusLabel(step.status)}`).join('；')}
      </p>
    </div>
  );
}
