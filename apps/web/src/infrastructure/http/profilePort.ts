/**
 * 模块: infrastructure/http/profilePort
 * 职责: 档案端口的 HTTP 实现——路径拼接、方法、载荷与查询参数
 * 数据来源:
 *   - docs/技术设计/面/profile/档案面HTTP契约.md: MUST — 第 2～5 节（路径与载荷）
 *   - docs/项目结构设计.md: MUST — 第 9 节（端口实现在 infrastructure，view 不得直接调 HTTP）
 * 边界:
 *   - 依赖: infrastructure/http/client、shared/types/profile
 *   - 被依赖: app/routes 装配后经 props 注入页面
 * 禁止行为:
 *   - 禁止在此判断业务分支（状态码分类归 features/profile/domain/failures）
 *   - 禁止把标识直接拼进路径而不转义（标识来自服务端与 URL，不能假定形状）
 */

import type {
  ConfirmProfileItemResponse,
  CorrectProfileItemRequest,
  CorrectProfileItemResponse,
  CreateProfileItemRequest,
  CreateProfileItemResponse,
  DeleteProfileItemResponse,
  ListProfileItemsResponse,
  ListSupportObjectsResponse,
  PatchSupportObjectRequest,
  ProfileSummaryResponse,
  RejectProfileItemResponse,
  SupportObject,
} from '../../shared/types/profile';
import type { ProfilePort } from '../../features/profile/application/ports';
import { request } from './client';

/** 把对象标识安全地拼进路径。 */
function objectPath(objectId: string): string {
  return `/profile/objects/${encodeURIComponent(objectId)}`;
}

/** 把条目标识安全地拼进路径。 */
function itemPath(itemId: string): string {
  return `/profile/items/${encodeURIComponent(itemId)}`;
}

/** 拼查询串：省略的参数不出现（不发送空 `cursor=`，那会被服务端当成非法游标）。 */
function query(entries: ReadonlyArray<[string, string | undefined]>): string {
  const parts = entries
    .filter((entry): entry is [string, string] => entry[1] !== undefined && entry[1] !== '')
    .map(([key, value]) => `${key}=${encodeURIComponent(value)}`);
  return parts.length === 0 ? '' : `?${parts.join('&')}`;
}

/** 档案端口的 HTTP 实现（档案面契约第 2～5 节）。 */
export const httpProfilePort: ProfilePort = {
  listObjects: () => request<ListSupportObjectsResponse>('/profile/objects'),

  createObject: (displayName: string) =>
    request<SupportObject>('/profile/objects', {
      method: 'POST',
      body: JSON.stringify({ display_name: displayName }),
    }),

  patchObject: (objectId: string, patch: PatchSupportObjectRequest) =>
    request<SupportObject>(objectPath(objectId), {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  getSummary: (objectId: string) => request<ProfileSummaryResponse>(`${objectPath(objectId)}/summary`),

  listItems: (objectId: string, options) =>
    request<ListProfileItemsResponse>(
      `${objectPath(objectId)}/items${query([
        ['include_candidates', options?.includeCandidates === true ? 'true' : undefined],
        ['cursor', options?.cursor],
      ])}`,
    ),

  confirmItem: (itemId: string) =>
    request<ConfirmProfileItemResponse>(`${itemPath(itemId)}/confirm`, { method: 'POST' }),

  correctItem: (itemId: string, body: CorrectProfileItemRequest) =>
    request<CorrectProfileItemResponse>(`${itemPath(itemId)}/correct`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  rejectItem: (itemId: string) => request<RejectProfileItemResponse>(`${itemPath(itemId)}/reject`, { method: 'POST' }),

  deleteItem: (itemId: string) => request<DeleteProfileItemResponse>(itemPath(itemId), { method: 'DELETE' }),

  addItem: (objectId: string, body: CreateProfileItemRequest) =>
    request<CreateProfileItemResponse>(`${objectPath(objectId)}/items`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
};
