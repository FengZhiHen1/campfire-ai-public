/**
 * 模块: features/accounts/application/usecases
 * 职责: 会话用例——查证会话存在性并返回三态快照
 * 数据来源:
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 6 节（登录与会话）
 * 边界:
 *   - 依赖: features/accounts/domain、features/accounts/application/ports
 *   - 被依赖: features/accounts/viewModel 与 app 的守卫
 * 禁止行为:
 *   - 禁止在此持有 UI 状态（isLoading/error 归 viewModel 层）
 *   - 禁止把查证异常当作「未登录」（结果未知与已确认未登录是两回事）
 */

import { unknownSession, type SessionSnapshot } from '../domain/session';
import type { SessionPort } from './ports';

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
