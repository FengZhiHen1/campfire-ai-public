/**
 * 模块: features/memory/domain/episodes
 * 职责: 记忆时间线的呈现规则——按日期倒序分组、时间与来源措辞、原文不摘要
 * 数据来源:
 *   - docs/design/pages/记忆页.md: MUST — 第 24～28、50 行（倒序按日期分组、发生时间、不暴露会话标识）
 *   - docs/技术设计/面/profile/记忆面HTTP契约.md: MUST — 第 3 节（episode_key/occurred_at/content/source_session_id）
 * 边界:
 *   - 依赖: shared/types/memory
 *   - 被依赖: features/memory 的 viewModel 与 view
 * 禁止行为:
 *   - 禁止在界面上出现 source_session_id 原文（它是排障定位，不是给使用者看的导航）
 *   - 禁止对 content 做摘要或转译（本页是核对场景，原文不得丢信息）
 */

import type { MemoryEpisode } from '../../../shared/types/memory';

/** 一个日期分组。 */
export interface EpisodeDateGroup {
  /** 本地日期键 `YYYY-MM-DD`；用作 React key。 */
  key: string;
  /** 分组头文案。 */
  label: string;
  items: MemoryEpisode[];
}

/**
 * 时间线分组用的本地日期键。
 *
 * 用本地日期而不是 UTC：用 UTC 会让晚上发生的记忆被分到第二天，
 * 而使用者核对的是「那天我说过什么」这件事。
 */
export function localDateKey(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return 'unknown';
  const month = `${parsed.getMonth() + 1}`.padStart(2, '0');
  const day = `${parsed.getDate()}`.padStart(2, '0');
  return `${parsed.getFullYear()}-${month}-${day}`;
}

/** 分组头文案：`M月D日`；无法解析的时间如实写「时间未知」。 */
export function dateHeading(key: string): string {
  const match = /^\d{4}-(\d{2})-(\d{2})$/.exec(key);
  if (match === null) return '时间未知';
  return `${Number(match[1])}月${Number(match[2])}日`;
}

/**
 * 把记忆按 `occurred_at` 倒序、按本地日期分组。
 *
 * 前置: 无（空数组返回空分组）
 * 后置: 分组按日期倒序；组内也按时间倒序；时间无法解析的条目归到最后一组
 * 异常: 无
 */
export function groupByDate(items: readonly MemoryEpisode[]): EpisodeDateGroup[] {
  // 豁免 no-array-sort 的理由：这里排的是 `[...items]` 这个副本，调用方的数组不受影响；
  // 规则建议的 `toSorted` 不在本项目的 TS lib 目标里（ES2023 起才提供）。
  // oxlint-disable-next-line unicorn/no-array-sort
  const sorted = [...items].sort((left, right) => timeOf(right.occurred_at) - timeOf(left.occurred_at));
  const groups: EpisodeDateGroup[] = [];
  for (const item of sorted) {
    const key = localDateKey(item.occurred_at);
    const last = groups[groups.length - 1];
    if (last !== undefined && last.key === key) last.items.push(item);
    else groups.push({ key, label: dateHeading(key), items: [item] });
  }
  return groups;
}

/**
 * 排序用的时间戳；无法解析的排在最后。
 *
 * `Number.NEGATIVE_INFINITY` 而不是 0：用 0 会让一条坏时间的记忆排到 1970 的位置
 * 却看起来像正常数据，而「排到最后」是明确的降级。
 */
function timeOf(iso: string): number {
  const parsed = new Date(iso).getTime();
  return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed;
}

/**
 * 发生时间的呈现文案。
 *
 * 一律标注「发生时间」而不是提交时间（记忆页第 50 行）：两者不同，
 * 用提交时间会让使用者核对的是错的时点。
 */
export function occurredAtLabel(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return '发生时间未知';
  const month = `${parsed.getMonth() + 1}`.padStart(2, '0');
  const day = `${parsed.getDate()}`.padStart(2, '0');
  const hour = `${parsed.getHours()}`.padStart(2, '0');
  const minute = `${parsed.getMinutes()}`.padStart(2, '0');
  return `发生时间 ${month}-${day} ${hour}:${minute}`;
}

/**
 * 来源行的固定文案。
 *
 * 不返回 `source_session_id`：会话标识是排障用的定位，不是给使用者看的导航
 * （记忆页第 26 行）。做成函数而不是常量，是为了让「界面上永远读不到那个字段」
 * 这件事在类型上成立——调用方拿不到它，也就写不出它。
 */
export function sourceLabel(): string {
  return '来自一次咨询';
}

/**
 * 把 ISO 时间转成 `<input type="datetime-local">` 需要的本地值。
 *
 * 必须用本地时区：datetime-local 的值是「挂钟时间」，没有时区；
 * 用 UTC 拼接会让使用者在表单里看到一个与刚才不一样的时刻。
 * 无法解析时返回空串——空值会被校验拦下，而不是变成一个编造的时间。
 */
export function toDatetimeLocalValue(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return '';
  const pad = (value: number): string => `${value}`.padStart(2, '0');
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}T${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

/**
 * 把 datetime-local 的值转成后端要的带时区 ISO 串。
 *
 * 无法解析时返回 null（由校验拒绝），不返回一个「当前时间」之类看似合理的兜底——
 * 那会把使用者的输入静默替换成一个他没选过的时刻。
 */
export function fromDatetimeLocalValue(local: string): string | null {
  if (local.trim() === '') return null;
  const parsed = new Date(local);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toISOString();
}
