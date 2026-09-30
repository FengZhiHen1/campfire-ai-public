/**
 * 模块: src/infrastructure/auth/authPort.test
 * 职责: 认证端口实现的错误映射——SDK 的四种抛出物与三种返回状态都收敛成显式 AuthError
 * 数据来源:
 *   - docs/design/pages/登录与注册.md: MUST — 数据与文案节（错误文案逐字）、状态覆盖表（限流）
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 9 节（失败语义）
 * 边界:
 *   - 依赖: infrastructure/auth/authPort、supertokens-web-js
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言后端原文被透出（物化后的错误消息必须是契约文案）
 *
 * 为什么必须打桩 SDK：真实登录要 core 与数据库（T12 的联调范围）。
 * 桩打在 SDK 的模块边界上，因此被测的是「SDK 的形状 → 我们的分类」这一段真实映射逻辑，
 * 而不是把所有逻辑都替换掉的空测试。
 *
 * 为什么桩结果要用辅助函数拼：SDK 的返回类型是带 fetchResponse 的判别联合，
 * 这个字段存在与否本身就是 SDK 契约的一部分，直接 `as` 断言会把它抹掉（tsc 会拒绝）。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('supertokens-web-js/recipe/emailpassword', () => ({
  default: { signIn: vi.fn(), signUp: vi.fn() },
}));
vi.mock('./session', () => ({
  supertokensSessionPort: { doesSessionExist: vi.fn(), signOut: vi.fn() },
}));

import EmailPassword from 'supertokens-web-js/recipe/emailpassword';
import STGeneralError from 'supertokens-web-js/utils/error';

import { supertokensAuthPort } from './authPort';
import { AuthError } from '../../features/accounts/domain/authFailure';

const signIn = vi.mocked(EmailPassword.signIn);
const signUp = vi.mocked(EmailPassword.signUp);

type SignInResult = Awaited<ReturnType<typeof EmailPassword.signIn>>;
type SignUpResult = Awaited<ReturnType<typeof EmailPassword.signUp>>;

/** 造一个 OK 结果；fetchResponse 用真实 Response（SDK 契约要求它存在）。 */
function okResult(email: string | null): { user: { emails: string[] }; fetchResponse: Response } {
  return { user: { emails: email === null ? [] : [email] }, fetchResponse: new Response(null, { status: 200 }) };
}

/** 造一个 FIELD_ERROR 结果。 */
function fieldError(formFields: { id: string; error: string }[]): {
  formFields: { id: string; error: string }[];
  fetchResponse: Response;
} {
  return { formFields, fetchResponse: new Response(null, { status: 200 }) };
}

/** 登录成功桩。 */
function loginOk(email: string | null): SignInResult {
  return { status: 'OK', ...okResult(email) } as SignInResult;
}

/** 注册成功桩。 */
function signUpOk(email: string | null): SignUpResult {
  return { status: 'OK', ...okResult(email) } as SignUpResult;
}

/** 登录字段错误桩。 */
function loginFieldError(formFields: { id: string; error: string }[]): SignInResult {
  return { status: 'FIELD_ERROR', ...fieldError(formFields) } as SignInResult;
}

/** 注册字段错误桩。 */
function signUpFieldError(formFields: { id: string; error: string }[]): SignUpResult {
  return { status: 'FIELD_ERROR', ...fieldError(formFields) } as SignUpResult;
}

const LOGIN = { account: '阿澈的妈妈', password: 'campfire2026' };
const REGISTER = { ...LOGIN, inviteCode: 'A1B2C3D4' };

/** 取回被拒的分类；抛出的不是 AuthError 时直接让用例失败（而不是静默通过）。 */
async function rejectionKind(action: () => Promise<unknown>): Promise<string> {
  try {
    await action();
  } catch (error) {
    if (error instanceof AuthError) return error.kind;
    throw error;
  }
  throw new Error('预期被拒绝，但调用成功了');
}

beforeEach(() => {
  signIn.mockReset();
  signUp.mockReset();
});

