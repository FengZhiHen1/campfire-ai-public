/**
 * PROF-07 档案数据逻辑 — 常量定义
 *
 * 所有静态配置数据集中管理，不与 store 或组件逻辑混合。
 *
 * 数据来源:
 *   - PROF-07 落地规范 §1.1, §1.5: MUST — 微问卷题目结构和选项
 *   - PROF-07 设计文档 §1.2: SHOULD — 触发因素预设值
 * 边界:
 *   - 依赖: types/contracts.ts (MicroSurveyQuestion)
 *   - 被依赖: store/microSurveyStore.ts, hooks/useMicroSurvey.ts
 * 禁止行为:
 *   - 禁止在常量中嵌入业务逻辑或状态判断
 *   - 禁止运行时修改这些值——它们是纯常量
 */

import type { MicroSurveyQuestion } from './types/contracts';

/** 干预有效性反馈选项 */
export const INTERVENTION_FEEDBACK_OPTIONS: readonly string[] = ['有帮助', '一般', '无帮助'];

/** 微问卷默认题目（固定 2 题，每次相同） */
export const DEFAULT_QUESTIONS: readonly MicroSurveyQuestion[] = [
  {
    id: 'trigger',
    text: '本次触发了什么因素？',
    type: 'single-choice-with-custom',
  },
  {
    id: 'effectiveness',
    text: '刚才的建议是否有帮助？',
    type: 'single-choice',
    options: [...INTERVENTION_FEEDBACK_OPTIONS],
  },
];

/** 预设触发因素枚举值（用于判断是否为自定义文本） */
export const PRESET_TRIGGERS: readonly string[] = [
  '噪音', '环境变化', '陌生人', '任务中断', '社交压力', '感官过载', '身体不适',
];

/** 判断触发因素值是否为自定义文本（非预设枚举值） */
export function isCustomTrigger(value: string): boolean {
  return !PRESET_TRIGGERS.includes(value);
}

/** 档案数量上限 */
export const MAX_PROFILE_COUNT = 5;

/** 微问卷提交成功后自动关闭延迟（毫秒） */
export const MICRO_SURVEY_AUTO_CLOSE_DELAY = 2000;
