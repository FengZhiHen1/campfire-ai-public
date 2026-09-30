/**
 * 模块: features/consult/domain/emergency.test
 * 职责: 应急采集的回归守卫——八项顺序、跳过语义、随时提交与载荷校验
 * 数据来源:
 *   - docs/design/pages/应急表单页.md: MUST — 布局结构（八项可跳过、提交不需答完）
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 5 节（skipped 不带值）
 * 边界:
 *   - 依赖: domain/emergency
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止只测「全填」路径：全跳过与部分作答才是本页的真实用法（RQ-EMG-01）
 */

import { describe, expect, it } from 'vitest';

import {
  createEmergencyDraft,
  EMERGENCY_QUESTIONS,
  isHandled,
  selectOption,
  setNote,
  skipQuestion,
  toEmergencyItems,
  toggleOption,
  validateEmergencyItems,
} from './emergency';

describe('应急草稿 — 八项与跳过语义', () => {
  it('八项顺序与契约第 5 节的 key 一致', () => {
    expect(EMERGENCY_QUESTIONS.map((question) => question.key)).toEqual([
      'medical_red_flags',
      'baseline_deviation',
      'communication',
      'distress',
      'sensory_environment',
      'what_happened',
      'primary_risk',
      'possible_pain',
    ]);
  });

  it('一题未答就是一个未处理项（不是空值）', () => {
    const draft = createEmergencyDraft();
    expect(isHandled(draft, 'medical_red_flags')).toBe(false);
    const items = toEmergencyItems(draft);
    expect(items).toHaveLength(8);
    expect(items.every((item) => item.skipped && item.value === undefined && item.values === undefined)).toBe(true);
  });

  it('作答后清除跳过标记，跳过时清空作答', () => {
    let draft = createEmergencyDraft();
    draft = skipQuestion(draft, 'distress');
    expect(isHandled(draft, 'distress')).toBe(true);
    draft = selectOption(draft, 'distress', 'severe');
    expect(draft.distress).toEqual({ selected: ['severe'], note: '', skipped: false });
    draft = skipQuestion(draft, 'distress');
    expect(draft.distress).toEqual({ selected: [], note: '', skipped: true });
  });

  it('多项勾选可叠加，再次点击取消该项', () => {
    let draft = createEmergencyDraft();
    draft = toggleOption(draft, 'medical_red_flags', 'seizure');
    draft = toggleOption(draft, 'medical_red_flags', 'obvious_pain');
    expect(draft.medical_red_flags?.selected).toEqual(['seizure', 'obvious_pain']);
    draft = toggleOption(draft, 'medical_red_flags', 'seizure');
    expect(draft.medical_red_flags?.selected).toEqual(['obvious_pain']);
  });

  it('全跳过也能提交（提交不需要答完）', () => {
    let draft = createEmergencyDraft();
    for (const question of EMERGENCY_QUESTIONS) draft = skipQuestion(draft, question.key);
    const items = toEmergencyItems(draft);
    expect(items).toHaveLength(8);
    expect(items.every((item) => item.skipped)).toBe(true);
    expect(() => validateEmergencyItems(items)).not.toThrow();
  });

  it('已作答项带值：三选一带 value、多项带 values、自由文本带原文', () => {
    let draft = createEmergencyDraft();
    draft = selectOption(draft, 'baseline_deviation', 'marked');
    draft = toggleOption(draft, 'sensory_environment', 'noise');
    draft = setNote(draft, 'sensory_environment', '还有消毒水味');
    draft = setNote(draft, 'what_happened', '在超市突然捂住耳朵');

    const items = toEmergencyItems(draft);
    const byKey = new Map(items.map((item) => [item.key, item]));
    expect(byKey.get('baseline_deviation')).toEqual({ key: 'baseline_deviation', value: 'marked', skipped: false });
    expect(byKey.get('sensory_environment')).toEqual({
      key: 'sensory_environment',
      values: ['noise', '还有消毒水味'],
      skipped: false,
    });
    expect(byKey.get('what_happened')).toEqual({
      key: 'what_happened',
      value: '在超市突然捂住耳朵',
      skipped: false,
    });
    expect(byKey.get('communication')).toEqual({ key: 'communication', skipped: true });
  });

  it('只有自由补充也算作答（不必勾选）', () => {
    let draft = createEmergencyDraft();
    draft = setNote(draft, 'sensory_environment', '警报声一直在响');
    expect(isHandled(draft, 'sensory_environment')).toBe(true);
    const items = toEmergencyItems(draft);
    expect(items.find((item) => item.key === 'sensory_environment')).toEqual({
      key: 'sensory_environment',
      values: ['警报声一直在响'],
      skipped: false,
    });
  });
});

describe('应急载荷校验', () => {
  it('拒绝缺项、越界 key 与「标了跳过却带值」', () => {
    expect(() => validateEmergencyItems([])).toThrow();
    expect(() =>
      validateEmergencyItems([{ key: '不存在的项', skipped: true }]),
    ).toThrow();
    expect(() =>
      validateEmergencyItems([
        { key: 'medical_red_flags', value: 'x', skipped: true },
        ...toEmergencyItems(createEmergencyDraft()).slice(1),
      ]),
    ).toThrow();
  });

  it('拒绝「没标跳过却没有值」', () => {
    const items = toEmergencyItems(createEmergencyDraft());
    const withEmptyValue = items.map((item) =>
      item.key === 'baseline_deviation' ? { key: item.key, skipped: false } : item,
    );
    expect(() => validateEmergencyItems(withEmptyValue)).toThrow();
  });
});
