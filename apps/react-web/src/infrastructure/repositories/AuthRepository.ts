/**
 * 模块: react-web.infrastructure.repositories.AuthRepository
 * 职责: IAuthRepository 端口的 HTTP 实现——对接 api-server /api/v1/auth 端点。
 * 边界:
 *   - 依赖: application/ports（实现）、httpClient、authMapper
 *   - 被依赖: viewModel（经依赖注入组装）
 */

import type {
  InviteCodeCreateRequest,
  InviteCodeCreateResponse,
  InviteCodeListResponse,
  LoginRequest,
  MeResponse,
  RegisterRequest,
  RegisterResponse,
  ReviewListResponse,
  ReviewResubmitRequest,
  TokenResponse,
} from '@campfire/ts-shared/auth';
import type { AuthUser, TokenPair } from '@/domain/auth';
import type { IAuthRepository } from '@/application/auth/ports/IAuthRepository';
import { httpClient } from '../http/httpClient';
import { mapMeResponseToUser, mapTokenResponseToPair } from '../mappers/authMapper';

export class AuthRepository implements IAuthRepository {
  async login(phone: string, password: string): Promise<TokenPair> {
    const body: LoginRequest = { phone, password };
    const dto = await httpClient.request<TokenResponse>('/api/v1/auth/login', {
      method: 'POST',
      data: body,
      skipAuth: true,
    });
    return mapTokenResponseToPair(dto);
  }

  async register(request: RegisterRequest): Promise<RegisterResponse> {
    return httpClient.request<RegisterResponse>('/api/v1/auth/register', {
      method: 'POST',
      data: request,
      skipAuth: true,
    });
  }

  async refresh(refreshToken: string): Promise<TokenPair> {
    const dto = await httpClient.request<TokenResponse>('/api/v1/auth/refresh', {
      method: 'POST',
      data: { refresh_token: refreshToken },
      skipAuth: true,
      skipRefresh: true,
    });
    return mapTokenResponseToPair(dto);
  }

  async logout(accessToken: string, refreshToken: string): Promise<void> {
    await httpClient.request('/api/v1/auth/logout', {
      method: 'POST',
      data: { refresh_token: refreshToken },
      skipAuth: true,
      skipRefresh: true,
    });
  }

  async fetchMe(): Promise<AuthUser> {
    const dto = await httpClient.request<MeResponse>('/api/v1/auth/me');
    return mapMeResponseToUser(dto);
  }

  async resubmitReview(userId: string, request: ReviewResubmitRequest): Promise<void> {
    await httpClient.request(`/api/v1/auth/reviews/${userId}/resubmit`, {
      method: 'POST',
      data: request,
    });
  }

  async createInviteCodes(request: InviteCodeCreateRequest): Promise<InviteCodeCreateResponse> {
    return httpClient.request<InviteCodeCreateResponse>('/api/v1/auth/invite-codes', {
      method: 'POST',
      data: request,
    });
  }

  async fetchInviteCodes(): Promise<InviteCodeListResponse> {
    return httpClient.request<InviteCodeListResponse>('/api/v1/auth/invite-codes');
  }

  async revokeInviteCode(code: string): Promise<void> {
    await httpClient.request(`/api/v1/auth/invite-codes/${code}/revoke`, { method: 'POST' });
  }

  async fetchReviews(): Promise<ReviewListResponse> {
    return httpClient.request<ReviewListResponse>('/api/v1/auth/reviews');
  }

  async approveReview(userId: string): Promise<void> {
    await httpClient.request(`/api/v1/auth/reviews/${userId}/approve`, { method: 'POST' });
  }

  async rejectReview(userId: string, reason: string): Promise<void> {
    await httpClient.request(`/api/v1/auth/reviews/${userId}/reject`, {
      method: 'POST',
      data: { reason },
    });
  }
}

/** 仓储单例（无状态，可全局共享） */
export const authRepository = new AuthRepository();
