/**
 * 模块: features/accounts/domain/session
 * 职责: 前端对「当前是否有有效会话」的领域建模——三态显式化，非法状态不可表示
 * 数据来源:
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 5、6 节（凭据与会话）
 * 边界:
 *   - 依赖: 无（不得 import 任何框架模块）
 *   - 被依赖: features/accounts 的 application、viewModel 与 app 的守卫
 * 禁止行为:
 *   - 禁止在此读取或存储凭据（会话凭据经 httpOnly cookie，前端不可读，项目结构第 9 节）
 */

/**
 * 会话存在性的三态。
 *
 * unknown 与 anonymous 不能合并：unknown 表示「尚未查证」——把未查证当成未登录会在
 * 冷启动时把已登录用户弹到登录页；把它当成已登录则会让守卫形同虚设。
 * 因此它是判别联合的第三个成员，而不是一个布尔值加一个 loading 标记。
 */
export type SessionStatus = 'unknown' | 'authenticated' | 'anonymous';

/** 会话快照；viewModel 与守卫消费的唯一形状。 */
export interface SessionSnapshot {
  status: SessionStatus;
}

/** 未查证态：应用启动到会话查证返回之间的唯一合法状态。 */
export function unknownSession(): SessionSnapshot {
  return { status: 'unknown' };
}
