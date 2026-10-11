/**
 * 模块: features/profile/domain/formValidation.test
 * 职责: 档案页表单校验与失败分类的纯函数用例
 * 数据来源:
 *   - docs/design/pages/档案页.md: MUST — 第 72 行（空值提交禁用而不是弹错）
 *   - docs/技术设计/面/profile/档案面HTTP契约.md: MUST — 第 1 节 422、第 6 节失败语义
 * 边界:
 *   - 依赖: features/profile/domain/formValidation、features/profile/domain/failures
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言 404 与 409 合并成同一句文案（归档必须与越权可区分）
 */

import { describe, expect, it } from 'vitest';

import { classifyProfileFailure, failureFromError, isRetryable, profileFailureInline, profileFailureTitle } from './failures';
import { emptyItemDraft, isKnownDomain, itemDraftChanged, validateItemDraft, validateObjectName } from './formValidation';

describe('对象名字校验', () => {
  it('去空白后为空即拒', () => {
    expect(validateObjectName('   ')).toEqual({ displayName: '名字不能为空' });
    expect(validateObjectName('小宝')).toEqual({});
  });
});

describe('条目草稿校验', () => {
  const draft = { domain: 'communication', topic: '表达方式', description: '用图片卡表达需求' };

  it('合法草稿无错误', () => {
    expect(validateItemDraft(draft)).toEqual({});
  });

  it('空主题与空描述都被拒（服务端也会 422，这里提前给出可读原因）', () => {
    expect(validateItemDraft({ ...draft, topic: ' ' })).toHaveProperty('topic');
    expect(validateItemDraft({ ...draft, description: '' })).toHaveProperty('description');
  });

  it('未知领域被拒——不把服务端一定会拒的载荷放行', () => {
    expect(validateItemDraft({ ...draft, domain: 'not_a_domain' })).toHaveProperty('domain');
    expect(isKnownDomain('communication')).toBe(true);
    expect(isKnownDomain('not_a_domain')).toBe(false);
  });

  it('纠正时内容与原描述逐字相同 → 拒（「没有需要更正的地方」）', () => {
    // unchanged 由调用方比对原条目后传入：为真即「没有变更」。
    expect(validateItemDraft(draft, true)).toHaveProperty('description');
    expect(validateItemDraft({ ...draft, description: '改了' }, false)).toEqual({});
  });

  it('空草稿与「已编辑」同源：只改领域也算已编辑（否则这次选择会被静默丢弃）', () => {
    expect(itemDraftChanged(emptyItemDraft())).toBe(false);
    expect(itemDraftChanged({ ...emptyItemDraft(), domain: 'communication' })).toBe(true);
    expect(itemDraftChanged({ ...emptyItemDraft(), topic: '睡前' })).toBe(true);
    // 清空回空白内容就是没改过：切换对象时不该为「什么都没留下」弹确认。
    expect(itemDraftChanged({ ...emptyItemDraft(), topic: '  ', description: '' })).toBe(false);
  });
});

describe('档案面失败分类', () => {
  it('三个语义各自成型，归档不与越权共用文案', () => {
    expect(classifyProfileFailure(404).kind).toBe('not-accessible');
    expect(classifyProfileFailure(409).kind).toBe('object-archived');
    expect(classifyProfileFailure(422).kind).toBe('invalid-payload');

    const notAccessible = profileFailureTitle({ kind: 'not-accessible' });
    const archived = profileFailureTitle({ kind: 'object-archived' });
    expect(archived).not.toBe(notAccessible);
  });

  it('归档的说明给出恢复出路（属主需要知道原因才能去恢复）', () => {
    expect(profileFailureInline({ kind: 'object-archived' })).toContain('归档');
    expect(profileFailureInline({ kind: 'object-archived' })).toContain('恢复');
  });

  it('只有未知失败给重试（越权与不存在重试无用）', () => {
    expect(isRetryable({ kind: 'unknown' })).toBe(true);
    expect(isRetryable({ kind: 'not-accessible' })).toBe(false);
    expect(isRetryable({ kind: 'object-archived' })).toBe(false);
  });

  it('从异常对象取状态码：结构化检查而不是 instanceof（不 import 传输实现）', () => {
    expect(failureFromError({ status: 409 }).kind).toBe('object-archived');
    expect(failureFromError(new Error('网络中断')).kind).toBe('unknown');
    expect(failureFromError(null).kind).toBe('unknown');
  });
});
