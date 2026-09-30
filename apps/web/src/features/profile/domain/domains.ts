/**
 * 模块: features/profile/domain/domains
 * 职责: 档案条目的十四个一级模块 + 「其他」兜底——取值、中文措辞与呈现顺序
 * 数据来源:
 *   - docs/技术设计/technical-details/个性化档案.md: MUST — 第 6 节（十四个一级模块与兜底）
 *   - apps/api/src/campfire/modules/profile/models.py: MUST — 领域闭集（存储层 CHECK 的同一份取值）
 * 边界:
 *   - 依赖: 无
 *   - 被依赖: features/profile 的 domain 分组函数、viewModel 与 view 的领域下拉
 * 禁止行为:
 *   - 禁止在此新增领域取值（闭集变更必须先改后端 CHECK 与档案文档，否则写入会被存储层拒绝）
 *   - 禁止把未知取值静默丢弃（未知取值归「其他」，条目不许在界面上消失）
 */

/**
 * 领域取值 → 中文措辞。
 *
 * 为什么中文措辞在前端而不在载荷里：后端只发取值（`domain`），措辞是呈现层的事；
 * 而十四个模块的中文名在档案文档第 6 节里是固定的，因此它是前端常量而不是接口字段。
 * 措辞逐字取自 models.py 的注释，不自行改写。
 */
export const DOMAIN_LABELS = {
  basic_identity: '基本身份与档案信息',
  about_self: '关于本人、优势、兴趣与目标',
  communication: '沟通',
  sensory_processing: '感觉处理',
  routines_and_change: '日常规律与变化',
  emotional_regulation: '情绪与自我调节',
  triggers_and_support: '触发因素与支持策略',
  executive_function: '执行功能与认知特点',
  daily_living: '日常生活与适应功能',
  social_relationships: '社交与关系',
  physical_medical: '身体与医疗',
  learning_and_work: '学习与工作',
  risk_and_crisis: '风险与危机',
  goals_and_plans: '目标与长期计划',
  other: '其他',
} as const;

/** 合法领域取值联合。与后端 `DOMAINS` 闭集同源。 */
export type ProfileDomain = keyof typeof DOMAIN_LABELS;

/**
 * 呈现顺序：十四个模块按档案文档第 6 节的编号顺序，兜底「其他」永远在末尾。
 *
 * `Object.keys` 的顺序依赖字面量书写顺序——这正是需要的，但仍然显式列出，
 * 因为「顺序是契约的一部分」（分组顺序就是阅读顺序）不该由书写顺序隐式承担。
 */
export const DOMAIN_ORDER: readonly ProfileDomain[] = [
  'basic_identity',
  'about_self',
  'communication',
  'sensory_processing',
  'routines_and_change',
  'emotional_regulation',
  'triggers_and_support',
  'executive_function',
  'daily_living',
  'social_relationships',
  'physical_medical',
  'learning_and_work',
  'risk_and_crisis',
  'goals_and_plans',
  'other',
];

/** 兜底领域取值。 */
export const DOMAIN_FALLBACK: ProfileDomain = 'other';

/**
 * 把载荷里的未知领域取值收窄到闭集。
 *
 * 为什么未知取值归「其他」而不是丢弃：条目在界面上消失是比措辞不准更严重的问题
 * ——使用者会以为系统没记住。后端 CHECK 保证正常路径不会出现未知取值，
 * 因此这条只在「前后端取值集不同步」时生效，属于纵深防御。
 */
export function toProfileDomain(raw: string): ProfileDomain {
  return raw in DOMAIN_LABELS ? (raw as ProfileDomain) : DOMAIN_FALLBACK;
}

/** 取领域的中文措辞；未知取值落到「其他」的措辞。 */
export function domainLabel(raw: string): string {
  return DOMAIN_LABELS[toProfileDomain(raw)];
}
