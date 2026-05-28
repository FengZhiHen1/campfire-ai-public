/**
 * CSLT-08 咨询 API 服务层。
 *
 * 职责：
 * - 封装咨询相关全部 HTTP 请求
 * - 通过 httpClient.request() 发送（已注入 Token + 401 续期）
 * - 包含 submitConsult、fetchHistoryList、fetchHistoryDetail
 *
 * 设计依据：CSLT-08 落地规范 §1.7 步骤 3-6
 * 契约对齐：AUTH-06 httpClient、CSLT-06 ConsultationHistoryList/Detail
 */

import { httpClient } from '../../shared/services/httpClient';
import type { IRequestResponse } from '../../shared/services/httpClient';
import type {
  ConsultSubmitRequest,
  ConsultationHistoryListItem,
  ConsultationHistoryDetail,
  ConfidenceValidationOutput,
} from '../types/index';

// ============================================================================
// API 路径常量
// ============================================================================

/** 咨询提交端点 */
const CONSULT_API_PATH = '/api/v1/consult';

/** 咨询历史端点 */
const HISTORY_API_PATH = '/api/v1/consultations';

// ============================================================================
// 类型：咨询提交响应
// ============================================================================

/**
 * POST /api/v1/consult 的响应类型。
 */
export interface ConsultSubmitResponse {
  /** SSE 流式推送端点 URL */
  stream_url: string;
  /** 会话 ID（用于重连） */
  session_id: string;
  /** 置信度校验输出 */
  confidence_output?: ConfidenceValidationOutput;
  /** 幂等请求 ID */
  request_id: string;
  /** 被引用案例 ID 列表 */
  referenced_slice_ids: string[];
  /** 法律合规声明 */
  disclaimer: string;
  /** 生成耗时毫秒 */
  generation_time_ms: number;
  /** 是否为部分生成 */
  is_partial: boolean;
  /** 完成原因 */
  finish_reason: string;
  /** 首字延迟毫秒 */
  ttft_ms: number;
  /** LLM 输入 Token 数 */
  token_input?: number | null;
  /** LLM 输出 Token 数 */
  token_output?: number | null;
}

/**
 * 历史列表分页响应类型。
 */
export interface HistoryListResponse {
  items: ConsultationHistoryListItem[];
  total: number;
  page: number;
  page_size: number;
}

// ============================================================================
// consultApi 对象
// ============================================================================

/**
 * 咨询 API 服务。
 * 封装咨询提交、历史列表查询、历史详情查询。
 * 所有请求通过 httpClient.request() 发送，Token 注入和 401 续期由 httpClient 自动处理。
 */
export const consultApi = {
  /**
   * 提交咨询请求（步骤 3）。
   * POST /api/v1/consult
   *
   * 请求成功时返回 SSE 流端点 URL 和置信度校验输出。
   *
   * @param request - 咨询请求体（行为类型 + 行为描述）
   * @param requestId - 幂等请求 ID（UUID v4）
   * @returns 提交响应（含 stream_url 和 confidence_output）
   * @throws 网络异常或 HTTP 5xx 时抛出
   */
  async submitConsult(
    request: ConsultSubmitRequest,
    requestId: string,
  ): Promise<ConsultSubmitResponse> {
    const res = await httpClient.request<ConsultSubmitResponse>({
      url: CONSULT_API_PATH,
      method: 'POST',
      data: {
        ...request,
        request_id: requestId,
      },
      timeout: 10000,
      header: {
        'Content-Type': 'application/json',
      },
    });
    return res.data;
  },

  /**
   * 获取咨询历史列表。
   * GET /api/v1/consultations?page={page}&page_size={pageSize}
   *
   * @param page - 页码（从 1 开始）
   * @param pageSize - 每页条目数
   * @returns 分页历史列表
   */
  async fetchHistoryList(
    page: number,
    pageSize: number,
  ): Promise<HistoryListResponse> {
    const res = await httpClient.request<HistoryListResponse>({
      url: HISTORY_API_PATH,
      method: 'GET',
      data: {
        page,
        page_size: pageSize,
      },
      header: {
        'Content-Type': 'application/json',
      },
    });
    return res.data;
  },

  /**
   * 获取咨询历史详情（只读）。
   * GET /api/v1/consultations/{consultationId}
   *
   * @param consultationId - 咨询记录 ID
   * @returns 咨询历史详情
   */
  async fetchHistoryDetail(
    consultationId: string,
  ): Promise<ConsultationHistoryDetail> {
    const res = await httpClient.request<ConsultationHistoryDetail>({
      url: `${HISTORY_API_PATH}/${consultationId}`,
      method: 'GET',
      header: {
        'Content-Type': 'application/json',
      },
    });
    return res.data;
  },

  /**
   * 归档写入咨询历史（步骤 6）。
   * POST /api/v1/consultations
   *
   * 非阻塞——写入失败不阻断用户浏览当前结果。
   *
   * @param data - 咨询历史归档数据
   */
  async archiveConsultation(data: Record<string, unknown>): Promise<void> {
    try {
      await httpClient.request({
        url: HISTORY_API_PATH,
        method: 'POST',
        data,
        header: {
          'Content-Type': 'application/json',
        },
      });
    } catch {
      // 归档写入失败为降级场景：不阻塞用户
      console.debug('archive_failed', { request_id: data.request_id });
    }
  },
};
