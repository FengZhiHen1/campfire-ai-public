/**
 * CASE-03 案例审核工作流 — 前端 API Service。
 *
 * 仅保留旧 `/api/v1/cases` 前缀下的审核相关接口：
 * - POST /api/v1/cases/{case_id}/review
 * - GET /api/v1/cases/review-queue
 *
 * 案例的增删改查已迁移到 narrativeApi / cardApi，本文件不再提供。
 */

import { httpClient } from '../../shared/services/httpClient';
import { createRequestSignal, withSignal } from '../../shared/services/requestSignal';
import type {
  CaseReviewResponse,
  PaginatedResponse,
  ReviewQueueItem,
} from '@campfire/ts-shared';

const BASE_PATH: string = '/api/v1/cases';

/**
 * 提交审核裁决（approve / reject）。
 */
export async function reviewCase(
  caseId: string,
  decision: 'approved' | 'rejected',
  reviewComment?: string,
  signal?: AbortSignal,
): Promise<CaseReviewResponse> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  if (caseId === null || caseId === undefined) {
    return Promise.reject(new TypeError('caseId is required'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<CaseReviewResponse>(
      withSignal(
        {
          url: `${BASE_PATH}/${caseId}/review`,
          method: 'POST',
          data: { decision, review_comment: reviewComment },
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
 * 获取待审核队列（分页）。
 */
export async function fetchReviewQueue(
  page: number = 1,
  pageSize: number = 15,
  signal?: AbortSignal,
): Promise<PaginatedResponse<ReviewQueueItem>> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const queryString = `page=${page}&page_size=${pageSize}`;
    const res = await httpClient.request<PaginatedResponse<ReviewQueueItem>>(
      withSignal(
        {
          url: `${BASE_PATH}/review-queue?${queryString}`,
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
