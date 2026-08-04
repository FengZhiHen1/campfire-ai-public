/**
 * 模块: react-web.infrastructure.mappers.authMapper
 * 职责: 认证 DTO ↔ domain 实体映射（snake_case 后端契约 → camelCase 领域形态）。
 * 边界:
 *   - 依赖: ts-shared（DTO）、domain（实体）
 *   - 被依赖: infrastructure/repositories
 */

import type { MeResponse, TokenResponse } from '@campfire/ts-shared/auth';
import type { AuthUser, TokenPair } from '@/domain/auth';

export function mapMeResponseToUser(dto: MeResponse): AuthUser {
  return {
    userId: dto.user_id,
    phone: dto.phone,
    realName: dto.real_name,
    role: dto.role,
    status: dto.status,
    rejectReason: dto.reject_reason,
  };
}

export function mapTokenResponseToPair(dto: TokenResponse): TokenPair {
  return {
    accessToken: dto.access_token,
    refreshToken: dto.refresh_token,
  };
}
