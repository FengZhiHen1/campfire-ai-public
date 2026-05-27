/**
 * PROF-07 档案 API 服务层
 *
 * 封装所有档案相关 HTTP 调用，基于 AUTH-06 httpClient。
 * 职责：请求/响应映射、业务错误转换。
 * 禁止：裸调 Taro.request()、fetch()。
 */

import { httpClient } from '../../shared/services/httpClient';
import type { IRequestResponse } from '../../shared/services/httpClient';
import type {
  ProfileListItem,
  ProfileResponse,
  ProfileCreate,
  ProfileUpdate,
} from '../types';

// ============================================================================
// 内部工具
// ============================================================================

function pickData<T>(res: IRequestResponse<T>): T {
  return res.data;
}

// ============================================================================
// API 方法
// ============================================================================

/** GET /api/v1/profiles — 获取档案列表 */
export async function listProfiles(): Promise<ProfileListItem[]> {
  const res = await httpClient.request<ProfileListItem[]>({
    url: '/api/v1/profiles',
    method: 'GET',
  });
  return pickData(res);
}

/** GET /api/v1/profiles/{profileId} — 获取档案详情 */
export async function getProfile(profileId: string): Promise<ProfileResponse> {
  const res = await httpClient.request<ProfileResponse>({
    url: `/api/v1/profiles/${profileId}`,
    method: 'GET',
  });
  return pickData(res);
}

/** POST /api/v1/profiles — 创建档案 */
export async function createProfile(data: ProfileCreate): Promise<ProfileResponse> {
  const res = await httpClient.request<ProfileResponse>({
    url: '/api/v1/profiles',
    method: 'POST',
    data,
    header: { 'Content-Type': 'application/json' },
  });
  return pickData(res);
}

/** PUT /api/v1/profiles/{profileId} — 更新档案（Merge Patch） */
export async function updateProfile(
  profileId: string,
  data: Partial<ProfileUpdate>,
): Promise<ProfileResponse> {
  const res = await httpClient.request<ProfileResponse>({
    url: `/api/v1/profiles/${profileId}`,
    method: 'PUT',
    data,
    header: { 'Content-Type': 'application/json' },
  });
  return pickData(res);
}

/** DELETE /api/v1/profiles/{profileId} — 删除档案 */
export async function deleteProfile(profileId: string): Promise<void> {
  await httpClient.request<void>({
    url: `/api/v1/profiles/${profileId}`,
    method: 'DELETE',
  });
}

/** PUT /api/v1/profiles/{profileId}/default — 设为默认档案 */
export async function setDefaultProfile(profileId: string): Promise<void> {
  await httpClient.request<void>({
    url: `/api/v1/profiles/${profileId}/default`,
    method: 'PUT',
  });
}

/**
 * POST /api/v1/profiles/{profileId}/invalidate-cache — 通知缓存失效。
 * Fire-and-forget：调用方应 try/catch，失败不阻断主流程。
 * PROF-02 未就绪时 404 为预期行为。
 */
export async function invalidateCache(
  profileId: string,
  changedFields: string[],
): Promise<void> {
  await httpClient.request<void>({
    url: `/api/v1/profiles/${profileId}/invalidate-cache`,
    method: 'POST',
    data: { profileId, changedFields },
    header: { 'Content-Type': 'application/json' },
  });
}
