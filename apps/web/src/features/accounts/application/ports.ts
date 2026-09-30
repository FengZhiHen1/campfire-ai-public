/**
 * 模块: features/accounts/application/ports
 * 职责: accounts 用例依赖的端口声明（凭据与会话维护由 infrastructure 实现）
 * 数据来源:
 *   - docs/项目结构设计.md: MUST — 第 9 节（application 不导入框架与 HTTP 库）
 * 边界:
 *   - 依赖: features/accounts/domain
 *   - 被依赖: features/accounts/application 的用例
 * 禁止行为:
 *   - 禁止在此导入 supertokens-web-js、fetch 或任何框架模块
 */

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
