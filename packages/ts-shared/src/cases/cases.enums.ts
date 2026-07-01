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

/** 案例状态——对应后端 CaseStatus 枚举（py_schemas.enums.case_enums.CaseStatus） */
export enum CaseStatus {
  DRAFT = 'draft',
  PENDING_REVIEW = 'pending_review',
  APPROVED = 'approved',
  REJECTED = 'rejected',
}

/** 案例来源类型——持久化值以后端 py-schemas 为准 */
export enum SourceType {
  EXPERT_WRITTEN = '专家撰写',
  INSTITUTION_DESENSITIZED = '机构脱敏',
  TICKET_DEPOSIT = '工单沉淀',
}

/** 行为类型——持久化值以后端 py-schemas 为准 */
export enum BehaviorType {
  SELF_INJURY = '自伤',
  AGGRESSION = '攻击',
  STEREOTYPY = '刻板',
  ELOPEMENT = '逃跑',
  MELTDOWN = '情绪崩溃',
  OTHER = '其他',
}

/** 严重程度——持久化值以后端 py-schemas 为准 */
export enum SeverityLevel {
  MILD = '轻度',
  MODERATE = '中度',
  SEVERE = '重度',
}

/** 场景类型——持久化值以后端 py-schemas 为准 */
export enum SceneType {
  HOME = '家庭',
  SCHOOL = '学校',
  PUBLIC = '公共场合',
  INSTITUTION = '机构',
  ANY = '不限',
}

/** 循证等级——持久化值以后端 py-schemas 为准 */
export enum EvidenceLevel {
  NCAEP = 'NCAEP循证实践',
  INSTITUTION_EXPERIENCE = '机构经验总结',
  CASE_OBSERVATION = '个案观察记录',
}

/** 家属端展示大类——持久化值以后端 py-schemas 为准 */
export enum FamilyDisplayCategory {
  ENVIRONMENT_ADJUSTMENT = '环境调整',
  COMMUNICATION_ALTERNATIVE = '沟通替代',
  BEHAVIOR_SHAPING = '行为塑造',
  CRISIS_SAFETY = '危机安全',
  SOCIAL_GUIDANCE = '社交引导',
  SELF_MANAGEMENT = '自我管理',
}
