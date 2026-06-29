/**
 * CASE-09 案例管理逻辑 — 共享常量定义。
 *
 * 所有视图层共用的状态映射、标签映射、选项列表，单一来源。
 * 视图组件禁止在文件内重复定义这些常量。
 *
 * 枚举对齐原则：持久化值以后端 py-schemas 为准；前端展示文案可独立映射。
 */

import {
  BehaviorType,
  SeverityLevel,
  SceneType,
  EvidenceLevel,
} from '@campfire/ts-shared';

// ============================================================================
// 状态显示映射
// ============================================================================

/** 案例状态 → 中文文案 */
export const STATUS_TEXT_MAP: Record<string, string> = {
  draft: '草稿',
  pending_review: '待审核',
  approved: '已通过',
  rejected: '已驳回',
};

/** 案例状态 → CSS 类名后缀 */
export const STATUS_CLASS_MAP: Record<string, string> = {
  draft: 'draft',
  pending_review: 'reviewing',
  approved: 'approved',
  rejected: 'rejected',
};

/** 来源类型 → 短标签（持久化值以后端 SourceType 为准） */
export const SOURCE_LABEL_MAP: Record<string, string> = {
  '专家撰写': '专家撰写',
  '机构脱敏': '机构脱敏',
  '工单沉淀': '工单沉淀',
  '家属分享': '家属分享',
};

/** 行为类型后端值 → 卡片/详情页展示文案 */
export const BEHAVIOR_DISPLAY_MAP: Record<string, string> = {
  [BehaviorType.SELF_INJURY]: '自伤行为',
  [BehaviorType.AGGRESSION]: '攻击行为',
  [BehaviorType.ELOPEMENT]: '出走/逃跑',
  [BehaviorType.MELTDOWN]: '情绪崩溃',
  [BehaviorType.STEREOTYPY]: '刻板行为',
  [BehaviorType.OTHER]: '其他',
};

/** 审核台筛选器：短文案（贴近 OD）→ 后端值 */
export const BEHAVIOR_FILTER_OPTIONS: readonly { label: string; value: string }[] = [
  { label: '自伤', value: BehaviorType.SELF_INJURY },
  { label: '攻击', value: BehaviorType.AGGRESSION },
  { label: '逃跑', value: BehaviorType.ELOPEMENT },
  { label: '情绪', value: BehaviorType.MELTDOWN },
  { label: '刻板', value: BehaviorType.STEREOTYPY },
  { label: '其他', value: BehaviorType.OTHER },
];

/** 卡片审核状态 → 文案 + CSS 类名 */
export const CARD_STATUS_MAP: Record<string, { text: string; cls: string }> = {
  draft: { text: '草稿', cls: 'draft' },
  pending_review: { text: '待审核', cls: 'reviewing' },
  approved: { text: '已通过', cls: 'approved' },
  rejected: { text: '已驳回', cls: 'rejected' },
};

// ============================================================================
// 选项列表
// ============================================================================

/** 行为类型选项（展示用）——顺序贴近 OD，持久化值以后端 BehaviorType 为准 */
export const BEHAVIOR_TYPE_OPTIONS: readonly string[] = [
  '自伤行为', '攻击行为', '出走/逃跑', '情绪崩溃', '刻板行为', '其他',
];

/** 行为类型后端枚举值（按索引对应 BEHAVIOR_TYPE_OPTIONS） */
export const BEHAVIOR_TYPE_VALUES: readonly string[] = [
  BehaviorType.SELF_INJURY,
  BehaviorType.AGGRESSION,
  BehaviorType.ELOPEMENT,
  BehaviorType.MELTDOWN,
  BehaviorType.STEREOTYPY,
  BehaviorType.OTHER,
];

/** 严重程度选项（展示用） */
export const SEVERITY_OPTIONS: readonly string[] = ['轻度', '中度', '重度'];

/** 严重程度后端枚举值（按索引对应 SEVERITY_OPTIONS） */
export const SEVERITY_VALUES: readonly string[] = [
  SeverityLevel.MILD,
  SeverityLevel.MODERATE,
  SeverityLevel.SEVERE,
];

/** 场景选项（展示用） */
export const SCENE_OPTIONS: readonly string[] = ['家庭', '学校', '公共场合', '机构', '不限'];

/** 场景后端枚举值（按索引对应 SCENE_OPTIONS） */
export const SCENE_VALUES: readonly string[] = [
  SceneType.HOME,
  SceneType.SCHOOL,
  SceneType.PUBLIC,
  SceneType.INSTITUTION,
  SceneType.ANY,
];

/** 循证等级选项（展示用） */
export const EVIDENCE_LEVEL_OPTIONS: readonly string[] = [
  'NCAEP循证实践', '机构经验总结', '个案观察记录',
];

/** 循证等级后端枚举值（按索引对应 EVIDENCE_LEVEL_OPTIONS） */
export const EVIDENCE_LEVEL_VALUES: readonly string[] = [
  EvidenceLevel.NCAEP,
  EvidenceLevel.INSTITUTION_EXPERIENCE,
  EvidenceLevel.CASE_OBSERVATION,
];

/** 家属展示大类选项 */
export const FAMILY_CATEGORY_OPTIONS: readonly string[] = [
  '环境调整', '沟通替代', '行为塑造', '危机安全', '社交引导', '自我管理',
];

/** 来源类型选项 */
export const SOURCE_TYPE_OPTIONS: readonly string[] = ['专家撰写', '机构脱敏', '工单沉淀'];

/** 叙事写作提示 */
export const WRITING_TIPS: readonly string[] = [
  '详细描述前因：引发行为的具体环境或事件是什么？',
  '客观记录行为：孩子具体的表现（如：大声尖叫持续5分钟，双手捂耳）。',
  '说明干预步骤及结果：采取了哪些行动，最终效果如何？',
];

/** 叙事正文 placeholder 模板 */
export const NARRATIVE_BODY_PLACEHOLDER: string = `【描述孩子情况】
年龄、诊断倾向、当下的情绪基调...

【行为表现】
具体的动作、声音、持续时间...

【干预动作】
你做了什么？环境做了哪些调整？...

【结果效果】
最终状态如何？有何反思？...`;
