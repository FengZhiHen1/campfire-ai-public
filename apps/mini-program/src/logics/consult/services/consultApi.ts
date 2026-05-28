/**
 * CSLT-08 咨询 API 服务层 — MVP Phase 1 匿名适配版。
 *
 * 职责：
 * - 封装咨询相关全部 HTTP 请求
 * - 通过 httpClient.request() 发送（自动注入 X-Device-Id）
 * - 适配后端 POST /api/v1/consult 的 ConsultStartRequest/ConsultStartResponse 契约
 *
 * 契约对齐：
 *   POST /api/v1/consult 请求体 = { behavior_description, profile_id?, behavior_type?, emotion_level? }
 *   POST /api/v1/consult 响应体 = { session_id }
 *   SSE 端点 = GET /api/v1/consult/stream/{session_id}
 */

import { httpClient } from '../../shared/services/httpClient';
import type { IRequestResponse } from '../../shared/services/httpClient';
import type {
  BehaviorTypeCategory,
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
// 类型：咨询提交响应（前端内部使用，由 session_id 扩展而来）
// ============================================================================

/**
 * POST /api/v1/consult 的响应类型。
 * 后端仅返回 { session_id }，前端据此构建 stream_url 并填充 MVP 默认值。
 */
export interface ConsultSubmitResponse {
  /** SSE 流式推送端点 URL */
  stream_url: string;
  /** 会话 ID（用于重连） */
  session_id: string;
  /** 置信度校验输出（MVP 暂不启用，固定为 null） */
  confidence_output?: ConfidenceValidationOutput | null;
  /** 幂等请求 ID（前端生成） */
  request_id: string;
  /** 被引用案例 ID 列表（MVP 暂不填充） */
  referenced_slice_ids: string[];
  /** 法律合规声明 */
  disclaimer: string;
  /** 生成耗时毫秒（MVP 占位） */
  generation_time_ms: number;
  /** 是否为部分生成（MVP 占位） */
  is_partial: boolean;
  /** 完成原因（MVP 占位） */
  finish_reason: string;
  /** 首字延迟毫秒（MVP 占位） */
  ttft_ms: number;
  /** LLM 输入 Token 数（MVP 占位） */
  token_input?: number | null;
  /** LLM 输出 Token 数（MVP 占位） */
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
 * 所有请求通过 httpClient.request() 发送，X-Device-Id 由 httpClient 自动注入。
 */
export const consultApi = {
  /**
   * 提交咨询请求（步骤 3）。
   * POST /api/v1/consult
   *
   * MVP 适配：
   * - 请求体对齐后端 ConsultStartRequest（含 behavior_description / behavior_type / profile_id / emotion_level）
   * - 响应中仅 session_id 为后端真实返回，其余字段由前端填充默认值
   *
   * @param behaviorDescription - 行为描述文本
   * @param behaviorTypes - 行为类型列表（用户多选）
   * @param profileId - 关联档案 ID（可选）
   * @param emotionLevel - 情绪等级（可选）
   * @param requestId - 幂等请求 ID（前端生成，仅本地使用）
   * @returns 提交响应（含 stream_url 和 session_id）
   * @throws 网络异常或 HTTP 5xx 时抛出
   */
  async submitConsult(
    behaviorDescription: string,
    behaviorTypes: BehaviorTypeCategory[],
    profileId: string | undefined,
    emotionLevel: string | undefined,
    requestId: string,
  ): Promise<ConsultSubmitResponse> {
    const res = await httpClient.request<{ session_id: string }>({
      url: CONSULT_API_PATH,
      method: 'POST',
      data: {
        behavior_description: behaviorDescription,
        behavior_type: behaviorTypes.length > 0 ? behaviorTypes : undefined,
        profile_id: profileId,
        emotion_level: emotionLevel,
      },
      timeout: 30000,
      header: {
        'Content-Type': 'application/json',
      },
    });

    const { session_id } = res.data;

    // 由 session_id 构建 SSE stream_url。小程序不走 webpack proxy，
    // 必须拼接完整的 API base URL（本地或 ngrok 公网地址）
    const API_BASE: string = process.env.TARO_APP_API_BASE || '';
    const stream_url = API_BASE
      ? `${API_BASE}${CONSULT_API_PATH}/stream/${session_id}`
      : `${CONSULT_API_PATH}/stream/${session_id}`;

    // MVP 阶段：后端仅返回 session_id，其余字段填充占位值
    return {
      stream_url,
      session_id,
      request_id: requestId,
      confidence_output: null,
      referenced_slice_ids: [],
      disclaimer:
        '以上建议由 AI 生成，仅供参考，不构成医疗诊断或治疗建议。如情况紧急，请立即联系专业医疗机构。',
      generation_time_ms: 0,
      is_partial: false,
      finish_reason: 'COMPLETE',
      ttft_ms: 0,
      token_input: null,
      token_output: null,
    };
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
