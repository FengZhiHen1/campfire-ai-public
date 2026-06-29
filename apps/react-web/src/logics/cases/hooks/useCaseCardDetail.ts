/**
 * CASE-09 案例管理逻辑 — 干预卡片详情页 Hook。
 *
 * 封装 CardDetail 页面的数据获取与重试逻辑。
 * View 层仅负责 JSX 渲染。
 */

import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { getCard } from '../services/cardApi';
import type { CardData } from '../services/cardApi';

export interface UseCaseCardDetailReturn {
  data: CardData | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useCaseCardDetail(): UseCaseCardDetailReturn {
  const { id: cardId } = useParams<{ id: string }>();
  const [data, setData] = useState<CardData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchCard = useCallback((targetId: string) => {
    setLoading(true);
    setError(null);
    getCard(targetId)
      .then((res) => setData(res))
      .catch(() => setError('加载卡片失败，请稍后重试'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (cardId) {
      fetchCard(cardId);
    }
  }, [cardId, fetchCard]);

  const refetch = useCallback(() => {
    if (cardId) {
      fetchCard(cardId);
    }
  }, [cardId, fetchCard]);

  return { data, loading, error, refetch };
}
