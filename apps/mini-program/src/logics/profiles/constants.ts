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
import { Trigger } from '@campfire/ts-shared';

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

/** 所有预设触发因素值 */
const ALL_TRIGGERS: readonly string[] = Object.values(Trigger);

/** 判断触发因素值是否为自定义文本（非预设 Trigger 枚举值） */
export function isCustomTrigger(value: string): boolean {
  return !ALL_TRIGGERS.includes(value);
}

/** 诊断类型选项 */
export const DIAGNOSIS_OPTIONS: readonly string[] = ['ASD', '疑似ASD', '其他发育障碍'];

/** 主要行为类型选项 */
export const BEHAVIOR_OPTIONS: readonly string[] = ['刻板行为', '情绪崩溃', '自伤行为', '攻击行为', '社交退缩', '多动'];

/** 严重程度选项 */
export const SEVERITY_OPTIONS: readonly string[] = ['轻', '中', '重'];

/** 发生场景选项 */
export const SETTING_OPTIONS: readonly string[] = ['家庭', '学校', '公共场合', '机构'];

/** 预设标签 */
export const PRESET_TAGS: readonly string[] = [
  '感官敏感', '睡眠障碍', '社交回避', '语言发育迟缓',
  '刻板行为', '注意力缺陷', '情绪调节困难', '饮食挑剔', '如厕困难', '分离焦虑',
];

/** 档案数量上限 */
export const MAX_PROFILE_COUNT = 5;

/** 微问卷提交成功后自动关闭延迟（毫秒） */
export const MICRO_SURVEY_AUTO_CLOSE_DELAY = 2000;

/** 档案昵称最小长度 */
export const NICKNAME_MIN_LENGTH = 2;

/** 档案昵称最大长度 */
export const NICKNAME_MAX_LENGTH = 20;

/** 自定义标签最大长度 */
export const CUSTOM_TAG_MAX_LENGTH = 10;

/** 保存失败通知自动消失延迟（毫秒） */
export const ERROR_AUTO_DISMISS_MS = 3000;
