/**
 * 模块: features/library/domain/libraryDomain.test
 * 职责: 案例与资料呈现措辞、失败分类、空态判定与 deep-link 三态的纯函数用例
 * 数据来源:
 *   - docs/技术设计/面/profile/资料库面HTTP契约.md: MUST — 第 3.1、5、6 节
 *   - docs/design/pages/案例库浏览页.md: MUST — 第 21、41、49、53 行
 * 边界:
 *   - 依赖: features/library/domain/*
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言 503 的文案与「没有找到相关内容」相同
 *   - 禁止断言 owner 显示成「已审阅」
 */

import { describe, expect, it } from 'vitest';

import type { GetLibraryItemResponse, LibraryItem } from '../../../shared/types/library';
import { deepLinkOutcome, parseDeepLink } from './deepLink';
import { classifyLibraryFailure, emptyStateKind, libraryFailureDescription, libraryFailureTitle } from './failures';
import { isFictional, itemMetaParts, reviewStatusLabel, statusLabel } from './labels';

/** 造一条条目。 */
function item(overrides: Partial<LibraryItem> = {}): LibraryItem {
  return {
    item_id: 'c1',
    library: 'case',
    title: '超市哭闹时的分流做法',
    snippet: '先把人带到安静处，再给两个可选的做法',
    source: '某机构公开材料',
    applicable_scope: '学龄前经验（家长自述）',
    status: 'published',
    locator: 'section-3',
    ranking: { rank: 1, channels: ['vector'] },
    ...overrides,
  };
}

describe('资料库措辞', () => {
  it('三种状态都直出文字，虚构样例用文字而不是颜色承载', () => {
    expect(statusLabel('published')).toBe('已发表');
    expect(statusLabel('internal')).toBe('内部');
    expect(statusLabel('fictional')).toBe('虚构样例');
    expect(isFictional('fictional')).toBe(true);
    expect(isFictional('published')).toBe(false);
  });

  it('owner 显示为「项目所有者核准」，不是「已审阅」', () => {
    expect(reviewStatusLabel('owner')).toBe('项目所有者核准');
    expect(reviewStatusLabel('owner')).not.toBe('已审阅');
    expect(reviewStatusLabel('professional')).toBe('专业审阅');
  });

  it('元信息行只拼接存在的字段，缺字段不补默认措辞', () => {
    const parts = itemMetaParts({ source: '某机构公开材料' });
    expect(parts).toEqual(['来源：某机构公开材料']);
  });

  it('资料条目拿到的是 null（不是缺键）时，元信息行不出现空段，也不出现「访谈 null」', () => {
    // 后端逐字段透传：资料侧这六项在响应里是 null。只判 undefined 的守卫被 null
    // 全部放行，元信息行会拼成「来源：某机构公开材料 ·  ·  ·  ·  · 访谈 null」。
    const parts = itemMetaParts({
      source: '某机构公开材料',
      source_type: null,
      evidence_level: null,
      review_status: null,
      authorization: null,
      interview_at: null,
    });
    expect(parts).toEqual(['来源：某机构公开材料']);
    expect(parts.join(' · ')).toBe('来源：某机构公开材料');
  });

  it('元信息行含六项必带字段与授权', () => {
    const parts = itemMetaParts({
      source: '某机构公开材料',
      source_type: '家长自述',
      evidence_level: 'OBSERVATIONAL',
      review_status: 'owner',
      authorization: '已授权',
      interview_at: '2026-09-01',
    });
    expect(parts).toContain('已授权');
    expect(parts).toContain('项目所有者核准');
    expect(parts).toContain('访谈 2026-09-01');
  });
});

describe('检索失败与空态必须可区分', () => {
  it('503 是「检索暂时不可用」，不是「没有找到相关内容」', () => {
    const failure = classifyLibraryFailure(503);
    expect(failure.kind).toBe('search-unavailable');
    expect(libraryFailureTitle(failure)).toBe('检索暂时不可用');
    expect(libraryFailureTitle(failure)).not.toContain('没有找到');
    expect(libraryFailureDescription(failure)).toContain('不等于没有内容');
  });

  it('有检索词的空结果与库为空的空结果分开', () => {
    expect(emptyStateKind('超市哭闹')).toBe('no-results');
    expect(emptyStateKind('   ')).toBe('library-not-ready');
  });
});

describe('deep-link 解析与三态', () => {
  it('解析 item 与 section；不认识的 section 当没给', () => {
    expect(parseDeepLink('?item=c1')).toEqual({ itemId: 'c1', section: null });
    expect(parseDeepLink('?section=knowledge')).toEqual({ itemId: null, section: 'knowledge' });
    expect(parseDeepLink('?section=bogus')).toEqual({ itemId: null, section: null });
    expect(parseDeepLink('')).toEqual({ itemId: null, section: null });
    expect(parseDeepLink('?item=  ')).toEqual({ itemId: null, section: null });
  });

  it('在库：返回条目本身', () => {
    const response: GetLibraryItemResponse = { item: item() };
    const outcome = deepLinkOutcome(response);
    expect(outcome.kind).toBe('in-library');
  });

  it('已撤下：只带标题，不带正文与其他字段', () => {
    const response: GetLibraryItemResponse = { item: null, withdrawn: true, title: '某个案例' };
    const outcome = deepLinkOutcome(response);
    expect(outcome).toEqual({ kind: 'withdrawn', title: '某个案例' });
    // 结构上就拿不到正文：撤下卡不可能渲染出 item 里的任何东西。
    expect(outcome).not.toHaveProperty('item');
  });

  it('撤下但没给标题 → 如实写「这条来源」，不编一个标题', () => {
    expect(deepLinkOutcome({ item: null, withdrawn: true })).toEqual({ kind: 'withdrawn', title: '这条来源' });
  });

  it('空体 → 按不存在处理（页面按普通进入）', () => {
    expect(deepLinkOutcome({ item: null })).toEqual({ kind: 'missing' });
  });
});
