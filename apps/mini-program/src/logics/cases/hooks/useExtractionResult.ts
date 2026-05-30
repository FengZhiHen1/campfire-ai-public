/**
 * CASE-09 案例管理逻辑 — 提取结果页 Hook。
 *
 * 封装 ExtractionResult 页面的全部业务逻辑：卡片列表加载、
 * 编辑态管理、保存/提交操作。View 层仅负责 JSX 渲染。
 *
 * 调用路径：views/cases/pages/extraction-result → useExtractionResult → cardApi → httpClient
 */

import { useState, useEffect, useCallback } from 'react';
import Taro from '@tarojs/taro';
import { updateCard, submitCard } from '../services/cardApi';
import { getNarrative } from '../services/narrativeApi';
import {
  BEHAVIOR_TYPE_OPTIONS,
  SEVERITY_OPTIONS,
  SCENE_OPTIONS,
  FAMILY_CATEGORY_OPTIONS,
} from '../types/constants';
import type { CardData } from '../services/cardApi';

// ============================================================================
// 类型定义
// ============================================================================

/** useExtractionResult 的返回值 */
export interface UseExtractionResultReturn {
  cards: CardData[];
  activeTab: number;
  editing: CardData | null;
  loading: boolean;
  narrativeId: string;
  setActiveTab: (idx: number) => void;
  updateField: (field: string, value: unknown) => void;
  saveCard: () => Promise<void>;
  submitAll: () => Promise<void>;
  behaviorTypeOptions: readonly string[];
  severityOptions: readonly string[];
  sceneOptions: readonly string[];
  categoryOptions: readonly string[];
}

// ============================================================================
// 辅助函数
// ============================================================================

function deepCloneCard(card: CardData): CardData {
  return {
    ...card,
    age_range: [...card.age_range],
    ebp_labels: [...card.ebp_labels],
    inferred_fields: card.inferred_fields ? { ...card.inferred_fields } : undefined,
  };
}

// ============================================================================
// Hook
// ============================================================================

export function useExtractionResult(): UseExtractionResultReturn {
  const [cards, setCards] = useState<CardData[]>([]);
  const [activeTab, setActiveTab] = useState(0);
  const [editing, setEditing] = useState<CardData | null>(null);
  const [loading, setLoading] = useState(true);

  const narrativeId: string = Taro.getCurrentInstance().router?.params?.narrativeId || '';

  useEffect(() => {
    if (!narrativeId) return;
    getNarrative(narrativeId)
      .then((res) => {
        const cardList: CardData[] = (res.cards || []) as unknown as CardData[];
        setCards(cardList);
        if (cardList.length > 0) {
          setEditing(deepCloneCard(cardList[0]));
        }
      })
      .catch(() => {
        Taro.showToast({ title: '加载失败', icon: 'none' });
      })
      .finally(() => setLoading(false));
  }, [narrativeId]);

  const switchTab = useCallback((idx: number) => {
    setActiveTab(idx);
    setEditing(cards[idx] ? deepCloneCard(cards[idx]) : null);
  }, [cards]);

  const updateField = useCallback((field: string, value: unknown) => {
    if (!editing) return;
    setEditing({ ...editing, [field]: value });
  }, [editing]);

  const saveCard = useCallback(async () => {
    if (!editing) return;
    try {
      const updated = await updateCard(editing.card_id, editing);
      const newCards = cards.map((c) => c.card_id === editing.card_id ? updated : c);
      setCards(newCards);
      setEditing(updated);
      Taro.showToast({ title: '已保存', icon: 'success' });
    } catch {
      Taro.showToast({ title: '保存失败', icon: 'none' });
    }
  }, [editing, cards]);

  const submitAll = useCallback(async () => {
    try {
      await Promise.all(cards.map((card) => submitCard(card.card_id)));
      Taro.showToast({ title: '全部卡片已提交审核' });
      Taro.navigateBack();
    } catch {
      Taro.showToast({ title: '提交失败', icon: 'none' });
    }
  }, [cards]);

  return {
    cards,
    activeTab,
    editing,
    loading,
    narrativeId,
    setActiveTab: switchTab,
    updateField,
    saveCard,
    submitAll,
    behaviorTypeOptions: BEHAVIOR_TYPE_OPTIONS,
    severityOptions: SEVERITY_OPTIONS,
    sceneOptions: SCENE_OPTIONS,
    categoryOptions: FAMILY_CATEGORY_OPTIONS,
  };
}
