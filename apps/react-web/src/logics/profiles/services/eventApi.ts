/**
 * PROF-03 事件 API 服务层
 *
 * 封装所有事件相关 HTTP 调用，基于 AUTH-06 httpClient。
 * 职责：请求/响应映射、业务错误转换。
 * 禁止：裸调 Taro.request()、fetch()。
 */

import type { PaginatedResponse } from '@campfire/ts-shared';

import { httpClient } from '../../shared/services/httpClient';
import type {
  EventListItem,
  EventResponse,
  EventCreate,
  EventUpdate,
} from '../types';
import { pickData } from './base';

// ============================================================================
// API 方法
// ============================================================================

/** GET /api/v1/profiles/{profileId}/events — 获取事件列表 */
export async function listEvents(
  profileId: string,
  page: number = 1,
  pageSize: number = 20,
): Promise<EventListItem[]> {
  const res = await httpClient.request<PaginatedResponse<EventListItem>>({
    url: `/api/v1/profiles/${profileId}/events`,
    method: 'GET',
    data: { page, page_size: pageSize },
  });
  return pickData(res).items;
}

/** GET /api/v1/profiles/{profileId}/events/{eventId} — 获取事件详情 */
export async function getEvent(profileId: string, eventId: string): Promise<EventResponse> {
  const res = await httpClient.request<EventResponse>({
    url: `/api/v1/profiles/${profileId}/events/${eventId}`,
    method: 'GET',
  });
  return pickData(res);
}

/** POST /api/v1/profiles/{profileId}/events — 创建事件 */
export async function createEvent(
  profileId: string,
  data: EventCreate,
): Promise<EventResponse> {
  const res = await httpClient.request<EventResponse>({
    url: `/api/v1/profiles/${profileId}/events`,
    method: 'POST',
    data,
    header: { 'Content-Type': 'application/json' },
  });
  return pickData(res);
}

/** PUT /api/v1/profiles/{profileId}/events/{eventId} — 更新事件（Merge Patch） */
export async function updateEvent(
  profileId: string,
  eventId: string,
  data: Partial<EventUpdate>,
): Promise<EventResponse> {
  const res = await httpClient.request<EventResponse>({
    url: `/api/v1/profiles/${profileId}/events/${eventId}`,
    method: 'PUT',
    data,
    header: { 'Content-Type': 'application/json' },
  });
  return pickData(res);
}

/** DELETE /api/v1/profiles/{profileId}/events/{eventId} — 删除事件 */
export async function deleteEvent(profileId: string, eventId: string): Promise<void> {
  await httpClient.request<void>({
    url: `/api/v1/profiles/${profileId}/events/${eventId}`,
    method: 'DELETE',
  });
}
