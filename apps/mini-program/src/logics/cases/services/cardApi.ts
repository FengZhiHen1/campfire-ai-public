/**
 * CASE-09 案例管理逻辑 — 卡片 API Service。
 *
 * 封装卡片 CRUD 相关的 API 调用，通过 httpClient 统一发送请求。
 * 所有函数支持超时（默认 15 秒）、AbortController 取消和空参数校验。
 *
 * 调用路径：views/ → hooks/ → cardApi → httpClient
 */

import { httpClient } from '../../shared/services/httpClient';

const BASE_PATH: string = '/api/v1/cards';

/** 默认请求超时（毫秒） */
const DEFAULT_TIMEOUT_MS: number = 15000;

// ============================================================================
// 内部工具
// ============================================================================

function createRequestSignal(
  externalSignal?: AbortSignal,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): { signal: AbortSignal; cleanup: () => void } {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(new Error('Request timeout')), timeoutMs);

  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort(externalSignal.reason);
      clearTimeout(timeoutId);
    } else {
      externalSignal.addEventListener(
        'abort',
        () => {
          controller.abort(externalSignal.reason);
          clearTimeout(timeoutId);
        },
        { once: true },
      );
    }
  }

  return {
    signal: controller.signal,
    cleanup: () => clearTimeout(timeoutId),
  };
}

function withSignal<T extends Record<string, unknown>>(
  options: T,
  signal?: AbortSignal,
): T & { signal?: AbortSignal } {
  if (signal) {
    return { ...options, signal };
  }
  return options;
}

// ============================================================================
// 类型定义
// ============================================================================

export interface CardData {
  card_id: string;
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
  is_template: boolean;
  inferred_fields?: Record<string, string>;
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
}

// ============================================================================
// API 函数
// ============================================================================

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
