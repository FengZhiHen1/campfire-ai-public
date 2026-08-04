/**
 * 应急咨询 API 客户端（ADR-009 端点族）。
 * 经新 infrastructure httpClient（Bearer 注入 + 401 刷新）。
 */

import { httpClient } from '@/infrastructure/http/httpClient';
import type { SafetyCardPayload } from '../types';

export interface ConsultHistoryItem {
  id: string;
  bucket: string;
  crisis_stage: string | null;
  turn_count: number;
  created_at: string;
}

export interface ConsultHistoryList {
  items: ConsultHistoryItem[];
  total: number;
  page?: number;
  page_size?: number;
}

export const consultApi = {
  /** 0 输入通用安全卡 */
  async fetchUniversalCard(): Promise<SafetyCardPayload | null> {
    const res = await httpClient.request<{ card: SafetyCardPayload | null }>(
      '/api/v1/consult/safety-card/universal',
    );
    return res.card;
  },

  /** 创建会话（桶选择） */
  async createSession(bucket: string, profileId?: string, text?: string): Promise<string> {
    const res = await httpClient.request<{ session_id: string }>('/api/v1/consult/stream', {
      method: 'POST',
      data: { bucket, profile_id: profileId ?? null, text: text ?? null },
    });
    return res.session_id;
  },

  /** 阶段回答推进 */
  async answerStage(sessionId: string, answer: string): Promise<void> {
    await httpClient.request('/api/v1/consult/stream', {
      method: 'POST',
      data: { session_id: sessionId, stage_answer: answer },
    });
  },

  /** 补充文字描述（精化重生成） */
  async appendText(sessionId: string, text: string): Promise<void> {
    await httpClient.request('/api/v1/consult/stream', {
      method: 'POST',
      data: { session_id: sessionId, text },
    });
  },

  /** 追问轮 */
  async followup(sessionId: string, text: string): Promise<void> {
    await httpClient.request(`/api/v1/consult/stream/${sessionId}/followup`, {
      method: 'POST',
      data: { text },
    });
  },

  /** 未解决标记（兜底信号） */
  async markUnresolved(sessionId: string): Promise<void> {
    await httpClient.request(`/api/v1/consult/stream/${sessionId}/unresolved`, {
      method: 'POST',
      data: { mark: true },
    });
  },

  /** 历史列表（兼容 HomePage 使用面） */
  async fetchHistoryList(page = 1, pageSize = 20): Promise<ConsultHistoryList> {
    const res = await httpClient.request<{ items: ConsultHistoryItem[]; total: number }>(
      '/api/v1/consult/history',
    );
    return { ...res, page, page_size: pageSize };
  },
};
