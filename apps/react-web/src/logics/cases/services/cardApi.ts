/**
 * CASE-09 案例管理逻辑 — 卡片 API Service。
 *
 * 封装卡片 CRUD 相关的 API 调用，通过 httpClient 统一发送请求。
 * 所有函数支持超时（默认 15 秒）、AbortController 取消和空参数校验。
 *
 * 调用路径：views/ → hooks/ → cardApi → httpClient
 */

import { httpClient } from '../../shared/services/httpClient';
import { createRequestSignal, withSignal } from '../../shared/services/requestSignal';

const BASE_PATH: string = '/api/v1/cards';

// ============================================================================
// 类型定义
// ============================================================================

export interface CardData {
  card_id: string;
  narrative_id: string;
  title: string;
  scenario: string;
  behavior_type: string;
  age_range: number[];
  severity: string;
  scene: string;
  ebp_labels: string[];
  family_category: string;
  immediate_action: string;
  comforting_phrase: string;
  observation_metrics: string;
  medical_criteria: string;
  evidence_level: string;
  caution_notes: string;
  contraindications: string;
  excluded_population?: string;
  is_template: boolean;
  review_status: string;
  review_comment?: string | null;
  inferred_fields?: Record<string, string>;
  attachment_refs?: unknown[] | null;
  is_owner?: boolean | null;
  created_at: string;
  updated_at: string;
}

export interface CardUpdateData {
  title?: string;
  scenario?: string;
  behavior_type?: string;
  age_range?: number[];
  severity?: string;
  scene?: string;
  ebp_labels?: string[];
  family_category?: string;
  immediate_action?: string;
  comforting_phrase?: string;
  observation_metrics?: string;
  medical_criteria?: string;
  evidence_level?: string;
  contraindications?: string;
  is_template?: boolean;
  /** 乐观锁时间戳，必填（对齐后端 CardUpdate.updated_at） */
  updated_at?: string;
}

// ============================================================================
// API 函数
// ============================================================================

/** 获取卡片详情。 */
export async function getCard(
  cardId: string,
  signal?: AbortSignal,
): Promise<CardData> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  if (cardId === null || cardId === undefined) {
    return Promise.reject(new TypeError('cardId is required'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<CardData>(
      withSignal(
        {
          url: `${BASE_PATH}/${cardId}`,
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

/** 更新卡片。 */
export async function updateCard(
  cardId: string,
  data: CardUpdateData,
  signal?: AbortSignal,
): Promise<CardData> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  if (cardId === null || cardId === undefined) {
    return Promise.reject(new TypeError('cardId is required'));
  }
  if (data === null || data === undefined) {
    return Promise.reject(new TypeError('data is required'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<CardData>(
      withSignal(
        {
          url: `${BASE_PATH}/${cardId}`,
          method: 'PUT',
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

/** 提交卡片审核。 */
export async function submitCard(
  cardId: string,
  signal?: AbortSignal,
): Promise<void> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  if (cardId === null || cardId === undefined) {
    return Promise.reject(new TypeError('cardId is required'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    await httpClient.request(
      withSignal(
        {
          url: `${BASE_PATH}/${cardId}/submit`,
          method: 'POST',
          header: { 'Content-Type': 'application/json' },
        },
        requestSignal,
      ),
    );
  } finally {
    cleanup();
  }
}
