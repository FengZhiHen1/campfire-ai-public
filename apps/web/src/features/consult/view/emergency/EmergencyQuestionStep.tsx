/**
 * 模块: features/consult/view/emergency/EmergencyQuestion
 * 职责: 当前题的题面与作答控件——单选/多选/自由文本，整行热区、单层选择行
 * 数据来源:
 *   - apps/web/src/features/consult/viewModel/useEmergencyForm.ts: MUST — current / answer / 作答回调
 *   - apps/web/src/features/consult/domain/emergency.ts: MUST — EmergencyQuestion 的控件形态与选项
 *   - docs/design/pages/应急表单页.md: MUST — 题干 ≥16px、选项 ≥16px、整行可点、第七项 textarea、
 *     单选圆形 / 多选方形指示、不预选事实答案
 * 边界:
 *   - 依赖: React、domain/emergency 的 EmergencyQuestion、控制器回调
 *   - 被依赖: view/EmergencyFormPage
 * 禁止行为:
 *   - 禁止预选任何事实答案（进入某题时所有控件都未选中）
 *   - 禁止把第七项自由文本做成必填或校验（写不清可以跳过）
 *   - 禁止保存行为偏离 domain：单选再点同一项不取消（域层 selectOption 决定）
 */

import type { EmergencyAnswerDraft, EmergencyQuestion } from '../../domain/emergency';
import styles from './emergencyForm.module.css';

/** 题面组件 props。 */
export interface EmergencyQuestionProps {
  /** 当前题。 */
  question: EmergencyQuestion;
  /** 当前题草稿（选中项、补充文本、是否跳过）。 */
  answer: EmergencyAnswerDraft;
  /** 多选切换一项。 */
  onToggle(value: string): void;
  /** 单选选中一项。 */
  onChoose(value: string): void;
  /** 写入自由补充文本。 */
  onNote(text: string): void;
  /** 提交中锁定输入（载荷按下按钮时已确定）。 */
  disabled: boolean;
}

/**
 * 渲染当前题的题面与控件。
 *
 * 前置: question 与 answer 对应同一题
 * 后置: 输出题干（h2#emergency-step-title）、提示、选项组；单选/多选整行可点，
 *       第七项输出 textarea；允许补充的题在选项后追加一个可选的 textarea
 * 异常: 无
 */
export function EmergencyQuestionStep({
  question,
  answer,
  onToggle,
  onChoose,
  onNote,
  disabled,
}: EmergencyQuestionProps) {
  return (
    <>
      <h2 className={styles.questionTitle} id="emergency-step-title" tabIndex={-1}>
        {question.prompt}
      </h2>
      <p className={styles.questionHint}>{question.hint}</p>

      <div className={styles.options} role="group" aria-labelledby="emergency-step-title">
        {question.control === 'text' ? (
          <div className={styles.field}>
            <label className={styles.fieldLabel} htmlFor="emergency-note">
              刚刚发生了什么
            </label>
            <textarea
              id="emergency-note"
              className={styles.textarea}
              value={answer.note}
              onChange={(event) => onNote(event.target.value)}
              placeholder="一两句话就够，写不清也可以跳过。"
              disabled={disabled}
            />
          </div>
        ) : (
          question.options.map((option) => {
            const checked = answer.selected.includes(option.value);
            const isMulti = question.control === 'multi';
            return (
              <label className={styles.option} key={option.value} data-checked={checked ? 'true' : undefined}>
                <input
                  type={isMulti ? 'checkbox' : 'radio'}
                  name={question.key}
                  value={option.value}
                  checked={checked}
                  disabled={disabled}
                  onChange={() => (isMulti ? onToggle(option.value) : onChoose(option.value))}
                />
                <span className={styles.optionMark} aria-hidden="true" />
                <span className={styles.optionLabel}>{option.label}</span>
              </label>
            );
          })
        )}
      </div>

      {question.allowNote && question.control !== 'text' ? (
        <div className={styles.field}>
          <label className={styles.fieldLabel} htmlFor="emergency-extra">
            补充一句（可选）
          </label>
          <textarea
            id="emergency-extra"
            className={styles.textarea}
            value={answer.note}
            onChange={(event) => onNote(event.target.value)}
            placeholder="可以补一句你观察到的样子。"
            disabled={disabled}
          />
        </div>
      ) : null}
    </>
  );
}
