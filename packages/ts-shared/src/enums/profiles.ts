/** PROF-01 档案相关前端枚举镜像 */

/** 诊断类型 */
export enum DiagnosisType {
  ASD = 'ASD',
  SUSPECTED_ASD = '疑似ASD',
  OTHER_DEVELOPMENTAL_DISORDER = '其他发育障碍',
}

/** 语言水平 */
export enum LanguageLevel {
  NON_VERBAL = '无语言',
  SINGLE_WORDS = '单字词',
  SHORT_PHRASES = '短句',
  CONVERSATIONAL = '可对话',
}

/** 感官特征 */
export enum SensoryFeature {
  AUDITORY_SENSITIVITY = '听觉敏感',
  TACTILE_SENSITIVITY = '触觉敏感',
  GUSTATORY_SENSITIVITY = '味觉敏感',
  VISUAL_SENSITIVITY = '视觉敏感',
  VESTIBULAR_SEEKING = '前庭寻求',
  PROPRIOCEPTIVE_SEEKING = '本体觉寻求',
}

/** 触发因素 */
export enum Trigger {
  NOISE = '噪音',
  ENVIRONMENT_CHANGE = '环境变化',
  STRANGERS = '陌生人',
  TASK_INTERRUPTION = '任务中断',
  SOCIAL_PRESSURE = '社交压力',
  SENSORY_OVERLOAD = '感官过载',
  PHYSICAL_DISCOMFORT = '身体不适',
}

/** 年龄区间 */
export enum AgeRange {
  INFANT = '0-3岁',
  PRESCHOOL = '4-6岁',
  SCHOOL_AGE = '7-12岁',
  TEEN = '13-18岁',
  ADULT = '18岁以上',
}

/** 档案行为类型 */
export enum ProfileBehaviorType {
  STEREOTYPY = '刻板行为',
  MELTDOWN = '情绪崩溃',
  SELF_INJURY = '自伤行为',
  AGGRESSION = '攻击行为',
  SOCIAL_WITHDRAWAL = '社交退缩',
  HYPERACTIVITY = '多动',
}
