/** CASE-01 案例录入管理 — 前端枚举镜像 */

/** 案例状态枚举 */
export enum CaseStatus {
  DRAFT = 'draft',
  PENDING_REVIEW = 'pending_review',
  REJECTED = 'rejected',
}

/** 案例来源类型枚举 */
export enum SourceType {
  EXPERT_WRITTEN = '专家撰写',
  INSTITUTION_DESENSITIZED = '机构脱敏',
  TICKET_DEPOSIT = '工单沉淀',
}

/** 行为类型枚举 */
export enum BehaviorType {
  SELF_INJURY = '自伤',
  AGGRESSION = '攻击',
  STEREOTYPY = '刻板',
  ELOPEMENT = '逃跑',
  MELTDOWN = '情绪崩溃',
  OTHER = '其他',
}

/** 严重程度枚举 */
export enum SeverityLevel {
  MILD = '轻度',
  MODERATE = '中度',
  SEVERE = '重度',
}

/** 场景类型枚举 */
export enum SceneType {
  HOME = '家庭',
  SCHOOL = '学校',
  PUBLIC = '公共场合',
  INSTITUTION = '机构',
  ANY = '不限',
}

/** 循证等级枚举 */
export enum EvidenceLevel {
  NCAEP = 'NCAEP循证实践',
  INSTITUTION_EXPERIENCE = '机构经验总结',
  CASE_OBSERVATION = '个案观察记录',
}

/** 家属端展示大类枚举 */
export enum FamilyDisplayCategory {
  ENVIRONMENT_ADJUSTMENT = '环境调整',
  COMMUNICATION_ALTERNATIVE = '沟通替代',
  BEHAVIOR_SHAPING = '行为塑造',
  CRISIS_SAFETY = '危机安全',
  SOCIAL_GUIDANCE = '社交引导',
  SELF_MANAGEMENT = '自我管理',
}
