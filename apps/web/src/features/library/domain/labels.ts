/**
 * 模块: features/library/domain/labels
 * 职责: 案例与资料条目的呈现措辞——状态、审阅状态、证据等级、授权与风险档
 * 数据来源:
 *   - docs/技术设计/面/profile/资料库面HTTP契约.md: MUST — 第 3.1 节（共有字段与案例六项必带）
 *   - docs/技术设计/technical-details/公共案例库.md: MUST — 第 5 节风险分级、第 7、8 节审阅状态
 *   - docs/design/pages/案例库浏览页.md: MUST — 第 21、40、59 行（状态徽章、不编造排序、虚构样例文字直出）
 * 边界:
 *   - 依赖: shared/types/library
 *   - 被依赖: features/library 的 viewModel 与 view
 * 禁止行为:
 *   - 禁止为缺字段补默认措辞（缺来源或状态的条目按不变量不进入结果，契约第 2 节）
 *   - 禁止把 owner 显示成「已审阅」（同文第 7、8 节：必须能显示为「项目所有者核准」）
 */

import type { EvidenceLevel, LibraryItemStatus, LibraryKind, ReviewStatus, RiskClass } from '../../../shared/types/library';

/** 库别措辞（两库分开取数，界面上是两个分区）。 */
const LIBRARY_LABELS: Readonly<Record<LibraryKind, string>> = {
  case: '案例',
  knowledge: '资料',
};

/** 取库别措辞。 */
export function libraryLabel(kind: LibraryKind): string {
  return LIBRARY_LABELS[kind];
}

/**
 * 条目状态措辞。
 *
 * 三个取值在列表里直出（`RQ-KB-02`）；「虚构样例」用文字而不是颜色承载，
 * 与真实案例混列但可辨（`AC-06`：可辨性不建立在色觉上）。
 */
const STATUS_LABELS: Readonly<Record<LibraryItemStatus, string>> = {
  published: '已发表',
  internal: '内部',
  fictional: '虚构样例',
};

/** 取状态措辞。 */
export function statusLabel(status: LibraryItemStatus): string {
  return STATUS_LABELS[status];
}

/** 是否为虚构样例（决定用灰调标识而不是彩色）。 */
export function isFictional(status: LibraryItemStatus): boolean {
  return status === 'fictional';
}

/**
 * 审阅状态措辞。
 *
 * `owner` 必须显示为「项目所有者核准」而不是「已审阅」：前者说明的是谁核准的，
 * 后者会让使用者以为经过了独立专业审阅（公共案例库第 7、8 节）。
 */
const REVIEW_LABELS: Readonly<Record<ReviewStatus, string>> = {
  professional: '专业审阅',
  owner: '项目所有者核准',
  pending: '待审阅',
};

/** 取审阅状态措辞。 */
export function reviewStatusLabel(status: ReviewStatus): string {
  return REVIEW_LABELS[status];
}

/** 证据等级措辞。 */
const EVIDENCE_LABELS: Readonly<Record<EvidenceLevel, string>> = {
  EBP: '循证实践',
  INSTITUTIONAL: '机构材料',
  OBSERVATIONAL: '观察性经验',
};

/** 取证据等级措辞。 */
export function evidenceLevelLabel(level: EvidenceLevel): string {
  return EVIDENCE_LABELS[level];
}

/** 卡片风险档措辞。 */
const RISK_LABELS: Readonly<Record<RiskClass, string>> = {
  low: '风险低',
  mixed: '风险混合',
  high: '风险高',
};

/** 取卡片风险档措辞。 */
export function riskClassLabel(risk: RiskClass): string {
  return RISK_LABELS[risk];
}

/**
 * 组成案例卡的元信息行：来源 + 来源类型 + 证据等级 + 审阅状态 + 授权 + 访谈时间。
 *
 * 状态（已发表/内部/虚构样例）不在这里——它是独立的状态徽章，见 `statusLabel`。
 * 缺字段不补默认值：案例侧的六项必带字段缺任一个，页面就无法如实回答
 * 「谁说的、多可信、什么时候」（契约第 3.1 节）。因此这里只拼接**存在**的字段，
 * 缺失的段落直接不出现——而不是写「未知来源」这种看起来像结论的填充。
 */
export function itemMetaParts(item: {
  source: string;
  source_type?: string;
  evidence_level?: EvidenceLevel;
  review_status?: ReviewStatus;
  authorization?: string;
  interview_at?: string;
}): string[] {
  const parts: string[] = [`来源：${item.source}`];
  if (item.source_type !== undefined && item.source_type !== '') parts.push(item.source_type);
  if (item.evidence_level !== undefined) parts.push(evidenceLevelLabel(item.evidence_level));
  if (item.review_status !== undefined) parts.push(reviewStatusLabel(item.review_status));
  if (item.authorization !== undefined && item.authorization !== '') parts.push(item.authorization);
  if (item.interview_at !== undefined && item.interview_at !== '') parts.push(`访谈 ${item.interview_at}`);
  return parts;
}
