/**
 * 模块: @campfire/ts-shared.cases.enums
 * 职责: 案例管理域的前端枚举定义——案例状态、行为类型、严重程度、场景、循证等级、家属展示大类。
 *       枚举值为后端数据库存储值，前端展示文案由 mini-program 的 i18n/常量层负责映射。
 * 数据来源:
 *   - py-schemas (case_enums): MUST — 后端 Python 枚举（py_schemas.enums.case_enums）
 *   - CASE-01 设计文档: SHOULD — 字段语义和取值范围
 * 边界:
 *   - 依赖: 无
 *   - 被依赖: cases.types.ts、cases.contract.ts、mini-program
 * 禁止行为:
 *   - 禁止在枚举值中嵌入中文展示文案——展示层应独立映射
 *   - 禁止定义与后端枚举值不一致的字符串
 *   - 禁止在此文件中定义运行时工具函数（枚举 → 标签映射应放在 contract.ts 中）
 */

/** 案例状态——对应后端 CaseStatus 枚举 */
export enum CaseStatus {
  DRAFT = 'draft',
  PENDING_REVIEW = 'pending_review',
  REJECTED = 'rejected',
}

/** 案例来源类型——对应后端 SourceType 枚举 */
export enum SourceType {
  EXPERT_WRITTEN = 'expert_written',
  INSTITUTION_DESENSITIZED = 'institution_desensitized',
  TICKET_DEPOSIT = 'ticket_deposit',
}

/** 行为类型——对应后端 BehaviorType 枚举 */
export enum BehaviorType {
  SELF_INJURY = 'self_injury',
  AGGRESSION = 'aggression',
  STEREOTYPY = 'stereotypy',
  ELOPEMENT = 'elopement',
  MELTDOWN = 'meltdown',
  OTHER = 'other',
}

/** 严重程度——对应后端 SeverityLevel 枚举 */
export enum SeverityLevel {
  MILD = 'mild',
  MODERATE = 'moderate',
  SEVERE = 'severe',
}

/** 场景类型——对应后端 SceneType 枚举 */
export enum SceneType {
  HOME = 'home',
  SCHOOL = 'school',
  PUBLIC = 'public',
  INSTITUTION = 'institution',
  ANY = 'any',
}

/** 循证等级——对应后端 EvidenceLevel 枚举 */
export enum EvidenceLevel {
  NCAEP = 'ncaep',
  INSTITUTION_EXPERIENCE = 'institution_experience',
  CASE_OBSERVATION = 'case_observation',
}

/** 家属端展示大类——对应后端 FamilyDisplayCategory 枚举 */
export enum FamilyDisplayCategory {
  ENVIRONMENT_ADJUSTMENT = 'environment_adjustment',
  COMMUNICATION_ALTERNATIVE = 'communication_alternative',
  BEHAVIOR_SHAPING = 'behavior_shaping',
  CRISIS_SAFETY = 'crisis_safety',
  SOCIAL_GUIDANCE = 'social_guidance',
  SELF_MANAGEMENT = 'self_management',
}
