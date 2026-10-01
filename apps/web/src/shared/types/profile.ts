/**
 * 模块: shared/types/profile
 * 职责: 档案面 HTTP 载荷的线格式类型——支持对象、摘要、条目、确认/纠正/否定/删除
 * 数据来源:
 *   - docs/技术设计/面/profile/档案面HTTP契约.md: MUST — 第 2～6 节（端点与载荷）
 *   - docs/技术设计/technical-details/个性化档案.md: MUST — 第 2 节条目形状、第 6 节领域取值
 * 边界:
 *   - 依赖: 无
 *   - 被依赖: features/profile 与 features/consult 的 domain
 * 禁止行为:
 *   - 禁止把领域名称的中文措辞写进类型（领域值域见下方 union，措辞由页面承担）
 *   - 禁止把 origin 与 source 合并成一个字段（两者语义不同，见个性化档案第 2 节）
 */

/**
 * 生成方式（谁在什么位置上说的）。
 * 形状见个性化档案第 2 节 origin 行与第 3 节落层判定表。
 */
export type ProfileOrigin =
  | 'user_statement'
  | 'guardian_observation'
  | 'third_party_report'
  | 'document'
  | 'system_observation'
  | 'ai_inference';

/** 是否被使用者确认过。形状见个性化档案第 2 节 confirmation 行。 */
export type ProfileConfirmation = 'unconfirmed' | 'confirmed' | 'rejected';

/** 是否仍是当前认识。形状见个性化档案第 2 节 freshness 行。 */
export type ProfileFreshness = 'current' | 'historical' | 'stale';

/**
 * 来源定位（这句话在何处可复核）。
 * 形状见个性化档案第 2 节 source 行：「会话 id、消息定位、工具名、时间；转述者记于此」。
 * relayed_by 承载「经监护人转述」这一事实，不为此增设第七个 origin 取值。
 */
export interface ProfileSource {
  session_id?: string;
  message_ref?: string;
  tool_name?: string;
  recorded_at?: string;
  relayed_by?: string;
}

/**
 * 档案条目。形状见个性化档案第 2 节 profile_item 与档案面契约第 3 节（必须含
 * origin、confirmation、freshness 三项）。
 *
 * 不含 pending_id：它是写入路径的幂等键（个性化档案第 7 节），不出现在任何读端点
 * 的载荷里——档案面契约第 3 节的返回是条目读模型。
 */
export interface ProfileItem {
  item_id: string;
  support_object_id: string;
  domain: string;
  topic: string;
  description: string;
  contexts: string[];
  manifestations: string[];
  person_report: string | null;
  probable_need: string | null;
  helpful_support: string[];
  unhelpful_support: string[];
  origin: ProfileOrigin;
  source: ProfileSource;
  confirmation: ProfileConfirmation;
  freshness: ProfileFreshness;
  first_recorded_at: string;
  last_confirmed_at: string | null;
  superseded_by: string | null;
}

/** 支持对象。形状见档案面契约第 2.1、2.2 节。 */
export interface SupportObject {
  id: string;
  display_name: string;
  archived_at: string | null;
}

/** 支持对象列表响应（含已归档对象）。形状见档案面契约第 2.1 节。 */
export interface ListSupportObjectsResponse {
  items: SupportObject[];
}

/** 创建支持对象请求。形状见档案面契约第 2.1 节；属主取登录态，不接受调用方传入。 */
export interface CreateSupportObjectRequest {
  display_name: string;
}

/** 改名与归档请求（同一状态位赋值合在一个端点）。形状见档案面契约第 2.2 节。 */
export interface PatchSupportObjectRequest {
  display_name?: string;
  archived?: boolean;
}

/** 摘要里的一个字段分组。形状见档案面契约第 3 节与个性化档案第 4 节（十二个字段）。 */
export interface ProfileSummaryField {
  key: string;
  label: string;
  items: ProfileSummaryEntry[];
}

/** 摘要里的一条；带 item_id、origin 与 last_confirmed_at。形状见档案面契约第 3 节。 */
export interface ProfileSummaryEntry {
  item_id: string;
  origin: ProfileOrigin;
  last_confirmed_at: string | null;
  text: string;
}

/** 摘要响应。形状见档案面契约第 3 节；只取稳定层。 */
export interface ProfileSummaryResponse {
  fields: ProfileSummaryField[];
  /**
   * 该对象是否已有档案。
   *
   * 契约第 3 节只写了 `fields`，但仅凭 `fields: []` 无法区分「还没有任何条目」与
   * 「有条目但都还在候选层」——个性化档案第 10 节要求前者返回「无档案」而不是空对象。
   * 后端已作为非契约点名字段返回（`modules/profile/routes.SummaryPayload.has_profile`），
   * 这里如实登记；可选是因为它是契约外的补充，缺失时前端按 `fields` 有无降级判断。
   */
  has_profile?: boolean;
}

/**
 * 条目列表响应；候选条目单独成组返回，不混进 items。
 * 形状见档案面契约第 3 节（AC-18 的服务端侧保证）。
 */
export interface ListProfileItemsResponse {
  items: ProfileItem[];
  candidates: ProfileItem[];
  next_cursor: string | null;
}

/**
 * 确认响应。形状见档案面契约第 4 节。
 *
 * 确认能否成功由条目状态决定（`confirmation = unconfirmed` 且未被取代），
 * 不由条目落在哪一组决定：
 * - 历史候选落在 `candidates` 里却不能确认，`superseded_by` 非空即 422 失败；
 * - `third_party_report`／`document` 的未确认条目落在 `items` 里，确认照常成功。
 */
export interface ConfirmProfileItemResponse {
  item_id: string;
  confirmation: 'confirmed';
}

/** 纠正请求（新条目的完整形状，不是补丁字段）。形状见档案面契约第 4 节。 */
export interface CorrectProfileItemRequest {
  description: string;
  topic?: string;
  contexts?: string[];
  manifestations?: string[];
}

/** 纠正响应；纠正即新增取代条目，旧条目转 historical 并互指。形状见档案面契约第 4 节。 */
export interface CorrectProfileItemResponse {
  item_id: string;
  supersedes: string;
}

/** 否定响应；rejected 不物理删除，此后不进摘要、不再作为候选。形状见档案面契约第 4.1 节。 */
export interface RejectProfileItemResponse {
  item_id: string;
  confirmation: 'rejected';
}

/** 删除响应；删除幂等，重复删除仍返回 200 且 already 为真。形状见档案面契约第 4 节。 */
export interface DeleteProfileItemResponse {
  item_id: string;
  already: boolean;
}

/** 补充条目请求；origin 由服务端定为 user_statement，不接受调用方传入。形状见档案面契约第 5 节。 */
export interface CreateProfileItemRequest {
  domain: string;
  topic: string;
  description: string;
  contexts: string[];
  manifestations: string[];
}

/** 补充条目响应。形状见档案面契约第 5 节。 */
export interface CreateProfileItemResponse {
  item_id: string;
}