describe('submitLogin', () => {
  it('P0 OK → 返回账号名，不抛异常', async () => {
    signIn.mockResolvedValue(loginOk('阿澈的妈妈'));

    await expect(supertokensAuthPort.submitLogin(LOGIN)).resolves.toEqual({ accountName: '阿澈的妈妈' });
  });

  it('P0 OK 但用户对象里没有账号名 → accountName 为 null（不编造空串）', async () => {
    signIn.mockResolvedValue(loginOk(null));

    await expect(supertokensAuthPort.submitLogin(LOGIN)).resolves.toEqual({ accountName: null });
  });

  it('P0 凭据错误 → invalid-credentials，文案逐字', async () => {
    signIn.mockResolvedValue({ status: 'WRONG_CREDENTIALS_ERROR' } as SignInResult);

    await expect(supertokensAuthPort.submitLogin(LOGIN)).rejects.toThrow('账号名或密码不正确');
    expect(await rejectionKind(() => supertokensAuthPort.submitLogin(LOGIN))).toBe('invalid-credentials');
  });

  it('P0 字段级拒绝（账号名形状）→ 同样归 invalid-credentials，不另立可区分的原因', async () => {
    signIn.mockResolvedValue(loginFieldError([{ id: 'email', error: 'Email is not valid' }]));

    expect(await rejectionKind(() => supertokensAuthPort.submitLogin(LOGIN))).toBe('invalid-credentials');
  });

  it('P1 SIGN_IN_NOT_ALLOWED（安全策略）→ unexpected，不当成凭据错误', async () => {
    signIn.mockResolvedValue({ status: 'SIGN_IN_NOT_ALLOWED', reason: 'security' } as unknown as SignInResult);

    expect(await rejectionKind(() => supertokensAuthPort.submitLogin(LOGIN))).toBe('unexpected');
  });

  it('P0 SDK 抛 STGeneralError → 不透出后端原文', async () => {
    signIn.mockRejectedValue(new STGeneralError('后端原始英文消息'));

    await expect(supertokensAuthPort.submitLogin(LOGIN)).rejects.toThrow('操作没有成功，请稍后重试');
  });

  it('P0 SDK 抛 Response(429) → rate-limited，限流文案逐字', async () => {
    signIn.mockRejectedValue(new Response(null, { status: 429 }));

    await expect(supertokensAuthPort.submitLogin(LOGIN)).rejects.toThrow('尝试次数过多，请稍后再试');
    expect(await rejectionKind(() => supertokensAuthPort.submitLogin(LOGIN))).toBe('rate-limited');
  });

  it('P1 SDK 抛 Response(503) → service-unavailable', async () => {
    signIn.mockRejectedValue(new Response(null, { status: 503 }));

    expect(await rejectionKind(() => supertokensAuthPort.submitLogin(LOGIN))).toBe('service-unavailable');
  });

  it('P1 网络错误（TypeError）→ service-unavailable，不得说成「密码不正确」', async () => {
    signIn.mockRejectedValue(new TypeError('Failed to fetch'));

    expect(await rejectionKind(() => supertokensAuthPort.submitLogin(LOGIN))).toBe('service-unavailable');
  });

  it('P2 未知抛出物 → unexpected，仍收敛为 AuthError', async () => {
    signIn.mockRejectedValue({ weird: true });

    expect(await rejectionKind(() => supertokensAuthPort.submitLogin(LOGIN))).toBe('unexpected');
  });
});

