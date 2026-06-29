/**
 * CASE-09 案例管理逻辑 — 案例详情页 Hook。
 *
 * 封装 CasesDetail 页面的全部业务逻辑：数据查询、加载/错误状态、
 * 导航操作。View 层仅负责 JSX 渲染。
 *
 * 调用路径：views/cases/pages/detail → useCaseDetailPage → narrativeApi
 */

import { useState, useEffect, useCallback } from 'react';
import Taro from '@tarojs/taro';
import { getNarrative } from '../services/narrativeApi';
import { STATUS_TEXT_MAP, STATUS_CLASS_MAP, SOURCE_LABEL_MAP, CARD_STATUS_MAP } from '../types/constants';
import type { NarrativeDetail, CardSummary } from '../types';

// ============================================================================
// 类型定义
// ============================================================================

/** useCaseDetailPage 的返回值 */
export interface UseCaseDetailPageReturn {
  data: NarrativeDetail | null;
  loading: boolean;
  error: string | null;
  handleGoExtract: () => void;
  handleEditNarrative: () => void;
  handleCardClick: (cardId: string) => void;
  handleRetry: () => void;
  statusTextMap: Record<string, string>;
  statusClassMap: Record<string, string>;
  sourceLabelMap: Record<string, string>;
  cardStatusMap: Record<string, { text: string; cls: string }>;
}

// ============================================================================
// Hook
// ============================================================================

export function useCaseDetailPage(): UseCaseDetailPageReturn {
  const [data, setData] = useState<NarrativeDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDetail = useCallback(() => {
    const params = Taro.getCurrentInstance().router?.params;
    const narrativeId = params?.narrativeId;
    if (!narrativeId) return;

    setLoading(true);
    setError(null);
    getNarrative(narrativeId)
      .then((res) => setData(res))
      .catch(() => {
        setError('加载失败，请稍后重试');
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchDetail(); }, [fetchDetail]);

  const handleGoExtract = () => {
    if (!data) return;
    Taro.navigateTo({ url: `/views/cases/pages/extraction-result?narrativeId=${data.narrative_id}` });
  };

  const handleEditNarrative = () => {
    if (!data) return;
    Taro.navigateTo({ url: `/views/cases/pages/narrative-submit?mode=edit&narrativeId=${data.narrative_id}` });
  };

  const handleCardClick = (cardId: string) => {
    // 从案例库查看已入库的干预卡片，跳转到「干预卡片」详情页
    Taro.navigateTo({ url: `/views/cases/pages/card-detail?cardId=${cardId}` });
  };

  const handleRetry = useCallback(() => { fetchDetail(); }, [fetchDetail]);

  return {
    data,
    loading,
    error,
    handleGoExtract,
    handleEditNarrative,
    handleCardClick,
    handleRetry,
    statusTextMap: STATUS_TEXT_MAP,
    statusClassMap: STATUS_CLASS_MAP,
    sourceLabelMap: SOURCE_LABEL_MAP,
    cardStatusMap: CARD_STATUS_MAP,
  };
}
