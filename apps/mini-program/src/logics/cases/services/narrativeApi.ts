/**
 * CASE-09 案例管理逻辑 — 叙事 API Service。
 *
 * 封装叙事相关的 API 调用，通过 httpClient 统一发送请求。
 * 所有函数支持超时（默认 15 秒）、AbortController 取消和空参数校验。
 *
 * 调用路径：views/ → hooks/ → narrativeApi → httpClient
 */

import { httpClient } from '../../shared/services/httpClient';
import { createRequestSignal, withSignal } from '../../shared/services/requestSignal';
import type { NarrativeListItem, NarrativeDetail } from '../types';
import type { PaginatedResponse } from '@campfire/ts-shared';

const BASE_PATH: string = '/api/v1/narratives';

// ============================================================================
// API 函数
// ============================================================================

/**
 * 查询叙事列表。
 *
 * @param scope - 查询范围（public / my）
 * @param page - 页码（从 1 开始）
 * @param pageSize - 每页条数
 * @param keyword - 可选搜索关键词
 * @param signal - 可选外部 AbortSignal
 * @returns 分页叙事列表
 */
export async function listNarratives(
  scope: string = 'public',
  page: number = 1,
  pageSize: number = 20,
  keyword?: string,
  signal?: AbortSignal,
): Promise<PaginatedResponse<NarrativeListItem>> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  if (scope === null || scope === undefined) {
    return Promise.reject(new TypeError('scope is required'));
  }
  const queryData: Record<string, unknown> = { scope, page, page_size: pageSize };
  if (keyword !== undefined) queryData.keyword = keyword;

  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<PaginatedResponse<NarrativeListItem>>(
      withSignal(
        {
          url: BASE_PATH,
          method: 'GET',
          data: queryData,
        },
        requestSignal,
      ),
    );
    return res.data;
  } finally {
    cleanup();
  }
}

/**
 * 获取叙事详情。
 *
 * @param id - 叙事唯一标识
 * @param signal - 可选外部 AbortSignal
 * @returns 叙事完整详情
 */
export async function getNarrative(
  id: string,
  signal?: AbortSignal,
): Promise<NarrativeDetail> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  if (id === null || id === undefined) {
    return Promise.reject(new TypeError('id is required'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<NarrativeDetail>(
      withSignal(
        {
          url: `${BASE_PATH}/${id}`,
          method: 'GET',
        },
        requestSignal,
      ),
    );
    return res.data;
  } finally {
    cleanup();
  }
}

/**
 * 创建叙事。
 *
 * @param data - 叙事创建请求体
 * @param signal - 可选外部 AbortSignal
 * @returns 新创建的叙事 ID
 */
export async function createNarrative(
  data: { title: string; narrative: string; source_type: string },
  signal?: AbortSignal,
): Promise<{ narrative_id: string }> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  if (data === null || data === undefined) {
    return Promise.reject(new TypeError('data is required'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<{ narrative_id: string }>(
      withSignal(
        {
          url: BASE_PATH,
          method: 'POST',
          data,
          header: { 'Content-Type': 'application/json' },
        },
        requestSignal,
      ),
    );
    return res.data;
  } finally {
    cleanup();
  }
}

/**
 * 触发 AI 提取干预卡片。
 *
 * @param narrativeId - 叙事唯一标识
 * @param signal - 可选外部 AbortSignal
 * @returns 提取出的卡片数量
 */
export async function extractNarrative(
  narrativeId: string,
  signal?: AbortSignal,
): Promise<{ card_count: number }> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  if (narrativeId === null || narrativeId === undefined) {
    return Promise.reject(new TypeError('narrativeId is required'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<{ card_count: number }>(
      withSignal(
        {
          url: `${BASE_PATH}/${narrativeId}/extract`,
          method: 'POST',
          header: { 'Content-Type': 'application/json' },
        },
        requestSignal,
      ),
    );
    return res.data;
  } finally {
    cleanup();
  }
}
