/**
 * 模块: @campfire/ts-shared.profiles.enums
 * 职责: 档案管理域的前端枚举定义——诊断类型、语言水平、感官特征、触发因素、年龄区间、行为类型。
 *       枚举值为后端数据库存储值，前端展示文案由 mini-program 的 i18n/常量层负责映射。
 * 数据来源:
 *   - py-schemas (profile_enums): MUST — 后端 Python 枚举
 *   - PROF-01/PROF-03 设计文档: SHOULD — 字段语义和取值范围
 * 边界:
 *   - 依赖: 无
 *   - 被依赖: profiles.types.ts、profiles.contract.ts、mini-program
 * 禁止行为:
 *   - 禁止在枚举值中嵌入中文展示文案——展示层应独立映射
 *   - 禁止定义与后端枚举值不一致的字符串
 */

/** 诊断类型（持久化值以后端 py-schemas 为准） */
export enum DiagnosisType {
  ASD = 'ASD',
  SUSPECTED_ASD = '疑似ASD',
  OTHER_DEVELOPMENTAL_DISORDER = '其他发育障碍',
}

/** 语言水平 */
export enum LanguageLevel {
  NON_VERBAL = 'non_verbal',
  SINGLE_WORDS = 'single_words',
  SHORT_PHRASES = 'short_phrases',
  CONVERSATIONAL = 'conversational',
}

/** 感官特征——枚举值与后端 py-schemas SensoryFeature StrEnum 一致 */
export enum SensoryFeature {
  AUDITORY_SENSITIVITY = '听觉敏感',
  TACTILE_SENSITIVITY = '触觉敏感',
  GUSTATORY_SENSITIVITY = '味觉敏感',
  VISUAL_SENSITIVITY = '视觉敏感',
  VESTIBULAR_SEEKING = '前庭寻求',
  PROPRIOCEPTIVE_SEEKING = '本体觉寻求',
}

/** 触发因素——枚举值与后端 py-schemas Trigger StrEnum 一致 */
export enum Trigger {
  NOISE = '噪音',
  ENVIRONMENTAL_CHANGE = '环境变化',
  STRANGER = '陌生人',
  TASK_INTERRUPTION = '任务中断',
  SOCIAL_PRESSURE = '社交压力',
  SENSORY_OVERLOAD = '感官过载',
  PHYSICAL_DISCOMFORT = '身体不适',
}

/** 年龄区间——服务端实时计算，展示文案由 mini-program 映射 */
export enum AgeRange {
  INFANT = '0-3',
  PRESCHOOL = '4-6',
  SCHOOL_AGE = '7-12',
  TEEN = '13-18',
  ADULT = '18+',
}

/** 档案行为类型（持久化值以后端 py-schemas 为准） */
export enum ProfileBehaviorType {
  SELF_INJURY = '自伤行为',
  AGGRESSION = '攻击行为',
  MELTDOWN = '情绪崩溃',
  STEREOTYPY = '刻板行为',
  SOCIAL_WITHDRAWAL = '社交退缩',
  HYPERACTIVITY = '多动',
}
