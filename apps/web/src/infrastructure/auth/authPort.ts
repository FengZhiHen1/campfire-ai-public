/**
 * 模块: infrastructure/auth/authPort
 * 职责: accounts 认证端口（AuthPort）的 SDK 实现——登录、注册与会话查证/登出
 * 数据来源:
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 4 节（注册凭邀请码）、第 5 节（SDK 职责）
 *   - docs/design/pages/登录与注册.md: MUST — 数据与文案节（失败文案的分类来源）
 * 边界:
 *   - 依赖: supertokens-web-js（唯一被允许接触身份服务的模块）
 *   - 被依赖: app 的装配与 features/accounts 的用例（经端口接口）
 * 禁止行为:
 *   - 禁止把 SDK 异常原文透出到界面（后端消息含英文与字段名，且是账号枚举渠道）
 *   - 禁止读取或存储 access/refresh 令牌（httpOnly cookie，前端不可读）
 */

import EmailPassword from 'supertokens-web-js/recipe/emailpassword';

import { supertokensSessionPort } from './session';
import type { AuthPort } from '../../features/accounts/application/ports';
import { AuthError } from '../../features/accounts/domain/authFailure';
import type { LoginFormValues, RegisterFormValues } from '../../features/accounts/domain/formValidation';
import type { AuthenticatedAccount } from '../../features/accounts/domain/session';

/**
 * 账号名在身份服务里的字段名。
 *
 * 为什么前端写 `email`：身份服务沿用 `email` 字段承载账号名，后端复写只读取它
 * （认证与账号第 3 节的 `TECH-08` 已知偏差；后端同名字段见
 * apps/api/src/campfire/modules/accounts/registration.py 的 EMAIL_FORM_FIELD）。
 * 前端不得把它展示成「邮箱」——界面上它始终是账号名。
 */
const ACCOUNT_FORM_FIELD = 'email';

/** 密码字段名（由 SDK 契约决定，与后端一致）。 */
const PASSWORD_FORM_FIELD = 'password';

/**
 * 邀请码字段名（前后端契约）。
 *
 * 必须与后端 `INVITE_CODE_FORM_FIELD` 逐字一致：不一致的表现是「注册总是被拒」
 * （后端把未声明的字段当形状错误，见 registration.py 的说明）。该常量在那里由测试钉住。
 */
const INVITE_CODE_FORM_FIELD = 'inviteCode';

/** 从 SDK 用户对象里取账号名；取不到返回 null（不编造空字符串）。 */
function readAccountName(user: { emails?: string[] } | undefined): string | null {
  const first = user?.emails?.[0];
  return typeof first === 'string' && first !== '' ? first : null;
}

/** 从 SDK 的 formFields 错误里取某个字段的错误文本。 */
function fieldError(formFields: { id: string; error: string }[], id: string): string | undefined {
  return formFields.find((field) => field.id === id)?.error;
}

/**
 * 判定抛出物是否为身份服务的 GENERAL_ERROR。
 *
 * 为什么用 SDK 自己的标记字段而不是 `instanceof STGeneralError`：实测在本包的
 * 打包/测试环境里 `supertokens-web-js/utils/error` 与 SDK 内部 `require` 到的是
 * 两份类对象，`instanceof` 恒为假——那会让所有 GENERAL_ERROR 静默落进
 * unexpected 分支（邀请码被拒的文案因此永远显示不出来）。标记字段由 SDK 写在实例上，
 * 跨模块身份依然成立。这个判定与 supertokens-website 的 `STGeneralError.isThisError`
 * 同义，但不需要把类引用带进来。
 */
function isGeneralError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    (error as { isSuperTokensGeneralError?: unknown }).isSuperTokensGeneralError === true
  );
}

/**
 * 把任意抛出物转成 AuthError。
 *
 * 这是数据边界（CORE-04）：SDK 的抛出物有四种形状——
 *   ① `STGeneralError`：后端以 HTTP 200 返回 `{status:"GENERAL_ERROR"}` 时 SDK 抛它；
 *   ② `Response`：SDK 的 querier 对 `status >= 300` 直接抛响应对象本身（实测
 *      supertokens-web-js 的 querier.js `if (result.status >= 300) { throw result; }`），
 *      因此 429 与 5xx 会以 Response 的形态到达这里；
 *   ③ 浏览器网络错误（TypeError）——后端未起或断网；
 *   ④ 其它未知抛出物。
 * 四者都必须收敛成显式分类，绝不能把原始对象往上抛（它会带着英文消息进到界面）。
 *
 * @param error 端口调用抛出的任意值。
 * @param context 本次调用的语义（注册与登录对同一 GENERAL_ERROR 的解释不同）。
 */
