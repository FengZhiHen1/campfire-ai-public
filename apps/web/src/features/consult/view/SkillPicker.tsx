import type { SkillSummary } from '../domain/types';

interface SkillPickerProps {
  skills: readonly SkillSummary[];
  selected: string | null;
  onSelect(skillId: string | null): void;
  disabled: boolean;
}

/** 只展示当前选择，点按后用设备的原生选项界面切换。 */
export function SkillPicker({ skills, selected, onSelect, disabled }: SkillPickerProps) {
  return (
    <label className="skill-picker">
      <span aria-hidden="true">技能</span>
      <select
        aria-label="下一条消息使用的技能"
        value={selected ?? ''}
        disabled={disabled}
        onChange={(event) => onSelect(event.target.value || null)}
      >
        <option value="">自动</option>
        {skills.map((skill) => <option key={skill.id} value={skill.id}>{skill.label}</option>)}
      </select>
    </label>
  );
}
