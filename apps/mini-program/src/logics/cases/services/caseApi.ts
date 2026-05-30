/**
 * CASE-09 案例管理逻辑 — 前端 API Service。
 *
 * 封装 6 个 API 调用函数，使用 httpClient 统一发送请求。
 * 所有函数通过 httpClient.request 路由，追加 AbortController 超时逻辑（默认 15 秒）。
 * 接受外部 AbortSignal 以支持调用方（Hooks 层）的请求取消。
 *
 * API Service 层不操作 Store，Store 不调用 API——编排逻辑集中在 Hooks 层。
 *
 * 调用路径：
 *   views/ → hooks/ → caseApi (httpClient)
 *
 * 设计依据：
 * - 设计文档 §1.1 技术实现思路
 * - 设计文档 §1.4 API 调用通过 httpClient 路由
 * - 落地规范 §1.5 步骤组 B：API 调用
 */

import { httpClient } from '../../shared/services/httpClient';
import type {
  CaseCreateRequest,
  CaseListItem,
  CaseResponse,
  CaseReviewResponse,
  CaseUpdate,
  PaginatedResponse,
  PiiDetectionResult,
} from '@campfire/ts-shared';

const BASE_PATH: string = '/api/v1/cases';

/** 默认请求超时（毫秒） */
const DEFAULT_TIMEOUT_MS: number = 15000;

// ============================================================================
// 内部工具
// ============================================================================

/**
 * 创建合并了外部 AbortSignal 和内部超时信号的 AbortSignal。
 *
 * 超时信号（默认 15 秒）确保请求不会无限挂起。
 * 外部信号（可选）允许调用方提前取消请求（如翻页竞态、组件卸载）。
 *
 * @param externalSignal - 调用方传入的可选外部 AbortSignal
 * @param timeoutMs - 超时时间（毫秒），默认 15 秒
 * @returns 合并后的 signal 和 cleanup 函数
 */
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

/**
 * 将 AbortSignal 合并到 httpClient 请求选项中。
 * 使用类型断言确保 signal 字段能被传递到底层 Taro.request。
 */
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
// API 函数
// ============================================================================

/**
 * 创建案例草稿。
 *
 * @param request - 案例创建请求体
 * @param signal - 可选外部 AbortSignal，用于请求取消
 * @returns 201 Created，案例详情（status=draft）
 */
export async function createCase(
  request: CaseCreateRequest,
  signal?: AbortSignal,
): Promise<CaseResponse> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  if (request === null || request === undefined) {
    return Promise.reject(new TypeError('request is required'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<CaseResponse>(
      withSignal(
        {
          url: BASE_PATH,
          method: 'POST',
          data: request,
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
 * 更新案例字段（部分更新 + 乐观锁）。
 *
 * @param caseId - 案例唯一标识
 * @param update - 部分更新数据（含 updated_at 乐观锁）
 * @param signal - 可选外部 AbortSignal，用于请求取消
 * @returns 更新后的案例详情
 */
export async function updateCase(
  caseId: string,
  update: CaseUpdate,
  signal?: AbortSignal,
): Promise<CaseResponse> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  if (caseId === null || caseId === undefined) {
    return Promise.reject(new TypeError('caseId is required'));
  }
  if (update === null || update === undefined) {
    return Promise.reject(new TypeError('update is required'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<CaseResponse>(
      withSignal(
        {
          url: `${BASE_PATH}/${caseId}`,
          method: 'PUT',
          data: update,
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
 * 提交审核（draft -> pending_review）。
 *
 * @param caseId - 案例唯一标识
 * @param piiConfirmed - 用户是否确认已处理 PII 警告
 * @param signal - 可选外部 AbortSignal，用于请求取消
 * @returns 提交后的案例详情（status=pending_review）
 */
export async function submitCase(
  caseId: string,
  piiConfirmed: boolean = false,
  signal?: AbortSignal,
): Promise<CaseResponse> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  if (caseId === null || caseId === undefined) {
    return Promise.reject(new TypeError('caseId is required'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<CaseResponse>(
      withSignal(
        {
          url: `${BASE_PATH}/${caseId}/submit`,
          method: 'POST',
          data: { pii_confirmed: piiConfirmed },
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
 * 获取案例详情。
 *
 * @param caseId - 案例唯一标识
 * @param signal - 可选外部 AbortSignal，用于请求取消
 * @returns 案例完整详情
 */
export async function getCase(
  caseId: string,
  signal?: AbortSignal,
): Promise<CaseResponse> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  if (caseId === null || caseId === undefined) {
    return Promise.reject(new TypeError('caseId is required'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<CaseResponse>(
      withSignal(
        {
          url: `${BASE_PATH}/${caseId}`,
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
 * 查询案例列表。
 *
 * @param status - 可选状态筛选
 * @param page - 页码（从 1 开始）
 * @param pageSize - 每页条数
 * @param signal - 可选外部 AbortSignal，用于请求取消
 * @returns 分页列表响应
 */
export async function listCases(
  status?: string,
  behaviorType?: string,
  page: number = 1,
  pageSize: number = 15,
  scope?: string,
  signal?: AbortSignal,
): Promise<PaginatedResponse<CaseListItem>> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    // 过滤 undefined 值，防止序列化为 "undefined" 字符串发送到后端
    const queryData: Record<string, unknown> = { page, page_size: pageSize };
    if (status !== undefined) queryData.status = status;
    if (behaviorType !== undefined) queryData.behavior_type = behaviorType;
    if (scope !== undefined) queryData.scope = scope;

    const res = await httpClient.request<PaginatedResponse<CaseListItem>>(
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
 * 提交审核裁决（approve / reject）。
 *
 * @param caseId - 案例唯一标识
 * @param decision - 裁决结果
 * @param reviewComment - 审核意见（驳回时必填）
 * @param signal - 可选外部 AbortSignal
 * @returns 审核裁决响应
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
 * PII 检测（独立检测端点）。
 *
 * @param narrative - 待检测的叙事文本
 * @param signal - 可选外部 AbortSignal，用于请求取消
 * @returns 检测结果（has_pii + warnings 列表）
 */
export async function detectPii(
  narrative: string,
  signal?: AbortSignal,
): Promise<PiiDetectionResult> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  }
  if (narrative === null || narrative === undefined) {
    return Promise.reject(new TypeError('narrative is required'));
  }
  const { signal: requestSignal, cleanup } = createRequestSignal(signal);
  try {
    const res = await httpClient.request<PiiDetectionResult>(
      withSignal(
        {
          url: `${BASE_PATH}/pii-check`,
          method: 'POST',
          data: { narrative },
        },
        requestSignal,
      ),
    );
    return res.data;
  } finally {
    cleanup();
  }
}
