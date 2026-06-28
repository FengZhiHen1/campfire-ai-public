/**
 * CASE-09 案例管理逻辑 — 共享常量定义。
 *
 * 所有视图层共用的状态映射、标签映射、选项列表，单一来源。
 * 视图组件禁止在文件内重复定义这些常量。
 */

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
  pending_review: 'pending',
  approved: 'approved',
  rejected: 'rejected',
};

/** 来源类型 → 短标签 */
export const SOURCE_LABEL_MAP: Record<string, string> = {
  '专家撰写': '专家',
  '机构脱敏': '机构',
  '工单沉淀': '工单',
  '家属分享': '家属',
};

/** 卡片审核状态 → 文案 + CSS 类名 */
export const CARD_STATUS_MAP: Record<string, { text: string; cls: string }> = {
  draft: { text: '草稿', cls: 'draft' },
  pending_review: { text: '待审核', cls: 'pending' },
  approved: { text: '已通过', cls: 'approved' },
  rejected: { text: '已驳回', cls: 'rejected' },
};

// ============================================================================
// 选项列表
// ============================================================================

/** 行为类型选项（展示用） */
export const BEHAVIOR_TYPE_OPTIONS: readonly string[] = [
  '自伤', '攻击', '刻板', '逃跑', '情绪崩溃', '其他',
];

/** 行为类型后端枚举值（与 SeverityLevel 枚举对齐，按索引对应 BEHAVIOR_TYPE_OPTIONS） */
export const BEHAVIOR_TYPE_VALUES: readonly string[] = [
  'self_injury', 'aggression', 'stereotypy', 'elopement', 'meltdown', 'other',
];

/** 严重程度选项（展示用） */
export const SEVERITY_OPTIONS: readonly string[] = ['轻度', '中度', '重度'];

/** 严重程度后端枚举值（与 BehaviorType 枚举对齐，按索引对应 SEVERITY_OPTIONS） */
export const SEVERITY_VALUES: readonly string[] = ['mild', 'moderate', 'severe'];

/** 场景选项（展示用） */
export const SCENE_OPTIONS: readonly string[] = ['家庭', '学校', '公共场合', '机构', '不限'];

/** 场景后端枚举值（与 SceneType 枚举对齐，按索引对应 SCENE_OPTIONS） */
export const SCENE_VALUES: readonly string[] = ['home', 'school', 'public', 'institution', 'any'];

/** 循证等级选项（展示用） */
export const EVIDENCE_LEVEL_OPTIONS: readonly string[] = [
  'NCAEP循证实践', '机构经验总结', '个案观察记录',
];

/** 循证等级后端枚举值（与 EvidenceLevel 枚举对齐，按索引对应 EVIDENCE_LEVEL_OPTIONS） */
export const EVIDENCE_LEVEL_VALUES: readonly string[] = [
  'ncaep', 'institution_experience', 'case_observation',
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
