/**
 * 模块: shared/types/library
 * 职责: 资料库面 HTTP 载荷的线格式类型——浏览/检索条目、条目展开与 deep-link
 * 数据来源:
 *   - docs/技术设计/面/profile/资料库面HTTP契约.md: MUST — 第 3、4、5 节
 *   - docs/技术设计/technical-details/资料与案例检索.md: MUST — 第 3 节返回契约
 *   - docs/技术设计/technical-details/公共案例库.md: MUST — 第 4、5 节卡片结构与风险分级
 * 边界:
 *   - 依赖: 无
 *   - 被依赖: features/library 的 domain 与 infrastructure
 * 禁止行为:
 *   - 禁止定义写端点载荷（本面只有读端点，资料库面契约第 1 节）
 *   - 禁止为缺字段补默认值（缺来源或状态的条目按不变量不进入结果，契约第 2 节）
 */

/** 库别。两库分开取数，不合并成一张表加类型标签。形状见资料库面契约第 2、3 节。 */
export type LibraryKind = 'knowledge' | 'case';

/** 条目发布状态。形状见资料与案例检索第 3 节返回契约。 */
export type LibraryItemStatus = 'published' | 'internal' | 'fictional';

/** 证据等级。形状见资料与案例检索第 3 节。 */
export type EvidenceLevel = 'EBP' | 'INSTITUTIONAL' | 'OBSERVATIONAL';

/** 审阅状态。形状见资料与案例检索第 3 节；owner 须显示为「项目所有者核准」。 */
export type ReviewStatus = 'professional' | 'owner' | 'pending';

/** 卡片风险档。形状见公共案例库第 5 节 risk_class（low | mixed | high）。 */
export type RiskClass = 'low' | 'mixed' | 'high';

/**
 * 检索命中的名次与命中来源（哪几路命中），供排序与调试。
 * 形状见资料与案例检索第 3 节返回契约 ranking 行。
 */
export interface SearchRanking {
  rank: number;
  channels: string[];
}

/**
 * 列表里的一个条目。
 * 共有字段见资料库面契约第 3.1 节；案例侧的六项必带字段同样见该节
 * （authorization、source_type、evidence_level、review_status、interview_at、
 * makes_claims_high_risk）——它们与 inferred_fields 只在 library 为 case 时出现。
 *
 * 案例侧这七项写成可空而不是仅可选：后端逐字段透传，资料条目的响应里键是在的、
 * 值是 null（不是缺键）。只判 undefined 的守卫会被 null 全部放行——
 * 2026-10-07 资料行的元信息行因此拼出「访谈 null」（见 domain/labels）。
 */
export interface LibraryItem {
  item_id: string;
  library: LibraryKind;
  title: string;
  snippet: string;
  source: string;
  applicable_scope: string;
  status: LibraryItemStatus;
  locator: string;
  ranking: SearchRanking;
  authorization?: string | null;
  source_type?: string | null;
  evidence_level?: EvidenceLevel | null;
  review_status?: ReviewStatus | null;
  interview_at?: string | null;
  makes_claims_high_risk?: boolean | null;
  inferred_fields?: string[] | null;
}

/** 叙事小节（条目展开时随列表一并返回）。形状见资料库面契约第 4 节。 */
export interface NarrativeSection {
  key: string;
  heading: string;
  text: string;
}

/** 条目展开时的 narrative。形状见资料库面契约第 4 节。 */
export interface Narrative {
  sections: NarrativeSection[];
}

/**
 * 条目展开时的一张卡片。
 * 契约显式列出的字段见资料库面契约第 4 节；其余上游字段见公共案例库第 4 节
 * （comforting_phrase、observation_metrics、behavior_type、setting 等）。
 * 高风险字段（immediate_action、medical_criteria、contraindications、caution_notes）
 * 照旧返回，呈现纪律在 skill 与页面层执行——本契约不拦截（契约第 4 节）。
 */
export interface CaseCard {
  card_id: string;
  scenario: string;
  immediate_action: string;
  inferred_fields: string[];
  risk_class: RiskClass;
  comforting_phrase?: string;
  observation_metrics?: string;
  medical_criteria?: string;
  contraindications?: string;
  caution_notes?: string;
  parent_category?: string;
}

/**
 * 条目展开内容。两项只在请求带 `expand=<item_id>` 且命中该条目时非空——
 * 普通列表请求里恒为 `null`（契约第 4 节：展开内容随列表一并返回，页面无详情页）。
 */
export interface LibraryItemExpansion {
  narrative: Narrative | null;
  cards: CaseCard[] | null;
}

/**
 * 列表里的条目：基础字段恒在场，展开内容按 `expand` 是否命中可空。
 *
 * 不叫 Expanded…：列表里绝大多数条目并未展开，用「已展开」命名会让读类型的人
 * 以为 narrative/cards 必填，于是把守卫写成判 undefined——2026-10-07 生产因此崩过。
 */
export type LibraryListItem = LibraryItem & LibraryItemExpansion;

/** 浏览与检索响应。形状见资料库面契约第 3 节；空 query 即全量浏览流。 */
export interface ListLibraryItemsResponse {
  library: LibraryKind;
  items: LibraryListItem[];
  next_cursor: string | null;
}

/**
 * deep-link 单条查询响应。
 * 形状见资料库面契约第 5 节：已撤下返回 200 且 item 为 null、只带标题，不带正文与
 * 其他字段——撤下判定来自服务端，不由前端猜测。
 */
export interface GetLibraryItemResponse {
  item: LibraryItem | null;
  withdrawn?: boolean;
  title?: string;
}
