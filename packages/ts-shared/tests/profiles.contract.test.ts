/**
 * 正式测试：profiles 域类型守卫（从对抗测试转正）。
 */
import { describe, it, expect } from 'vitest';
import {
  isValidProfileCreate,
  isValidBirthDate,
  isValidEventCreate,
} from '../src/profiles/profiles.contract';

describe('isValidProfileCreate', () => {
  const valid = {
    birth_date: '2020-03-15',
    diagnosis_type: 'ASD',
    primary_behavior: 'stereotypy',
  };

  it('全部必填字段存在应返回 true', () => {
    expect(isValidProfileCreate(valid)).toBe(true);
  });

  it('含可选字段应返回 true', () => {
    expect(isValidProfileCreate({ ...valid, nickname: '小明', language_level: 'single_words' })).toBe(true);
  });

  ['birth_date', 'diagnosis_type', 'primary_behavior'].forEach(field => {
    it(`缺少 ${field} 应返回 false`, () => {
      const { [field]: _, ...rest } = valid;
      expect(isValidProfileCreate(rest)).toBe(false);
    });
  });

  it('birth_date 为空字符串应返回 false', () => {
    expect(isValidProfileCreate({ ...valid, birth_date: '' })).toBe(false);
  });

  it('null/undefined/空对象应返回 false', () => {
    expect(isValidProfileCreate(null)).toBe(false);
    expect(isValidProfileCreate(undefined)).toBe(false);
    expect(isValidProfileCreate({})).toBe(false);
  });
});

describe('isValidBirthDate', () => {
  it('YYYY-MM-DD 格式应返回 true', () => {
    expect(isValidBirthDate('2020-01-01')).toBe(true);
    expect(isValidBirthDate('2000-12-31')).toBe(true);
  });

  it('非日期格式应返回 false', () => {
    expect(isValidBirthDate('2020/01/01')).toBe(false);
    expect(isValidBirthDate('2020-1-1')).toBe(false);
    expect(isValidBirthDate('')).toBe(false);
    expect(isValidBirthDate('2020-01-01T00:00:00')).toBe(false);
    expect(isValidBirthDate('abcd-ef-gh')).toBe(false);
  });
});

describe('isValidEventCreate', () => {
  const valid = {
    event_time: '2026-05-30T12:00:00',
    behavior_type: 'meltdown',
    severity_level: 'moderate',
    trigger_description: '噪音触发',
    manifestation: '哭闹行为',
    intervention_tried: '安抚尝试',
    intervention_result: '部分有效',
  };

  it('全部必填字段存在应返回 true', () => {
    expect(isValidEventCreate(valid)).toBe(true);
  });

  ['event_time', 'behavior_type', 'severity_level',
    'trigger_description', 'manifestation',
    'intervention_tried', 'intervention_result',
  ].forEach(field => {
    it(`缺少 ${field} 应返回 false`, () => {
      const { [field]: _, ...rest } = valid;
      expect(isValidEventCreate(rest)).toBe(false);
    });
  });

  it('null/undefined 应返回 false', () => {
    expect(isValidEventCreate(null)).toBe(false);
    expect(isValidEventCreate(undefined)).toBe(false);
  });
});
