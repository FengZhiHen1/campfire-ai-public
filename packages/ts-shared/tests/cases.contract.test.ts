/**
 * 正式测试：cases 域类型守卫（从对抗测试转正）。
 */
import { describe, it, expect } from 'vitest';
import {
  isValidCaseCreateRequest,
  isValidCaseUpdate,
  isValidAttachmentRef,
} from '../src/cases/cases.contract';

describe('isValidCaseCreateRequest', () => {
  const valid = {
    title: '测试案例',
    behavior_type: 'self_injury',
    severity: 'moderate',
    scene: 'home',
    immediate_action: '立即干预',
    comforting_phrase: '安抚语句',
    observation_metrics: '观测指标',
    medical_criteria: '医学标准',
    evidence_level: 'ncaep',
  };

  it('全部必填字段存在且非空应返回 true', () => {
    expect(isValidCaseCreateRequest(valid)).toBe(true);
  });

  it('含可选字段的完整数据应返回 true', () => {
    expect(isValidCaseCreateRequest({ ...valid, narrative: '叙事', is_template: false })).toBe(true);
  });

  ['title', 'behavior_type', 'severity', 'scene',
    'immediate_action', 'comforting_phrase', 'observation_metrics',
    'medical_criteria', 'evidence_level',
  ].forEach(field => {
    it(`缺少 ${field} 应返回 false`, () => {
      const { [field]: _, ...rest } = valid;
      expect(isValidCaseCreateRequest(rest)).toBe(false);
    });
  });

  it('必填字段为空字符串应返回 false', () => {
    expect(isValidCaseCreateRequest({ ...valid, title: '' })).toBe(false);
  });

  it('必填字段为纯空格应返回 false', () => {
    expect(isValidCaseCreateRequest({ ...valid, title: '   ' })).toBe(false);
  });

  it('null 应返回 false', () => {
    expect(isValidCaseCreateRequest(null)).toBe(false);
  });

  it('undefined 应返回 false', () => {
    expect(isValidCaseCreateRequest(undefined)).toBe(false);
  });

  it('非对象类型应返回 false', () => {
    expect(isValidCaseCreateRequest('string')).toBe(false);
    expect(isValidCaseCreateRequest(42)).toBe(false);
    expect(isValidCaseCreateRequest([valid])).toBe(false);
  });
});

describe('isValidCaseUpdate', () => {
  it('含 updated_at 应返回 true', () => {
    expect(isValidCaseUpdate({ updated_at: '2026-05-30T12:00:00' })).toBe(true);
  });

  it('缺少 updated_at 应返回 false', () => {
    expect(isValidCaseUpdate({ title: '新标题' })).toBe(false);
  });

  it('updated_at 为空字符串应返回 false', () => {
    expect(isValidCaseUpdate({ updated_at: '' })).toBe(false);
  });

  it('null 和 undefined 应返回 false', () => {
    expect(isValidCaseUpdate(null)).toBe(false);
    expect(isValidCaseUpdate(undefined)).toBe(false);
  });
});

describe('isValidAttachmentRef', () => {
  it('完整附件引用应返回 true', () => {
    expect(isValidAttachmentRef({
      file_name: 'test.pdf',
      minio_path: '/cases/test.pdf',
      file_type: 'application/pdf',
      file_size: 1024,
      uploaded_at: '2026-05-30T12:00:00',
      sort_order: 0,
    })).toBe(true);
  });

  it('缺少 file_name 应返回 false', () => {
    expect(isValidAttachmentRef({ minio_path: '/test.pdf' })).toBe(false);
  });

  it('缺少 minio_path 应返回 false', () => {
    expect(isValidAttachmentRef({ file_name: 'test.pdf' })).toBe(false);
  });

  it('null 应返回 false', () => {
    expect(isValidAttachmentRef(null)).toBe(false);
  });
});
