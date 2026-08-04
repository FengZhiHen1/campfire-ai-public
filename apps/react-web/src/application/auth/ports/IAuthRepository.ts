/**
 * 模块: react-web.application.auth.ports
 * 职责: 认证应用层端口——IAuthRepository 接口（依赖倒置：application 定义，
 *       infrastructure 实现）。
 * 数据来源:
 *   - py-schemas (auth): MUST — 后端 API 契约（经 ts-shared 镜像）
 * 边界:
 *   - 依赖: domain（实体）、ts-shared（请求 DTO 类型）
 *   - 被依赖: application/usecases、infrastructure/repositories
 * 禁止行为:
 *   - 禁止在端口接口中泄露 HTTP 细节（URL/header 等归 infrastructure；
 *     access token 注入归 httpClient 唯一入口，端口签名不重复传递）
 */

import type {
  InviteCodeCreateRequest,
  InviteCodeCreateResponse,
  InviteCodeListResponse,
  RegisterRequest,
  RegisterResponse,
  ReviewListResponse,
  ReviewResubmitRequest,
} from '@campfire/ts-shared/auth';
import type { AuthUser, TokenPair } from '@/domain/auth';

/** 认证仓储端口 */
export interface IAuthRepository {
  /** 手机号 + 密码登录，签发 Token 对 */
  login(phone: string, password: string): Promise<TokenPair>;
  /** 邀请码注册（family/volunteer 即 active；teacher/expert 进入 pending_review） */
  register(request: RegisterRequest): Promise<RegisterResponse>;
  /** refresh token 轮换（单次使用；旧 token 复用触发全家族吊销） */
  refresh(refreshToken: string): Promise<TokenPair>;
  /** 登出（access 黑名单 + 家族吊销，fail-open） */
  logout(accessToken: string, refreshToken: string): Promise<void>;
  /** 获取当前用户信息 */
  fetchMe(): Promise<AuthUser>;
  /** 驳回后补交材料重提（本人，rejected → pending_review） */
  resubmitReview(userId: string, request: ReviewResubmitRequest): Promise<void>;

  /** 生成邀请码（admin） */
  createInviteCodes(request: InviteCodeCreateRequest): Promise<InviteCodeCreateResponse>;
  /** 邀请码列表（admin） */
  fetchInviteCodes(): Promise<InviteCodeListResponse>;
  /** 停用邀请码（admin） */
  revokeInviteCode(code: string): Promise<void>;

  /** 待审列表（admin） */
  fetchReviews(): Promise<ReviewListResponse>;
  /** 审核通过（admin） */
  approveReview(userId: string): Promise<void>;
  /** 审核驳回（admin，含面向用户的原因） */
  rejectReview(userId: string, reason: string): Promise<void>;
}
