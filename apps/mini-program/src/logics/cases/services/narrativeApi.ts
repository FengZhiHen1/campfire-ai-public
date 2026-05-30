/**
 * CASE-09 案例管理逻辑 — 叙事 API Service。
 *
 * 封装叙事相关的 API 调用，通过 httpClient 统一发送请求。
 * 类型定义已归并至 ../types/index.ts。
 *
 * 调用路径：views/ → hooks/ → narrativeApi → httpClient
 */

import { httpClient } from '../../shared/services/httpClient';
import type { NarrativeListItem, NarrativeDetail, NarrativeListResponse } from '../types';

const BASE_PATH: string = '/api/v1/narratives';

/**
 * 查询叙事列表。
 *
 * @param scope - 查询范围（public / my）
 * @param page - 页码（从 1 开始）
 * @param pageSize - 每页条数
 * @returns 分页叙事列表
 */
export async function listNarratives(
  scope: string = 'public',
  page: number = 1,
  pageSize: number = 20,
): Promise<NarrativeListResponse> {
  const res = await httpClient.request<NarrativeListResponse>({
    url: BASE_PATH,
    method: 'GET',
    data: { scope, page, page_size: pageSize },
  });
  return res.data;
}

/**
 * 获取叙事详情。
 *
 * @param id - 叙事唯一标识
 * @returns 叙事完整详情
 */
export async function getNarrative(id: string): Promise<NarrativeDetail> {
  const res = await httpClient.request<NarrativeDetail>({
    url: `${BASE_PATH}/${id}`,
    method: 'GET',
  });
  return res.data;
}

/**
 * 创建叙事。
 *
 * @param data - 叙事创建请求体
 * @returns 新创建的叙事 ID
 */
export async function createNarrative(data: {
  title: string;
  narrative: string;
  source_type: string;
}): Promise<{ narrative_id: string }> {
  const res = await httpClient.request<{ narrative_id: string }>({
    url: BASE_PATH,
    method: 'POST',
    data,
    header: { 'Content-Type': 'application/json' },
  });
  return res.data;
}

/**
 * 触发 AI 提取干预卡片。
 *
 * @param narrativeId - 叙事唯一标识
 * @returns 提取出的卡片数量
 */
export async function extractNarrative(narrativeId: string): Promise<{ card_count: number }> {
  const res = await httpClient.request<{ card_count: number }>({
    url: `${BASE_PATH}/${narrativeId}/extract`,
    method: 'POST',
    header: { 'Content-Type': 'application/json' },
  });
  return res.data;
}
