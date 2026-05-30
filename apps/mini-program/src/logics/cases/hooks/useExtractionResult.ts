/**
 * CASE-09 案例管理逻辑 — 提取结果页 Hook。
 *
 * 封装 ExtractionResult 页面的全部业务逻辑：卡片列表加载、
 * 编辑态管理、保存/提交操作。View 层仅负责 JSX 渲染。
 *
 * 调用路径：views/cases/pages/extraction-result → useExtractionResult → cardApi → httpClient
 */

import { useState, useEffect, useCallback, useRef } from 'react';
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
  isSaving: boolean;
  isSubmittingAll: boolean;
  extracting: boolean;
  extractFailed: boolean;
  narrativeId: string;
  setActiveTab: (idx: number) => void;
  updateField: (field: string, value: unknown) => void;
  saveCard: () => Promise<void>;
  submitAll: () => Promise<void>;
  retryExtraction: () => void;
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
  const [isSaving, setIsSaving] = useState(false);
  const [isSubmittingAll, setIsSubmittingAll] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractFailed, setExtractFailed] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const narrativeId: string = Taro.getCurrentInstance().router?.params?.narrativeId || '';

  // DEBUG: 确认 narrativeId 是否正确传入
  console.debug('[extraction-result] narrativeId:', narrativeId, 'router:', Taro.getCurrentInstance().router);

  const loadNarrative = useCallback(() => {
    if (!narrativeId) {
      console.debug('[extraction-result] loadNarrative skipped — narrativeId is empty');
      return;
    }
    getNarrative(narrativeId)
      .then((res) => {
        const status = res.extraction_status || 'pending';
        if (status === 'extracted' || (res.cards && res.cards.length > 0)) {
          // 卡片已就绪
          const cardList: CardData[] = (res.cards || []) as unknown as CardData[];
          setCards(cardList);
          if (cardList.length > 0) {
            setEditing(deepCloneCard(cardList[0]));
          }
          setLoading(false);
          setExtracting(false);
          setExtractFailed(false);
          if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null; }
        } else if (status === 'failed') {
          setLoading(false);
          setExtracting(false);
          setExtractFailed(true);
          if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null; }
        } else {
          // pending 或 extracting：继续轮询
          setExtracting(true);
          setLoading(false);
          if (!pollTimer.current) {
            pollTimer.current = setInterval(() => loadNarrative(), 3000);
          }
        }
      })
      .catch(() => {
        setLoading(false);
        setExtracting(false);
        if (!pollTimer.current) {
          // 网络错误也重试轮询
          pollTimer.current = setInterval(() => loadNarrative(), 5000);
        }
      });
  }, [narrativeId]);

  useEffect(() => {
    if (!narrativeId) return;
    loadNarrative();
    return () => {
      if (pollTimer.current) {
        clearInterval(pollTimer.current);
        pollTimer.current = null;
      }
    };
  }, [narrativeId, loadNarrative]);

  const retryExtraction = useCallback(() => {
    setExtractFailed(false);
    setExtracting(true);
    loadNarrative();
  }, [loadNarrative]);

  const switchTab = useCallback((idx: number) => {
    setActiveTab(idx);
    setEditing(cards[idx] ? deepCloneCard(cards[idx]) : null);
  }, [cards]);

  const updateField = useCallback((field: string, value: unknown) => {
    if (!editing) return;
    setEditing({ ...editing, [field]: value });
  }, [editing]);

  const saveCard = useCallback(async () => {
    if (!editing || isSaving) return;
    setIsSaving(true);
    try {
      const updated = await updateCard(editing.card_id, editing);
      const newCards = cards.map((c) => c.card_id === editing.card_id ? updated : c);
      setCards(newCards);
      setEditing(updated);
      Taro.showToast({ title: '已保存', icon: 'success' });
    } catch {
      Taro.showToast({ title: '保存失败', icon: 'none' });
    } finally {
      setIsSaving(false);
    }
  }, [editing, cards, isSaving]);

  const submitAll = useCallback(async () => {
    if (isSubmittingAll) return;
    setIsSubmittingAll(true);
    try {
      await Promise.all(cards.map((card) => submitCard(card.card_id)));
      Taro.showToast({ title: '全部卡片已提交审核' });
      Taro.navigateBack();
    } catch {
      Taro.showToast({ title: '提交失败', icon: 'none' });
    } finally {
      setIsSubmittingAll(false);
    }
  }, [cards, isSubmittingAll]);

  return {
    cards,
    activeTab,
    editing,
    loading,
    isSaving,
    isSubmittingAll,
    extracting,
    extractFailed,
    narrativeId,
    setActiveTab: switchTab,
    updateField,
    saveCard,
    submitAll,
    retryExtraction,
    behaviorTypeOptions: BEHAVIOR_TYPE_OPTIONS,
    severityOptions: SEVERITY_OPTIONS,
    sceneOptions: SCENE_OPTIONS,
    categoryOptions: FAMILY_CATEGORY_OPTIONS,
  };
}
