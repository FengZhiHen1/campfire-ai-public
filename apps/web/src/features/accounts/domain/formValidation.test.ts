/**
 * 模块: src/features/accounts/formValidation.test
 * 职责: 表单校验纯函数的用例——空字段、密码规则、邀请码非空与「不校验邮箱语义」
 * 数据来源:
 *   - docs/design/pages/登录与注册.md: MUST — 状态覆盖表（invalid-after-touched 的内联错误）
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 3、4 节（账号名 + 密码；官方默认密码校验器）
 * 边界:
 *   - 依赖: features/accounts/domain/formValidation
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言邮箱格式被校验（一期不存在邮箱语义，这正是要守住的边界）
 */

import { describe, expect, it } from 'vitest';

import { FIELD_MESSAGES, validateLoginForm, validateRegisterForm } from './formValidation';

describe('validateLoginForm', () => {
  it('P0 全部为空 → 账号名与密码各有错误', () => {
    const errors = validateLoginForm({ account: '', password: '' });

    expect(errors.account).toBe(FIELD_MESSAGES.account);
    expect(errors.password).toBe(FIELD_MESSAGES.password);
  });

  it('P0 合法输入 → 无任何字段错误', () => {
    expect(validateLoginForm({ account: '阿澈的妈妈', password: 'campfire2026' })).toEqual({});
  });

  it('P1 只填空白字符视为未填', () => {
    const errors = validateLoginForm({ account: '   ', password: 'campfire2026' });

    expect(errors.account).toBe(FIELD_MESSAGES.account);
  });

  it('P0 密码短于 8 位 → 密码规则错误', () => {
    const errors = validateLoginForm({ account: 'acct', password: 'abc123' });

    expect(errors.password).toBe(FIELD_MESSAGES.passwordRule);
  });

  it('P0 密码少于一个数字 → 密码规则错误（与身份服务默认校验器同形）', () => {
    const errors = validateLoginForm({ account: 'acct', password: 'abcdefghij' });

    expect(errors.password).toBe(FIELD_MESSAGES.passwordRule);
  });

  it('P0 密码少于一个字母 → 密码规则错误', () => {
    const errors = validateLoginForm({ account: 'acct', password: '1234567890' });

    expect(errors.password).toBe(FIELD_MESSAGES.passwordRule);
  });

  it('P1 账号名含 @ 与不含 @ 都通过（账号名不是邮箱语义）', () => {
    expect(validateLoginForm({ account: 'someone@example.com', password: 'campfire2026' })).toEqual({});
    expect(validateLoginForm({ account: '阿澈的妈妈', password: 'campfire2026' })).toEqual({});
  });
});

describe('validateRegisterForm', () => {
  it('P0 邀请码为空 → 邀请码字段错误', () => {
    const errors = validateRegisterForm({ account: 'acct', password: 'campfire2026', inviteCode: '' });

    expect(errors.inviteCode).toBe(FIELD_MESSAGES.inviteCode);
  });

  it('P0 三字段齐备 → 无错误', () => {
    expect(validateRegisterForm({ account: 'acct', password: 'campfire2026', inviteCode: 'A1B2C3D4' })).toEqual({});
  });

  it('P1 邀请码只做非空校验，不判形状（形状判定归服务端）', () => {
    // 刻意用短码与含空格的码：前端不得据此拒绝——提前判形状会把「码无效」
    // 与「码写错」变成两条可区分的路径，构成枚举渠道（认证与账号第 4 节）。
    expect(validateRegisterForm({ account: 'acct', password: 'campfire2026', inviteCode: 'A1' })).toEqual({});
    expect(validateRegisterForm({ account: 'acct', password: 'campfire2026', inviteCode: ' A B ' })).toEqual({});
  });
});
