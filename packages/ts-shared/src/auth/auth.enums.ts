/**
 * 模块: @campfire/ts-shared.auth.enums
 * 职责: 认证域前端枚举定义——六角色、账号状态、邀请码状态/渠道、凭证类型。
 *       枚举值与后端 py-schemas 严格一致（ADR-013 目标态）。
 * 数据来源:
 *   - py-schemas (auth / enums.auth_enums): MUST — 后端 Python 枚举
 *   - docs/技术设计/机制/认证与访问.md: MUST — 状态机与角色语义唯一事实源
 * 边界:
 *   - 依赖: 无
 *   - 被依赖: auth.types.ts、react-web（S6 五层重组后全站使用）
 * 禁止行为:
 *   - 禁止定义与后端枚举值不一致的字符串
 *   - 禁止引入数值层级（level）语义——RBAC 为显式角色→能力映射
 */

/** 用户角色——对应后端 UserRole 枚举（py_schemas.auth.UserRole），单角色互斥 */
export enum UserRole {
  FAMILY = 'family',
  VOLUNTEER = 'volunteer',
  TEACHER = 'teacher',
  EXPERT = 'expert',
  ADMIN = 'admin',
  MAINTAINER = 'maintainer',
}

/** 账号状态机——对应后端 AccountStatus 枚举 */
export enum AccountStatus {
  ACTIVE = 'active',
  PENDING_REVIEW = 'pending_review',
  REJECTED = 'rejected',
  DISABLED = 'disabled',
}

/** 邀请码状态——对应后端 InviteCodeStatus 枚举 */
export enum InviteCodeStatus {
  ACTIVE = 'active',
  REVOKED = 'revoked',
}

/** 邀请码渠道——对应后端 InviteChannel 枚举；demand 可注册家属/志愿者，supply 可注册老师/专家 */
export enum InviteChannel {
  DEMAND = 'demand',
  SUPPLY = 'supply',
}

/** 凭证渠道类型——对应后端 CredentialType 枚举（wechat 为预留） */
export enum CredentialType {
  PASSWORD = 'password',
  WECHAT = 'wechat',
}

/** 邀请码渠道 → 可注册角色约束映射（与后端 CHANNEL_ALLOWED_ROLES 一致） */
export const CHANNEL_ALLOWED_ROLES: Readonly<Record<InviteChannel, readonly UserRole[]>> = {
  [InviteChannel.DEMAND]: [UserRole.FAMILY, UserRole.VOLUNTEER],
  [InviteChannel.SUPPLY]: [UserRole.TEACHER, UserRole.EXPERT],
} as const;

/** 注册开放的角色集合（admin/maintainer 由管理员分配，不开放注册） */
export const REGISTRABLE_ROLES: readonly UserRole[] = [
  UserRole.FAMILY,
  UserRole.VOLUNTEER,
  UserRole.TEACHER,
  UserRole.EXPERT,
] as const;

/** 注册后进入准入审核的角色集合 */
export const REVIEW_REQUIRED_ROLES: readonly UserRole[] = [UserRole.TEACHER, UserRole.EXPERT] as const;