describe('submitRegister', () => {
  it('P0 OK → 返回账号名', async () => {
    signUp.mockResolvedValue(signUpOk('新账号'));

    await expect(supertokensAuthPort.submitRegister(REGISTER)).resolves.toEqual({ accountName: '新账号' });
  });

  it('P0 邀请码被拒（GENERAL_ERROR）→ invite-rejected，文案逐字', async () => {
    signUp.mockRejectedValue(new STGeneralError('邀请码无效或已不可用'));

    await expect(supertokensAuthPort.submitRegister(REGISTER)).rejects.toThrow('邀请码无效或已被使用');
    expect(await rejectionKind(() => supertokensAuthPort.submitRegister(REGISTER))).toBe('invite-rejected');
  });

  it('P1 判定通道对 GENERAL_ERROR 的类身份不敏感（canary：跨模块实例也命中）', async () => {
    // 实测本包环境里 supertokens-web-js/utils/error 与 SDK 内部 require 到的是两份类对象，
    // 用 `instanceof` 判定会恒为假——那正是本包第一版实现吞掉邀请码拒绝文案的原因。
    // 这里构造一个「标记相同但类不同」的抛出物：判定必须仍然命中。
    class ForeignGeneralError extends Error {
      isSuperTokensGeneralError = true;
    }
    signUp.mockRejectedValue(new ForeignGeneralError('邀请码无效或已不可用'));

    expect(await rejectionKind(() => supertokensAuthPort.submitRegister(REGISTER))).toBe('invite-rejected');
  });

  it('P1 无标记的普通 Error 不得被误判为 GENERAL_ERROR（阴性对照）', async () => {
    signUp.mockRejectedValue(new Error('随便一个错误'));

    expect(await rejectionKind(() => supertokensAuthPort.submitRegister(REGISTER))).toBe('unexpected');
  });

  it('P0 账号名已被占用（FIELD_ERROR 落在 email 字段）→ account-unusable', async () => {
    signUp.mockResolvedValue(
      signUpFieldError([{ id: 'email', error: 'This email already exists. Please sign in instead.' }]),
    );

    expect(await rejectionKind(() => supertokensAuthPort.submitRegister(REGISTER))).toBe('account-unusable');
  });

  it('P0 账号名格式被拒（同一个 FIELD_ERROR 形状）→ 与「已被占用」同一分类（线上不可区分）', async () => {
    // 实测 supertokens_python 的 api/signup.py：EmailAlreadyExistsError 走
    // raise_form_field_exception("EMAIL_ALREADY_EXISTS_ERROR", [email])，而账号名未过
    // 默认 email 校验器走 api/utils.py 的 validate_form_or_throw_error——两者的线上形状
    // 完全相同（都是 {status:"FIELD_ERROR", formFields:[{id:"email"}]}）。前端因此无法区分，
    // 这个用例把「不假装能区分」钉住。
    signUp.mockResolvedValue(signUpFieldError([{ id: 'email', error: 'Email is not valid' }]));

    expect(await rejectionKind(() => supertokensAuthPort.submitRegister(REGISTER))).toBe('account-unusable');
  });

  it('P1 密码不合规（FIELD_ERROR 落在 password 字段）→ weak-password', async () => {
    signUp.mockResolvedValue(
      signUpFieldError([{ id: 'password', error: 'Password must contain at least 8 characters, including a number' }]),
    );

    expect(await rejectionKind(() => supertokensAuthPort.submitRegister(REGISTER))).toBe('weak-password');
  });

  it('P1 账号名与密码同时不合规 → 优先报密码（两条字段错误都在时按字段分派）', async () => {
    signUp.mockResolvedValue(
      signUpFieldError([
        { id: 'email', error: 'Email is not valid' },
        { id: 'password', error: 'Password must contain at least 8 characters' },
      ]),
    );

    expect(await rejectionKind(() => supertokensAuthPort.submitRegister(REGISTER))).toBe('weak-password');
  });

  it('P1 邀请码字段级拒绝 → invite-rejected（与 GENERAL_ERROR 同一条文案）', async () => {
    signUp.mockResolvedValue(signUpFieldError([{ id: 'inviteCode', error: '任意后端原文' }]));

    await expect(supertokensAuthPort.submitRegister(REGISTER)).rejects.toThrow('邀请码无效或已被使用');
  });

  it('P1 注册遇 429 → rate-limited', async () => {
    signUp.mockRejectedValue(new Response(null, { status: 429 }));

    expect(await rejectionKind(() => supertokensAuthPort.submitRegister(REGISTER))).toBe('rate-limited');
  });

  it('P1 SIGN_UP_NOT_ALLOWED（安全策略）→ unexpected', async () => {
    signUp.mockResolvedValue({ status: 'SIGN_UP_NOT_ALLOWED', reason: 'security' } as unknown as SignUpResult);

    expect(await rejectionKind(() => supertokensAuthPort.submitRegister(REGISTER))).toBe('unexpected');
  });

  it('P0 提交给 SDK 的表单字段名与后端契约一致（email/password/inviteCode）', async () => {
    signUp.mockResolvedValue(signUpOk('新账号'));

    await supertokensAuthPort.submitRegister(REGISTER);

    // 字段名不一致的表现是「注册总是被拒」且无人知道为什么——这里把它钉住。
    expect(signUp).toHaveBeenCalledWith({
      formFields: [
        { id: 'email', value: '阿澈的妈妈' },
        { id: 'password', value: 'campfire2026' },
        { id: 'inviteCode', value: 'A1B2C3D4' },
      ],
    });
  });

  it('P0 提交给 SDK 的登录字段名与后端契约一致（email/password）', async () => {
    signIn.mockResolvedValue(loginOk('阿澈的妈妈'));

    await supertokensAuthPort.submitLogin(LOGIN);

    expect(signIn).toHaveBeenCalledWith({
      formFields: [
        { id: 'email', value: '阿澈的妈妈' },
        { id: 'password', value: 'campfire2026' },
      ],
    });
  });
});
