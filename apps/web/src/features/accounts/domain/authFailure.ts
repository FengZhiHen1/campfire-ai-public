/**
 * 模块: features/accounts/domain/authFailure
 * 职责: 认证失败的分类与对外文案——判别联合的失败类型 + 逐字契约文案
 * 数据来源:
 *   - docs/design/pages/登录与注册.md: MUST — 数据与文案节（错误文案逐字）、状态覆盖表（限流形态）
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 9 节（失败语义）
 * 边界:
 *   - 依赖: 无（不得 import 任何框架模块）
 *   - 被依赖: application 的用例、infrastructure 的端口实现与 viewModel
 * 禁止行为:
 *   - 禁止把服务端原文透出给使用者（后端文案含英文与"email"字样，且是账号枚举渠道）
 *   - 禁止合并「凭据错误」与「账号不存在」两类失败（合并的是文案，不是分类：分类用于断言）
 */

/** 认证失败的分类；每个分类对应一条对外文案。 */
export type AuthFailureKind =
  | 'invalid-credentials'
  | 'invite-rejected'
  | 'account-unusable'
  | 'weak-password'
  | 'rate-limited'
  | 'service-unavailable'
  | 'unexpected';

/**
 * 对外文案表。
 *
 * 为什么文案集中在这里而不是由服务端下发：文案是产品契约的一部分，且后端拒绝消息里
 * 含字段名与英文句子——透出它既不符合本产品的语言，也把「服务端如何描述这次拒绝」
 * 变成了可被外部观察的枚举渠道（认证与账号第 9 节）。
 *
 * 前两条与限流一条是页面设计的逐字成稿；其余是设计文档未给定、但失败语义要求
 * 「明确拒绝并明确报错」时的最小中文表达（实现说明的未决问题节已单列供复核）。
 */
export const AUTH_FAILURE_MESSAGES: Readonly<Record<AuthFailureKind, string>> = {
  'invalid-credentials': '账号名或密码不正确',
  'invite-rejected': '邀请码无效或已被使用',
  // 刻意合并两类原因：身份服务对「账号名已被占用」与「账号名格式不被接受」返回的是
  // 同一个形状（都是 FIELD_ERROR 落在 email 字段，实测 supertokens_python 的
  // api/signup.py 与 api/utils.py），前端无法区分，也不应假装能区分。
  'account-unusable': '该账号名无法使用，请换一个',
  'weak-password': '密码至少 8 位，且同时包含字母与数字',
  'rate-limited': '尝试次数过多，请稍后再试',
  'service-unavailable': '服务暂时不可用，请稍后再试',
  unexpected: '操作没有成功，请稍后重试',
};

/**
 * 认证失败；携带分类供调用方分支，消息恒为上面的契约文案。
 *
 * 为什么用分类而不是让调用方比对消息文本：比对文案会在改字时静默失效
 * （测试仍绿而分支再也不会命中），分类是类型层面的判别联合（CORE-01）。
 */
export class AuthError extends Error {
  constructor(
    readonly kind: AuthFailureKind,
    message: string = AUTH_FAILURE_MESSAGES[kind],
  ) {
    super(message);
    this.name = 'AuthError';
  }
}
