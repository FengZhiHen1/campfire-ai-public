/**
 * 模块: features/accounts/application/usecases
 * 职责: 会话查证、登录、注册与会话用例——编排端口调用并把拒绝路径显式化
 * 数据来源:
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 4 节（注册凭邀请码）、第 6 节（登录与会话）
 *   - docs/design/pages/登录与注册.md: MUST — 状态覆盖表（submitting/server-error）
 * 边界:
 *   - 依赖: features/accounts/domain、features/accounts/application/ports
 *   - 被依赖: features/accounts/viewModel 与 app 的守卫
 * 禁止行为:
 *   - 禁止在此持有 UI 状态（isLoading/error 归 viewModel 层）
 *   - 禁止把查证异常当作「未登录」（结果未知与已确认未登录是两回事）
 *   - 禁止在提交用例里吞掉 AuthError（拒绝原因必须到达 viewModel 才能呈现）
 */

import { AuthError } from '../domain/authFailure';
import type { LoginFormValues, RegisterFormValues } from '../domain/formValidation';
import { ValidationError, hasFieldErrors, validateLoginForm, validateRegisterForm } from '../domain/formValidation';
import { unknownSession, type AuthenticatedAccount, type SessionSnapshot } from '../domain/session';
import type { AuthPort, SessionPort } from './ports';

/**
 * 查证当前会话状态。
 *
 * 为什么用无状态类而不是函数：它编排端口调用并承载前置/后置语义（FE-04），
 * 与后续会加入的注册、登出用例保持同一形状；实例不持有任何状态，每次调用新建即可。
 */
export class ResolveSessionUseCase {
  constructor(private readonly session: SessionPort) {}

  /**
   * 执行会话查证。
   *
   * 前置: 无（应用启动即可调用；未初始化时实现方须自行处理）
   * 后置: 返回 authenticated 或 anonymous 两个确定态之一
   * 异常: 不抛出——查证失败（网络、SDK 未初始化）按 unknown 返回，
   *       由调用方决定重试或维持未决，不得把失败静默记为匿名
   */
  async execute(): Promise<SessionSnapshot> {
    try {
      const exists = await this.session.doesSessionExist();
      return { status: exists ? 'authenticated' : 'anonymous' };
    } catch {
      // 结果未知是合法状态而非错误：网络中断或 SDK 未就绪时，把用户判为未登录
      // 会造成冷启动误弹登录页；判为已登录则让守卫失效。保持 unknown 由调用方处置。
      return unknownSession();
    }
  }
}

/**
 * 登录用例。
 *
 * 为什么校验放用例而不是 viewModel：校验规则是领域规则（域名与密码形状），
 * 而 viewModel 只负责「什么时候展示错误」；同一份规则还必须被注册用例复用，
 * 放在 viewModel 会变成两份（FE-04：内部校验不可绕过）。
 */
export class SubmitLoginUseCase {
  constructor(private readonly auth: AuthPort) {}

  /**
   * 执行登录。
   *
   * 前置: 无（未填的字段会走校验拒绝）
   * 后置: 返回即表示服务端已签发会话；返回值为本次可用的账号名
   * 异常: ValidationError（字段级错误，未发起请求）；AuthError（服务端拒绝）
   */
  async execute(values: LoginFormValues): Promise<AuthenticatedAccount> {
    const errors = validateLoginForm(values);
    if (hasFieldErrors(errors)) throw new ValidationError(errors);
    return this.auth.submitLogin(values);
  }
}

/**
 * 注册用例（凭邀请码建号）。
 *
 * 与登录用例分开而不是合成一个带 mode 参数的用例：两条路径的字段集合与失败语义
 * 不同（注册多一个邀请码拒绝分支），合并后每个调用点都要带着一个恒真的分支参数。
 */
export class SubmitRegisterUseCase {
  constructor(private readonly auth: AuthPort) {}

  /**
   * 执行注册。
   *
   * 前置: 无（未填的字段会走校验拒绝）
   * 后置: 返回即表示账号已建且会话已签发；返回值为本次可用的账号名
   * 异常: ValidationError（字段级错误，未发起请求）；AuthError（邀请码拒绝、账号占用等）
   */
  async execute(values: RegisterFormValues): Promise<AuthenticatedAccount> {
    const errors = validateRegisterForm(values);
    if (hasFieldErrors(errors)) throw new ValidationError(errors);
    return this.auth.submitRegister(values);
  }
}

/**
 * 登出用例。
 *
 * 为什么登出失败要抛而不是静默：登出是安全语义的操作（会话撤销），
 * 把它记成成功会让使用者以为已登出而实际仍持有可用会话；设置页因此要求
 * 「登出失败 → sheet 内联错误 + 重试」（设置页状态覆盖表）。
 */
export class LogoutUseCase {
  constructor(private readonly auth: AuthPort) {}

  /**
   * 执行登出。
   *
   * 前置: 无
   * 后置: 成功返回表示服务端已撤销当前会话并清除 cookie
   * 异常: AuthError（服务不可达或撤销失败）；结果未知不得当作已登出
   */
  async execute(): Promise<void> {
    try {
      await this.auth.signOut();
    } catch (error) {
      if (error instanceof AuthError) throw error;
      throw new AuthError('service-unavailable');
    }
  }
}
