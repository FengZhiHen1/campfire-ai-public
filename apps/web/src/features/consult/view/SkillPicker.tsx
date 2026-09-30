/**
 * 模块: features/consult/view/SkillPicker
 * 职责: 技能选择器——「自动」+ 技能 chip，选择只作用于下一条消息
 * 数据来源:
 *   - docs/design/pages/对话页.md: MUST — 布局结构第 3 节（SkillPicker 横向标签条、选中态、发送即消费）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 4.2 节（技能选择器语义）
 * 边界:
 *   - 依赖: domain/types（SkillSummary）
 *   - 被依赖: view 的对话工作面
 * 禁止行为:
 *   - 禁止在这里决定「发送后清空」（消费动作归 viewModel 与适配器）
 *   - 禁止用 emoji 作图标（DESIGN.md 反模式）
 */

import type { SkillSummary } from '../domain/types';

/** 技能选择器 props。 */
export interface SkillPickerProps {
  skills: readonly SkillSummary[];
  /** 当前选择；null = 自动匹配。 */
  selected: string | null;
  /** 选择技能；传 null 表示「自动」。 */
  onSelect(skillId: string | null): void;
  /** 是否禁用（运行中；选择仍可保留，草稿与选择都不清空）。 */
  disabled: boolean;
}

/**
 * 渲染技能选择器。
 *
 * 前置: 无（目录为空时只渲染「自动」，不编造技能）
 * 后置: 输出可横向滚动的 chip 行；当前项以 aria-pressed 标记（不只靠颜色）
 * 异常: 无
 */
export function SkillPicker({ skills, selected, onSelect, disabled }: SkillPickerProps) {
  return (
    <div className="skill-picker" role="group" aria-label="下一条消息使用的技能">
      <button
        type="button"
        className="skill-chip"
        aria-pressed={selected === null}
        disabled={disabled}
        onClick={() => onSelect(null)}
      >
        自动
      </button>
      {skills.map((skill) => (
        <button
          type="button"
          className="skill-chip"
          key={skill.id}
          aria-pressed={selected === skill.id}
          disabled={disabled}
          onClick={() => onSelect(skill.id)}
        >
          {skill.label}
        </button>
      ))}
    </div>
  );
}
