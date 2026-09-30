/**
 * 模块: features/profile/domain/items.test
 * 职责: 档案条目呈现规则的纯函数用例——来源措辞、候选/时效判定、按领域分组
 * 数据来源:
 *   - docs/design/pages/档案页.md: MUST — 第 23～26、50～52 行
 *   - docs/技术设计/technical-details/个性化档案.md: MUST — 第 6 节十四个模块与兜底
 * 边界:
 *   - 依赖: features/profile/domain/items、features/profile/domain/domains
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言「未知领域被丢弃」（未知取值必须归「其他」而不是消失）
 */

import { describe, expect, it } from 'vitest';

import type { ProfileItem } from '../../../shared/types/profile';
import { DOMAIN_LABELS, DOMAIN_ORDER, domainLabel, toProfileDomain } from './domains';
import { freshnessLabel, groupByDomain, isCandidate, isStale, itemMetaLine, originLabel } from './items';

/** 造一条条目；只覆盖断言需要的字段，其余给契约形状的默认值。 */
function item(overrides: Partial<ProfileItem> = {}): ProfileItem {
  return {
    item_id: 'i1',
    support_object_id: 'o1',
    domain: 'communication',
    topic: '表达方式',
    description: '用图片卡表达需求',
    contexts: [],
    manifestations: [],
    person_report: null,
    probable_need: null,
    helpful_support: [],
    unhelpful_support: [],
    origin: 'user_statement',
    source: {},
    confirmation: 'confirmed',
    freshness: 'current',
    first_recorded_at: '2026-10-02T09:00:00Z',
    last_confirmed_at: '2026-10-02T09:00:00Z',
    superseded_by: null,
    ...overrides,
  };
}

describe('档案领域取值', () => {
  it('十四个一级模块加「其他」共十五个取值，且顺序固定', () => {
    expect(Object.keys(DOMAIN_LABELS)).toHaveLength(15);
    expect(DOMAIN_ORDER).toHaveLength(15);
    expect(DOMAIN_ORDER[DOMAIN_ORDER.length - 1]).toBe('other');
  });

  it('未知领域取值归「其他」——条目在界面上不许消失', () => {
    expect(toProfileDomain('not_a_domain')).toBe('other');
    expect(domainLabel('not_a_domain')).toBe('其他');
  });

  it('已知取值原样映射', () => {
    expect(domainLabel('sensory_processing')).toBe('感觉处理');
    expect(toProfileDomain('goals_and_plans')).toBe('goals_and_plans');
  });
});

describe('档案条目呈现规则', () => {
  it('六类来源都有中文措辞', () => {
    expect(originLabel('user_statement')).toBe('你说过');
    expect(originLabel('guardian_observation')).toBe('你的观察');
    expect(originLabel('third_party_report')).toBe('第三方转述');
    expect(originLabel('document')).toBe('文档记录');
    expect(originLabel('system_observation')).toBe('系统观察');
    expect(originLabel('ai_inference')).toBe('AI 归纳');
  });

  it('时效措辞只在需要提醒时出现', () => {
    expect(freshnessLabel('current')).toBeNull();
    expect(freshnessLabel('stale')).toBe('已降权');
    expect(freshnessLabel('historical')).toBe('已更正');
  });

  it('候选判定看 confirmation 而不是来源是否属推断', () => {
    expect(isCandidate(item({ confirmation: 'unconfirmed' }))).toBe(true);
    // 使用者的自述也可能未被确认：判据是确认状态，不是 origin。
    expect(isCandidate(item({ origin: 'user_statement', confirmation: 'unconfirmed' }))).toBe(true);
    expect(isCandidate(item({ origin: 'ai_inference', confirmation: 'confirmed' }))).toBe(false);
  });

  it('降权判定只看 freshness', () => {
    expect(isStale(item({ freshness: 'stale' }))).toBe(true);
    expect(isStale(item({ freshness: 'current' }))).toBe(false);
  });

  it('元信息行区分「确认时间」与「记录时间」', () => {
    expect(itemMetaLine(item())).toContain('10-02 确认');
    // 未确认条目没有确认时间——不得共用一句「10-02」冒充确认。
    expect(itemMetaLine(item({ confirmation: 'unconfirmed', last_confirmed_at: null }))).toContain('记录');
  });

  it('元信息行带转述者（经监护人转述这一类事实）', () => {
    const meta = itemMetaLine(item({ source: { relayed_by: '监护人' } }));
    expect(meta).toContain('经监护人转述');
  });

  it('非法时间如实写「时间未知」而不是编造一个日期', () => {
    expect(itemMetaLine(item({ last_confirmed_at: 'not-a-date' }))).toContain('时间未知');
  });
});

describe('按领域分组', () => {
  it('空组不出现，组按固定顺序排列，组内保持传入顺序', () => {
    const groups = groupByDomain([
      item({ item_id: 'a', domain: 'goals_and_plans' }),
      item({ item_id: 'b', domain: 'communication' }),
      item({ item_id: 'c', domain: 'communication' }),
    ]);

    expect(groups.map((group) => group.domain)).toEqual(['communication', 'goals_and_plans']);
    expect(groups[0].items.map((entry) => entry.item_id)).toEqual(['b', 'c']);
  });

  it('未知领域的条目落进「其他」组，不会被丢掉', () => {
    const groups = groupByDomain([item({ domain: 'brand_new_domain' })]);
    expect(groups).toHaveLength(1);
    expect(groups[0].domain).toBe('other');
    expect(groups[0].items).toHaveLength(1);
  });

  it('空输入返回空分组', () => {
    expect(groupByDomain([])).toEqual([]);
  });
});
