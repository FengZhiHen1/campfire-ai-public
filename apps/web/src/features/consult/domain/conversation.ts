/**
 * 模块: features/consult/domain/conversation
 * 职责: 会话列表的纯呈现转换——相对时间与四字段展示数据
 * 数据来源:
 *   - docs/design/pages/会话列表页.md: MUST — 布局结构（三行信息）、数据与文案（四个字段）
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 3.2 节（列表返回形状）
 * 边界:
 *   - 依赖: shared/types/consult（SessionSummary）
 *   - 被依赖: viewModel 的 useSessionList 与 view 的会话列表页
 * 禁止行为:
 *   - 禁止发明契约未定义的第五个字段（页面设计数据与文案节：四个字段即端点形状）
 *   - 禁止在字段缺失时留占位符（对象名缺失即不渲染该段，契约第 3.2 节）
 */

import type { SessionSummary } from '../../../shared/types/consult';

/** 一分钟 / 一小时 / 一天的毫秒数；相对时间的档位边界。 */
const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

/**
 * 相对时间文案。
 *
 * 前置: iso 是可被 Date 解析的时间串；now 为参照时刻（毫秒）
 * 后置: 返回「刚刚 / N 分钟前 / N 小时前 / 昨天 / M 月 D 日」之一
 * 异常: 时间串不可解析时返回空串——列表按「时间缺失」处理，不编造时间
 */
export function formatRelativeTime(iso: string, now: number): string {
  const timestamp = Date.parse(iso);
  if (Number.isNaN(timestamp)) return '';
  const delta = now - timestamp;
  if (delta < MINUTE_MS) return '刚刚';
  if (delta < HOUR_MS) return `${Math.floor(delta / MINUTE_MS)} 分钟前`;
  if (delta < DAY_MS) return `${Math.floor(delta / HOUR_MS)} 小时前`;
  if (delta < 2 * DAY_MS) return '昨天';
  const date = new Date(timestamp);
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日`;
}

/** 会话行的展示数据（页面设计的四字段）。 */
export interface ConversationRow {
  sessionId: string;
  title: string;
  /** 相对时间；时间不可解析时为空串（view 不渲染该段）。 */
  relativeTime: string;
  /** 支持对象名；null = 缺失，view 不渲染该段（不留占位符）。 */
  supportObjectName: string | null;
  /** 末条消息预览；null = 缺失，view 不渲染该段。 */
  preview: string | null;
}

/** 列表项 → 展示行。纯函数：不读时钟（now 由调用方注入，测试可控）。 */
export function toConversationRow(summary: SessionSummary, now: number): ConversationRow {
  return {
    sessionId: summary.session_id,
    title: summary.title,
    relativeTime: formatRelativeTime(summary.updated_at, now),
    supportObjectName: summary.support_object_name,
    preview: summary.last_message_preview,
  };
}
