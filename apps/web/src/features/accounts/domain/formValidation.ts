/**
 * 模块: features/accounts/domain/formValidation
 * 职责: 登录与注册表单的纯校验规则与字段文案——无副作用、可被表单与用例共用
 * 数据来源:
 *   - docs/design/pages/登录与注册.md: MUST — 状态覆盖表（untouched/invalid-after-touched）、布局结构（字段清单）
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 3、4 节（账号名 + 密码，无邮箱字段）
 * 边界:
 *   - 依赖: 无（纯函数，不 import 框架）
 *   - 被依赖: features/accounts 的 application 用例与 viewModel 表单 hook
 * 禁止行为:
 *   - 禁止校验邮箱格式（账号名不是邮箱语义，AC-16 反向：不存在邮箱字段）
 *   - 禁止在本层持有表单状态（touched/dirty 归 viewModel）
 */

/** 登录表单的值。 */
export interface LoginFormValues {
  account: string;
  password: string;
}

/** 注册表单的值：登录字段 + 邀请码。 */
export interface RegisterFormValues extends LoginFormValues {
  inviteCode: string;
}

/** 表单字段名；用于 touched/errors 的键与 aria-describedby 的拼接。 */
export type AuthFieldName = 'account' | 'password' | 'inviteCode';

/** 按字段归集的校验消息；无错误的字段不出现该键。 */
export type FieldErrors = Partial<Record<AuthFieldName, string>>;

/** 字段级文案（页面设计的「请填写账号名」类内联错误）。 */
export const FIELD_MESSAGES: Readonly<Record<'account' | 'password' | 'inviteCode' | 'passwordRule', string>> = {
  account: '请填写账号名',
  password: '请填写密码',
  inviteCode: '请填写邀请码',
  passwordRule: '密码至少 8 位，且同时包含字母与数字',
};

/**
 * 密码规则与身份服务的默认校验器同形：长度 ≥8 且 <100、同时含字母与数字。
 *
 * 为什么前端也校验一遍：规则由服务端拥有（认证与账号第 4 节采用官方默认校验器），
 * 前端这一份只为在提交前给出即时反馈；判定权仍在服务端——这里放宽或收紧都不会
 * 让不合规的密码通过建号。
 */
function checkPassword(password: string): string | undefined {
  if (password === '') return FIELD_MESSAGES.password;
  const longEnough = password.length >= 8 && password.length < 100;
  const hasLetter = /[A-Za-z]/.test(password);
  const hasDigit = /[0-9]/.test(password);
  if (!longEnough || !hasLetter || !hasDigit) return FIELD_MESSAGES.passwordRule;
  return undefined;
}

/**
 * 校验登录表单。
 *
 * 前置: values 的两个字段都是字符串（表单取值保证）
 * 后置: 返回按字段归集的错误；全部合法时返回空对象
 * 异常: 无
 *
 * 刻意不校验账号名格式：一期账号名由运营发放，形态（是否含 `@`）不是前端该收紧的语义，
 * 收紧会把可用的账号名挡在门外（认证与账号第 3 节：账号名登录，不要求邮箱）。
 */
export function validateLoginForm(values: LoginFormValues): FieldErrors {
  const errors: FieldErrors = {};
  if (values.account.trim() === '') errors.account = FIELD_MESSAGES.account;
  const passwordError = checkPassword(values.password);
  if (passwordError !== undefined) errors.password = passwordError;
  return errors;
}

/**
 * 校验注册表单：登录字段 + 邀请码。
 *
 * 前置: values 的三个字段都是字符串
 * 后置: 返回按字段归集的错误；全部合法时返回空对象
 * 异常: 无
 *
 * 邀请码只校验非空：形状与存在性判定全在服务端（认证与账号第 4 节），
 * 前端提前判定形状会把「码无效」与「码写错」变成两条可区分的路径。
 */
export function validateRegisterForm(values: RegisterFormValues): FieldErrors {
  const errors: FieldErrors = validateLoginForm(values);
  if (values.inviteCode.trim() === '') errors.inviteCode = FIELD_MESSAGES.inviteCode;
  return errors;
}

/** 是否存在任一字段错误；空对象的判定集中一处，避免调用方各写各的。 */
export function hasFieldErrors(errors: FieldErrors): boolean {
  return Object.keys(errors).length > 0;
}

/**
 * 表单校验失败；携带字段级消息供 viewModel 落到字段上。
 *
 * 它让用例的拒绝路径显式（CORE-07）：调用方无法忽略字段错误继续提交。
 */
export class ValidationError extends Error {
  constructor(readonly fieldErrors: FieldErrors) {
    super('表单校验未通过');
    this.name = 'ValidationError';
  }
}
