/**
 * 模块: features/consult/domain/conversation.test
 * 职责: 会话列表呈现转换的回归守卫——相对时间档位与四字段（缺字段不留占位符）
 * 数据来源:
 *   - docs/design/pages/会话列表页.md: MUST — 布局结构三行信息、edge 行（对象名缺失不渲染）
 * 边界:
 *   - 依赖: domain/conversation、test/fixtures
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言契约外的第五个字段
 */

import { describe, expect, it } from 'vitest';

import { formatRelativeTime, toConversationRow } from './conversation';
import { sessionSummary } from '../test/fixtures';

/** 参照时刻：2026-09-30T12:00:00Z。 */
const NOW = Date.parse('2026-09-30T12:00:00Z');

describe('formatRelativeTime', () => {
  it('按档位给出相对时间', () => {
    expect(formatRelativeTime('2026-09-30T11:59:30Z', NOW)).toBe('刚刚');
    expect(formatRelativeTime('2026-09-30T11:40:00Z', NOW)).toBe('20 分钟前');
    expect(formatRelativeTime('2026-09-30T09:00:00Z', NOW)).toBe('3 小时前');
    expect(formatRelativeTime('2026-09-29T09:00:00Z', NOW)).toBe('昨天');
    expect(formatRelativeTime('2026-09-20T09:00:00Z', NOW)).toBe('9 月 20 日');
  });

  it('时间不可解析时返回空串（不编造时间）', () => {
    expect(formatRelativeTime('不是时间', NOW)).toBe('');
  });
});

describe('toConversationRow', () => {
  it('四个契约字段映射，缺失字段保持 null', () => {
    const row = toConversationRow(
      sessionSummary({ support_object_name: null, last_message_preview: null }),
      NOW,
    );
    expect(row).toEqual({
      sessionId: 's1',
      title: '等候时的沟通',
      relativeTime: '2 小时前',
      supportObjectName: null,
      preview: null,
    });
  });
});
