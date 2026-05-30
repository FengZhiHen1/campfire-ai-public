/**
 * 正式测试：common 域类型守卫（从对抗测试转正）。
 */
import { describe, it, expect } from 'vitest';
import {
  isISODateTime,
  isISODate,
  isValidPaginatedResponse,
} from '../src/common/common.contract';

describe('isISODateTime', () => {
  it('ISO datetime 格式应返回 true', () => {
    expect(isISODateTime('2026-05-30T12:00:00')).toBe(true);
  });

  it('含毫秒应返回 true', () => {
    expect(isISODateTime('2026-05-30T12:00:00.123')).toBe(true);
  });

  it('带 Z 时区应返回 true', () => {
    expect(isISODateTime('2026-05-30T12:00:00Z')).toBe(true);
  });

  it('纯日期（无时间）应返回 false', () => {
    expect(isISODateTime('2026-05-30')).toBe(false);
  });

  it('空字符串应返回 false', () => {
    expect(isISODateTime('')).toBe(false);
  });

  it('带尾部垃圾应返回 false', () => {
    expect(isISODateTime('2026-05-30T12:00:00' + 'x'.repeat(100))).toBe(false);
  });
});

describe('isISODate', () => {
  it('YYYY-MM-DD 应返回 true', () => {
    expect(isISODate('2026-05-30')).toBe(true);
  });

  it('含时间部分应返回 false', () => {
    expect(isISODate('2026-05-30T00:00:00')).toBe(false);
  });

  it('空字符串应返回 false', () => {
    expect(isISODate('')).toBe(false);
  });
});

describe('isValidPaginatedResponse', () => {
  const valid = {
    items: [{ id: '1' }, { id: '2' }],
    total: 2,
    page: 1,
    page_size: 10,
    total_pages: 1,
  };

  it('完整分页响应应返回 true', () => {
    expect(isValidPaginatedResponse(valid)).toBe(true);
  });

  it('空 items 应返回 true', () => {
    expect(isValidPaginatedResponse({ items: [], total: 0, page: 1, page_size: 10, total_pages: 0 })).toBe(true);
  });

  it('items 为字符串应返回 false', () => {
    expect(isValidPaginatedResponse({ ...valid, items: 'not array' })).toBe(false);
  });

  it('total 为字符串应返回 false', () => {
    expect(isValidPaginatedResponse({ ...valid, total: '2' })).toBe(false);
  });

  it('null 应返回 false', () => {
    expect(isValidPaginatedResponse(null)).toBe(false);
  });

  it('带 itemGuard 且全部通过应返回 true', () => {
    const guard = (item: unknown): item is { id: string } =>
      typeof item === 'object' && item !== null && typeof (item as Record<string, unknown>)['id'] === 'string';
    expect(isValidPaginatedResponse(valid, guard)).toBe(true);
  });

  it('带 itemGuard 但某项不通过应返回 false', () => {
    const guard = (item: unknown): item is { id: string } =>
      typeof item === 'object' && item !== null && typeof (item as Record<string, unknown>)['id'] === 'string';
    expect(isValidPaginatedResponse({
      ...valid,
      items: [{ id: '1' }, { noId: true }],
    }, guard)).toBe(false);
  });
});
