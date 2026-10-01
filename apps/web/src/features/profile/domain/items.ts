/**
 * 模块: features/profile/domain/items
 * 职责: 档案条目的呈现规则——来源措辞、候选/降权/历史判定、按领域分组
 * 数据来源:
 *   - docs/design/pages/档案页.md: MUST — 第 23 行（`.lr-meta` = 来源类型 + 确认状态 + 时间）、
 *     第 25 行（降权条目的行首标与描述折叠）、第 62 行（纠正后原条目转历史态，行首「已更正」标）
 *   - docs/技术设计/面/profile/档案面HTTP契约.md: MUST — 第 3 节（items 与 candidates 分开返回）
 *   - docs/技术设计/technical-details/个性化档案.md: MUST — 第 2 节条目字段、第 3 节时效
 * 边界:
 *   - 依赖: shared/types/profile、features/profile/domain/domains
 *   - 被依赖: features/profile 的 application 与 viewModel
 * 禁止行为:
 *   - 禁止在界面层自行判断「哪条算候选」（候选由返回结构给出，见下方 isCandidate 的说明）
 *   - 禁止把未确认条目混进摘要（候选层视觉不变量，AC-18）
 *   - 禁止把时效措辞写进元信息行（`已降权`/`已更正` 是 `.tag.meta` 标，不是 `.lr-meta` 的内容）
 */

import type { ProfileItem, ProfileOrigin } from '../../../shared/types/profile';
import { DOMAIN_ORDER, type ProfileDomain, toProfileDomain } from './domains';

/** 来源类型的界面措辞（档案页第 50 行的六类映射，逐字使用）。 */
const ORIGIN_LABELS: Readonly<Record<ProfileOrigin, string>> = {
  user_statement: '你说过',
  guardian_observation: '你的观察',
  third_party_report: '第三方转述',
  document: '文档记录',
  system_observation: '系统观察',
  ai_inference: 'AI 归纳',
};

/** 取来源类型的中文措辞。 */
export function originLabel(origin: ProfileOrigin): string {
  return ORIGIN_LABELS[origin];
}

/**
 * 是否为候选（待确认）条目。
 *
 * 判据是 `confirmation === 'unconfirmed'`，不是 origin 是否属推断：
 * 使用者的自述也可以未被确认（服务端由 origin 推导确认状态，前端不重做这一步）。
 * 分组仍由服务端返回结构决定（`candidates` 数组），本函数只用于行内呈现，
 * 不用于把 items 拆成两组——那是 `AC-18` 的服务端侧保证，前端重做会掩盖它的失效。
 */
export function isCandidate(item: ProfileItem): boolean {
  return item.confirmation === 'unconfirmed';
}

/** 是否为已降权（90 天）条目：行组件据此出行首「已降权」标并把描述默认折叠（档案页第 25 行）。 */
export function isStale(item: ProfileItem): boolean {
  return item.freshness === 'stale';
}

/**
 * 是否为历史（已被取代）条目：行组件据此出行首「已更正」标（档案页第 33、62 行）。
 *
 * 判据只由 `freshness` 承担，与 `isStale` 同形：`superseded_by` 是同一件事的另一侧指针
 * （纠正一次同时置两者并互指），再判一次就是同一事实的两个出口。
 * 历史条目由服务端在 `include_superseded = true` 时随条目流返回（档案页第 62 行
 * 「原条目转历史态……新条目进入列表」）；落哪一组不由本判据决定——已确认或非推断来源的
 * 归 `items`，未确认的系统推断即便已被取代也归 `candidates`（`AC-18`）。两组都用本判据出行首标。
 */
export function isHistorical(item: ProfileItem): boolean {
  return item.freshness === 'historical';
}

/** 一个领域分组：领域取值 + 该组条目。 */
export interface DomainGroup {
  domain: ProfileDomain;
  items: ProfileItem[];
}

/**
 * 把稳定层条目按领域分组，空的领域不出现。
 *
 * 为什么空组不渲染：十四个模块全列出来、其中十二个是空的，会让「有什么」这件事
 * 淹没在「没什么」里；而领域下拉（补充条目的选择）才需要完整取值集。
 *
 * 前置: 无（空数组返回空数组）
 * 后置: 返回的组按 `DOMAIN_ORDER` 排列，组内保持传入顺序，且不含空组
 * 异常: 无
 */
export function groupByDomain(items: readonly ProfileItem[]): DomainGroup[] {
  const buckets = new Map<ProfileDomain, ProfileItem[]>();
  for (const item of items) {
    const domain = toProfileDomain(item.domain);
    const bucket = buckets.get(domain);
    if (bucket === undefined) buckets.set(domain, [item]);
    else bucket.push(item);
  }
  return DOMAIN_ORDER.filter((domain) => buckets.has(domain)).map((domain) => ({
    domain,
    items: buckets.get(domain) ?? [],
  }));
}

/**
 * 组成条目行的元信息行：来源 + 确认状态 + 时间。
 *
 * 三者就是设计给 `.lr-meta` 的全部内容（档案页第 23 行），因此这里不收时效：
 * `已降权` 是条目行首的 `.tag.meta` 标（第 25、33 行），由 `isStale` 在行组件里判。
 * 时效措辞曾一度追加在本行尾部，使一条降权候选行同时出现两处「已降权」——
 * 同一事实两处出口，且违反第 23 行对 `.lr-meta` 的定义。
 *
 * 时间用 `last_confirmed_at`（最近确认时间，档案页第 19 行：「本人自述（经监护人转述）· 10-02 确认」）；
 * 未确认条目没有确认时间，改用 `first_recorded_at` 并标成记录时间——两者语义不同，
 * 不能共用一句「10-02」。
 */
export function itemMetaLine(item: ProfileItem): string {
  const parts: string[] = [originLabel(item.origin)];
  if (item.source.relayed_by !== undefined && item.source.relayed_by !== '') {
    parts[0] = `${parts[0]}（经${item.source.relayed_by}转述）`;
  }
  if (item.last_confirmed_at !== null) {
    parts.push(`${formatMonthDay(item.last_confirmed_at)} 确认`);
  } else {
    parts.push(`${formatMonthDay(item.first_recorded_at)} 记录`);
  }
  if (isCandidate(item)) parts.push('待确认');
  return parts.join(' · ');
}

/**
 * 把 ISO 时间渲染成「MM-DD」。
 *
 * 非法时间原样返回短串而不是抛错：时间是呈现信息，一条时间格式异常不该让整页崩掉
 * （边界显式，不静默兜底成假日期——这里回退成「时间未知」）。
 */
export function formatMonthDay(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return '时间未知';
  const month = `${parsed.getMonth() + 1}`.padStart(2, '0');
  const day = `${parsed.getDate()}`.padStart(2, '0');
  return `${month}-${day}`;
}
