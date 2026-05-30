/**
 * CASE-09 案例管理逻辑 — 提取结果页 Hook。
 *
 * 封装 ExtractionResult 页面的全部业务逻辑：卡片列表加载、
 * 编辑态管理、保存/提交操作。View 层仅负责 JSX 渲染。
 *
 * 调用路径：views/cases/pages/extraction-result → useExtractionResult → httpClient
 *           （卡片 CRUD 暂未抽象到独立 service，直接通过 httpClient 调用）
 */

import { useState, useEffect, useCallback } from 'react';
import Taro from '@tarojs/taro';
import { httpClient } from '../../shared/services/httpClient';
import {
  BEHAVIOR_TYPE_OPTIONS,
  SEVERITY_OPTIONS,
  SCENE_OPTIONS,
  FAMILY_CATEGORY_OPTIONS,
} from '../types/constants';

// ============================================================================
// 类型定义
// ============================================================================

/** AI 提取的卡片数据 */
interface CardData {
  card_id: string;
  title: string;
  scenario: string;
  behavior_type: string;
  age_range: number[];
  severity: string;
  scene: string;
  ebp_labels: string[];
  family_category: string;
  immediate_action: string;
  comforting_phrase: string;
  observation_metrics: string;
  medical_criteria: string;
  evidence_level: string;
  caution_notes: string;
  contraindications: string;
  is_template: boolean;
  inferred_fields?: Record<string, string>;
}

/** 叙事 API 返回的卡片列表响应 */
interface NarrativeCardsResponse {
  cards: CardData[];
}

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
    httpClient.request<NarrativeCardsResponse>({
      url: `/api/v1/narratives/${narrativeId}`,
      method: 'GET',
    }).then((res) => {
      const cardList = res.data.cards || [];
      setCards(cardList);
      if (cardList.length > 0) {
        setEditing({ ...cardList[0] });
      }
    }).catch(() => {
      Taro.showToast({ title: '加载失败', icon: 'none' });
    }).finally(() => setLoading(false));
  }, [narrativeId]);

  const switchTab = useCallback((idx: number) => {
    setActiveTab(idx);
    setEditing(cards[idx] ? { ...cards[idx] } : null);
  }, [cards]);

  const updateField = useCallback((field: string, value: unknown) => {
    if (!editing) return;
    setEditing({ ...editing, [field]: value });
  }, [editing]);

  const saveCard = useCallback(async () => {
    if (!editing) return;
    try {
      await httpClient.request({
        url: `/api/v1/cards/${editing.card_id}`,
        method: 'PUT',
        data: editing,
        header: { 'Content-Type': 'application/json' },
      });
      const updated = cards.map((c) => c.card_id === editing.card_id ? editing : c);
      setCards(updated);
      Taro.showToast({ title: '已保存', icon: 'success' });
    } catch {
      Taro.showToast({ title: '保存失败', icon: 'none' });
    }
  }, [editing, cards]);

  const submitAll = useCallback(async () => {
    try {
      for (const card of cards) {
        await httpClient.request({
          url: `/api/v1/cards/${card.card_id}/submit`,
          method: 'POST',
          header: { 'Content-Type': 'application/json' },
        });
      }
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
