/**
 * 模块: react-web.application.auth.usecases
 * 职责: 认证用例编排——每个用例是一个纯函数，接收端口与参数，返回领域对象。
 *       用例不含状态（状态归 viewModel 层 store）。
 * 边界:
 *   - 依赖: application/ports、domain
 *   - 被依赖: viewModel/auth
 */

import type {
  InviteCodeCreateRequest,
  InviteCodeCreateResponse,
  InviteCodeListResponse,
  RegisterRequest,
  RegisterResponse,
  ReviewListResponse,
} from '@campfire/ts-shared/auth';
import type { AuthUser, TokenPair } from '@/domain/auth';
import type { IAuthRepository } from '../ports/IAuthRepository';

// === 会话用例 ===

export async function login(repo: IAuthRepository, phone: string, password: string): Promise<TokenPair> {
  return repo.login(phone, password);
}

export async function register(repo: IAuthRepository, request: RegisterRequest): Promise<RegisterResponse> {
  return repo.register(request);
}

export async function logout(repo: IAuthRepository, tokens: TokenPair): Promise<void> {
  // fail-open：后端失败也视为本地登出成功（机制 §九）
  try {
    await repo.logout(tokens.accessToken, tokens.refreshToken);
  } catch {
    // 静默降级
  }
}

export async function refreshSession(repo: IAuthRepository, refreshToken: string): Promise<TokenPair> {
  return repo.refresh(refreshToken);
}

export async function fetchMe(repo: IAuthRepository): Promise<AuthUser> {
  return repo.fetchMe();
}

export async function resubmitReview(repo: IAuthRepository, userId: string, realName: string | null): Promise<void> {
  return repo.resubmitReview(userId, { real_name: realName });
}

// === 邀请码管理用例（admin） ===

export async function createInviteCodes(
  repo: IAuthRepository,
  request: InviteCodeCreateRequest,
): Promise<InviteCodeCreateResponse> {
  return repo.createInviteCodes(request);
}

export async function fetchInviteCodes(repo: IAuthRepository): Promise<InviteCodeListResponse> {
  return repo.fetchInviteCodes();
}

export async function revokeInviteCode(repo: IAuthRepository, code: string): Promise<void> {
  return repo.revokeInviteCode(code);
}

// === 准入审核用例（admin） ===

export async function fetchReviews(repo: IAuthRepository): Promise<ReviewListResponse> {
  return repo.fetchReviews();
}

export async function approveReview(repo: IAuthRepository, userId: string): Promise<void> {
  return repo.approveReview(userId);
}

export async function rejectReview(repo: IAuthRepository, userId: string, reason: string): Promise<void> {
  return repo.rejectReview(userId, reason);
}
