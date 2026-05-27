/**
 * CASE-01 案例录入管理 — 前端 API Service。
 *
 * 封装 6 个 API 调用函数，使用 httpClient 统一发送请求。
 * 所有函数返回类型与 @campfire/ts-shared 中的接口定义对齐。
 *
 * 调用路径：
 *   views/ (Props) → caseFormStore (Zustand) → caseApiService (httpClient)
 */

import Taro from '@tarojs/taro';
import { httpClient } from '../../shared/services/httpClient';
import type {
  CaseCreateRequest,
  CaseListItem,
  CaseResponse,
  CaseUpdate,
  PaginatedResponse,
  PiiDetectionResult,
} from '@campfire/ts-shared';

const BASE_PATH: string = '/api/v1/cases';

/**
 * 创建案例草稿。
 *
 * @param request - 案例创建请求体
 * @returns 201 Created，案例详情（status=draft）
 */
export async function createCase(request: CaseCreateRequest): Promise<CaseResponse> {
  const res = await httpClient.request<CaseResponse>({
    url: BASE_PATH,
    method: 'POST',
    data: request,
  });
  return res.data;
}

/**
 * 更新案例字段（部分更新 + 乐观锁）。
 *
 * @param caseId - 案例唯一标识
 * @param update - 部分更新数据（含 updated_at 乐观锁）
 * @returns 更新后的案例详情
 */
export async function updateCase(
  caseId: string,
  update: CaseUpdate,
): Promise<CaseResponse> {
  const res = await httpClient.request<CaseResponse>({
    url: `${BASE_PATH}/${caseId}`,
    method: 'PUT',
    data: update,
  });
  return res.data;
}

/**
 * 提交审核（draft -> pending_review）。
 *
 * @param caseId - 案例唯一标识
 * @param piiConfirmed - 用户是否确认已处理 PII 警告
 * @returns 提交后的案例详情（status=pending_review）
 */
export async function submitCase(
  caseId: string,
  piiConfirmed: boolean = false,
): Promise<CaseResponse> {
  const res = await httpClient.request<CaseResponse>({
    url: `${BASE_PATH}/${caseId}/submit`,
    method: 'POST',
    data: { pii_confirmed: piiConfirmed },
  });
  return res.data;
}

/**
 * 获取案例详情。
 *
 * @param caseId - 案例唯一标识
 * @returns 案例完整详情
 */
export async function getCase(caseId: string): Promise<CaseResponse> {
  const res = await httpClient.request<CaseResponse>({
    url: `${BASE_PATH}/${caseId}`,
    method: 'GET',
  });
  return res.data;
}

/**
 * 查询案例列表。
 *
 * @param status - 可选状态筛选
 * @param page - 页码（从 1 开始）
 * @param pageSize - 每页条数
 * @returns 分页列表响应
 */
export async function listCases(
  status?: string,
  page: number = 1,
  pageSize: number = 15,
): Promise<PaginatedResponse<CaseListItem>> {
  const res = await httpClient.request<PaginatedResponse<CaseListItem>>({
    url: BASE_PATH,
    method: 'GET',
    data: {
      status,
      page,
      page_size: pageSize,
    },
  });
  return res.data;
}

/**
 * PII 检测（独立检测端点）。
 *
 * @param narrative - 待检测的叙事文本
 * @returns 检测结果（has_pii + warnings 列表）
 */
export async function detectPii(narrative: string): Promise<PiiDetectionResult> {
  const res = await httpClient.request<PiiDetectionResult>({
    url: `${BASE_PATH}/pii-check`,
    method: 'POST',
    data: { narrative },
  });
  return res.data;
}
