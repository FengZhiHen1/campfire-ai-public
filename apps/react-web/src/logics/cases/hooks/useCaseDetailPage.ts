/**
 * CASE-09 案例管理逻辑 — 案例详情页 Hook。
 *
 * 封装 CasesDetail 页面的全部业务逻辑：数据查询、加载/错误状态、
 * 导航操作。View 层仅负责 JSX 渲染。
 *
 * 调用路径：views/cases/pages/detail → useCaseDetailPage → narrativeApi
 */

import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getNarrative } from '../services/narrativeApi';
import { STATUS_TEXT_MAP, STATUS_CLASS_MAP, SOURCE_LABEL_MAP, CARD_STATUS_MAP } from '../types/constants';
import type { NarrativeDetail } from '../types';

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
  const navigate = useNavigate();
  const { id: narrativeId } = useParams<{ id: string }>();
  const [data, setData] = useState<NarrativeDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDetail = useCallback((targetId: string) => {
    setLoading(true);
    setError(null);
    getNarrative(targetId)
      .then((res) => setData(res))
      .catch(() => {
        setError('加载失败，请稍后重试');
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (narrativeId) {
      fetchDetail(narrativeId);
    }
  }, [narrativeId, fetchDetail]);

  const handleGoExtract = () => {
    if (!narrativeId) return;
    navigate(`/cases/extraction/${narrativeId}`);
  };

  const handleEditNarrative = () => {
    if (!narrativeId) return;
    navigate(`/cases/narrative?mode=edit&narrativeId=${narrativeId}`);
  };

  const handleCardClick = (cardId: string) => {
    // 从案例库查看已入库的干预卡片，跳转到「干预卡片」详情页
    navigate(`/cases/card/${cardId}`);
  };

  const handleRetry = useCallback(() => {
    if (narrativeId) {
      fetchDetail(narrativeId);
    }
  }, [narrativeId, fetchDetail]);

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
