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
 * @param signal - 可选外部 AbortSignal
 * @returns 分页叙事列表
 */
export async function listNarratives(
  scope: string = 'public',
  page: number = 1,
  pageSize: number = 15,
  signal?: AbortSignal,
): Promise<PaginatedResponse<NarrativeListItem>> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<PaginatedResponse<NarrativeListItem>>(
      withSignal(
        {
          url: `${BASE_PATH}?scope=${scope}&page=${page}&page_size=${pageSize}`,
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
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<{ narrative_id: string }>(
      withSignal(
        {
          url: BASE_PATH,
          method: 'POST',
          header: { 'Content-Type': 'application/json' },
          data: JSON.stringify(data),
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
 * 更新叙事。
 */
export async function updateNarrative(
  narrativeId: string,
  data: { title?: string; narrative?: string },
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<Record<string, unknown>>(
      withSignal(
        {
          url: `${BASE_PATH}/${narrativeId}`,
          method: 'PUT',
          header: { 'Content-Type': 'application/json' },
          data: JSON.stringify(data),
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
 * 提交叙事审核。
 */
export async function submitNarrative(
  narrativeId: string,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<Record<string, unknown>>(
      withSignal(
        {
          url: `${BASE_PATH}/${narrativeId}/submit`,
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

/**
 * 调用 LLM 提取 L2 卡片。
 */
export async function extractNarrative(
  narrativeId: string,
  signal?: AbortSignal,
): Promise<{ status: string; card_count?: number; cards?: unknown[] }> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<{ status: string; card_count?: number; cards?: unknown[] }>(
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

/**
 * 获取 L2 卡片详情。
 */
export async function getCard(
  cardId: string,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<Record<string, unknown>>(
      withSignal(
        { url: `/api/v1/cards/${cardId}`, method: 'GET' },
        requestSignal,
      ),
    );
    return res.data;
  } finally {
    cleanup();
  }
}
