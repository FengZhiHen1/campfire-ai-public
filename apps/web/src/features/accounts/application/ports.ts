/**
 * 模块: features/accounts/application/ports
 * 职责: accounts 用例依赖的端口声明（凭据与会话维护由 infrastructure 实现）
 * 数据来源:
 *   - docs/项目结构设计.md: MUST — 第 9 节（application 不导入框架与 HTTP 库）
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 4、5、6 节（注册复写、SDK 职责、登录与会话）
 * 边界:
 *   - 依赖: features/accounts/domain
 *   - 被依赖: features/accounts/application 的用例
 * 禁止行为:
 *   - 禁止在此导入 supertokens-web-js、fetch 或任何框架模块
 */

import type { LoginFormValues, RegisterFormValues } from '../domain/formValidation';
import type { AuthenticatedAccount } from '../domain/session';

/**
 * 会话端口：只回答「当前会话是否有效」与「登出」。
 *
 * 为什么端口只暴露这两件事：supertokens-web-js 的职责被限定为传输与会话维护
 * （认证与账号第 5 节），刷新重试与 anti-CSRF 头注入都在实现内部完成，
 * 用例层不需要、也不应该感知它们。
 */
export interface SessionPort {
  /** 查证当前是否存在有效会话。异常表示结果未知，不是「未登录」。 */
  doesSessionExist(): Promise<boolean>;
  /** 登出当前会话（撤销当前设备会话并清除 cookie）。 */
  signOut(): Promise<void>;
}

/**
 * 认证端口：会话端口 + 登录 + 注册（对外承诺给 T12 的形状）。
 *
 * 为什么继承 SessionPort 而不是各声明一份 signOut：登出只有一种语义
 * （撤销当前设备会话），两处各写一份会让「谁负责撤销」在实现侧分叉；
 * 继承后实现方只需满足一个对象，用例按各自需要收窄依赖。
 *
 * 为什么登录与注册也经端口而不是让用例直接调 SDK：用例层不得导入框架模块
 * （项目结构设计第 9 节），而 supertokens-web-js 与 SessionPort 同属传输层。
 */
export interface AuthPort extends SessionPort {
  /**
   * 登录。
   *
   * 前置: values 已通过表单校验（用例层负责，见 SubmitLoginUseCase）
   * 后置: 成功时服务端已签发会话 cookie，并返回本次可用的账号名
   * 异常: AuthError（分类见 domain/authFailure；不得把 SDK 原始异常透出到界面）
   *
   * 为什么返回账号名而不是 void：登录响应里带账号名，而冷启动刷新页面时前端
   * 没有任何可读的账号名来源（凭据在 httpOnly cookie，一期无账号信息查询端点）。
   * 不在这一刻顺手取回，设置页就只能显示空账号名。
   */
  submitLogin(values: LoginFormValues): Promise<AuthenticatedAccount>;
  /**
   * 注册（凭邀请码建号并直接进入登录态）。
   *
   * 前置: values 已通过表单校验，且 inviteCode 非空
   * 后置: 成功时账号已建、会话已签发，并返回本次可用的账号名；
   *      失败时不留半成品（服务端保证，见认证与账号第 4 节的补偿释放）
   * 异常: AuthError
   */
  submitRegister(values: RegisterFormValues): Promise<AuthenticatedAccount>;
}
