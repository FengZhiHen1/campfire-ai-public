/**
 * 模块: react-web.domain.auth
 * 职责: 认证领域层——实体、枚举与领域规则（纯 TS，零框架依赖）。
 * 数据来源:
 *   - @campfire/ts-shared/auth: MUST — 前后端共享契约（枚举值以后端 py-schemas 为准）
 *   - docs/技术设计/机制/认证与访问.md: MUST — 状态机与角色语义唯一事实源
 * 边界:
 *   - 依赖: ts-shared（纯类型）
 *   - 被依赖: application / viewModel / infrastructure（Mapper）
 * 禁止行为:
 *   - 禁止引入 React / zustand / fetch 等框架或 IO 依赖
 */

import { AccountStatus, UserRole } from '@campfire/ts-shared/auth';

export { AccountStatus, UserRole };
export { InviteChannel, InviteCodeStatus } from '@campfire/ts-shared/auth';

/** 已认证用户实体（领域形态） */
export interface AuthUser {
  readonly userId: string;
  readonly phone: string;
  readonly realName: string | null;
  readonly role: UserRole;
  readonly status: AccountStatus;
  readonly rejectReason: string | null;
}

/** Token 对（领域形态） */
export interface TokenPair {
  readonly accessToken: string;
  readonly refreshToken: string;
}

/**
 * 账号是否需要进入准入状态页（pending_review/rejected 无任何业务能力，
 * 仅见状态页——认证与访问 §3.2）。
 */
export function needsReviewStatusPage(user: AuthUser): boolean {
  return user.status === AccountStatus.PENDING_REVIEW || user.status === AccountStatus.REJECTED;
}

/** 角色 → 默认首页路径（角色收敛导航，ADR-012/013） */
export function homePathForRole(role: UserRole): string {
  switch (role) {
    case UserRole.FAMILY:
    case UserRole.VOLUNTEER:
      return '/consult';
    case UserRole.TEACHER:
    case UserRole.EXPERT:
      return '/cases';
    case UserRole.ADMIN:
      return '/admin/invite-codes';
    case UserRole.MAINTAINER:
      return '/no-access';
  }
}