function toAuthError(error: unknown, context: 'login' | 'register'): AuthError {
  if (error instanceof AuthError) return error;

  if (isGeneralError(error)) {
    // 注册路径上 GENERAL_ERROR 只由我们的复写产生：邀请码被拒（后端把四种拒绝
    // 收敛成同一条消息，见 registration.py 的 _reject）。这里换上界面文案，
    // 不透出后端文本——文案以页面设计为准，且后端文本是枚举渠道。
    if (context === 'register') return new AuthError('invite-rejected');
    // 登录路径上 GENERAL_ERROR 没有可判定的具体原因（后端未复写 sign_in_post）。
    // 不猜成「密码错误」（会把服务端故障说成用户输错），给不可区分的通用拒绝。
    return new AuthError('unexpected');
  }

  if (error instanceof Response) {
    if (error.status === 429) {
      // 限流由 Nginx 层实现（认证与账号第 5 节），它以 429 表达；界面只说明
      // 「稍后再试」，不暴露阈值与计数逻辑（登录页状态覆盖表）。
      return new AuthError('rate-limited');
    }
    return new AuthError('service-unavailable');
  }

  if (error instanceof TypeError) {
    // fetch 在网络不可达时抛 TypeError；这不是「凭据错误」，不得混为一类。
    return new AuthError('service-unavailable');
  }

  return new AuthError('unexpected');
}

/**
 * AuthPort 的 SDK 实现。
 *
 * 为什么登录与注册把账号名回传给调用方：登录/注册响应里带账号名，而冷启动刷新
 * 页面时前端没有任何可读的账号名来源——凭据在 httpOnly cookie 里，且一期没有
 * 账号信息查询端点（认证与账号第 5 节）。与其在设置页显示空白，不如让每次登录/注册
 * 顺手把这一个字段带进会话 store。
 */
export const supertokensAuthPort: AuthPort = {
  async submitLogin(values: LoginFormValues): Promise<AuthenticatedAccount> {
    let result: Awaited<ReturnType<typeof EmailPassword.signIn>>;
    try {
      result = await EmailPassword.signIn({
        formFields: [
          { id: ACCOUNT_FORM_FIELD, value: values.account },
          { id: PASSWORD_FORM_FIELD, value: values.password },
        ],
      });
    } catch (error) {
      throw toAuthError(error, 'login');
    }

    switch (result.status) {
      case 'OK':
        return { accountName: readAccountName(result.user) };
      case 'WRONG_CREDENTIALS_ERROR':
        // 服务端不区分「账号不存在」与「密码错误」，前端也不得区分（认证与账号第 9 节）。
        throw new AuthError('invalid-credentials');
      case 'FIELD_ERROR':
        // 登录表单提交前已做非空与规则校验，此处只剩「账号名形状被服务端拒绝」这一支；
        // 按同一句不区分原因的话术拒绝，避免它变成账号枚举渠道。
        throw new AuthError('invalid-credentials');
      default:
        // SIGN_IN_NOT_ALLOWED：安全策略拒绝，没有面向使用者的原因可讲。
        throw new AuthError('unexpected');
    }
  },

  async submitRegister(values: RegisterFormValues): Promise<AuthenticatedAccount> {
    let result: Awaited<ReturnType<typeof EmailPassword.signUp>>;
    try {
      result = await EmailPassword.signUp({
        formFields: [
          { id: ACCOUNT_FORM_FIELD, value: values.account },
          { id: PASSWORD_FORM_FIELD, value: values.password },
          { id: INVITE_CODE_FORM_FIELD, value: values.inviteCode },
        ],
      });
    } catch (error) {
      throw toAuthError(error, 'register');
    }

    switch (result.status) {
      case 'OK':
        return { accountName: readAccountName(result.user) };
      case 'FIELD_ERROR': {
        // 按出错字段分派，不解析错误文本：文本是服务端措辞，任何改字都会让分支静默失效。
        // 三种 FIELD_ERROR 的来源（实测 supertokens_python 的 api/utils.py 与 api/signup.py）：
        //   - inviteCode：邀请码校验器返回错误（今天的校验器恒通过，属预留分支）；
        //   - password：官方默认密码校验器（长度/字母/数字）；
        //   - email：既可能是「账号名已被占用」（signup.py 用同一个形状返回
        //     EmailAlreadyExistsError），也可能是账号名未通过默认 email 校验器——
        //     两者在线上形状完全相同，前端无法区分，因此合并为一条不猜测原因的文案。
        if (fieldError(result.formFields, INVITE_CODE_FORM_FIELD) !== undefined) {
          throw new AuthError('invite-rejected');
        }
        if (fieldError(result.formFields, PASSWORD_FORM_FIELD) !== undefined) {
          throw new AuthError('weak-password');
        }
        throw new AuthError('account-unusable');
      }
      default:
        // SIGN_UP_NOT_ALLOWED：安全策略拒绝，同样没有面向使用者的原因。
        throw new AuthError('unexpected');
    }
  },

  doesSessionExist: () => supertokensSessionPort.doesSessionExist(),
  signOut: () => supertokensSessionPort.signOut(),
};
