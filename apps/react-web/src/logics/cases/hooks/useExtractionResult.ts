/**
 * CASE-09 案例管理逻辑 — 提取结果页 Hook。
 *
 * 封装 ExtractionResult 页面的全部业务逻辑：卡片列表加载、
 * 编辑态管理、保存/提交操作。View 层仅负责 JSX 渲染。
 *
 * 调用路径：views/cases/pages/extraction-result → useExtractionResult → cardApi → httpClient
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { updateCard, submitCard } from '../services/cardApi';
import { showToast } from '../../shared/utils/toast';
import { getNarrative, extractNarrative, submitNarrative } from '../services/narrativeApi';
import { HttpError } from '../../shared/services/httpClient';
import {
  BEHAVIOR_TYPE_OPTIONS,
  SEVERITY_OPTIONS,
  SCENE_OPTIONS,
  FAMILY_CATEGORY_OPTIONS,
} from '../types/constants';
import type { CardData } from '../services/cardApi';

function getErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof HttpError && err.data) {
    const data = err.data as Record<string, unknown>;
    if (Array.isArray(data.errors) && data.errors.length > 0) {
      const first = data.errors[0] as Record<string, unknown>;
      if (typeof first.constraint === 'string') return first.constraint;
      if (typeof first.reason === 'string') return first.reason;
    }
    if (typeof data.detail === 'string') return data.detail;
    if (typeof data.message === 'string') return data.message;
  }
  if (err instanceof Error) return err.message;
  return fallback;
}

function isHardError(err: unknown): boolean {
  if (err instanceof HttpError) {
    // 4xx 客户端错误（除超时/限流外）不再重试
    return err.statusCode >= 400 && err.statusCode < 500 && err.statusCode !== 408 && err.statusCode !== 429;
  }
  return false;
}

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
  canSubmitAll: boolean;
  extracting: boolean;
  extractFailed: boolean;
  extractError: string | null;
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
  const navigate = useNavigate();
  const [cards, setCards] = useState<CardData[]>([]);
  const [activeTab, setActiveTab] = useState(0);
  const [editing, setEditing] = useState<CardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isSubmittingAll, setIsSubmittingAll] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractFailed, setExtractFailed] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const { id } = useParams<{ id: string }>();
  const narrativeId = id ?? '';

  // DEBUG: 确认 narrativeId 是否正确传入
  console.debug('[extraction-result] narrativeId:', narrativeId);

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
          setExtractError(null);
          if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null; }
        } else if (status === 'failed') {
          setLoading(false);
          setExtracting(false);
          setExtractFailed(true);
          setExtractError(res.extraction_error || 'AI 提取失败，未返回具体原因');
          if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null; }
        } else {
          // pending 或 extracting：继续轮询
          setExtracting(true);
          setExtractFailed(false);
          setExtractError(null);
          setLoading(false);
          if (!pollTimer.current) {
            pollTimer.current = setInterval(() => loadNarrative(), 3000);
          }
        }
      })
      .catch((err) => {
        const message = getErrorMessage(err, '加载失败');
        setLoading(false);
        setExtracting(false);
        if (isHardError(err)) {
          // 客户端错误（404/422 等）：停止轮询，展示错误
          setExtractFailed(true);
          setExtractError(message);
          if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null; }
        } else if (!pollTimer.current) {
          // 网络/服务端抖动：延长轮询
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

  const retryExtraction = useCallback(async () => {
    setExtractFailed(false);
    setExtractError(null);
    setExtracting(true);
    try {
      await extractNarrative(narrativeId);
    } catch (err) {
      const message = getErrorMessage(err, '重试提取失败');
      setExtracting(false);
      setExtractFailed(true);
      setExtractError(message);
      showToast({ title: message, icon: 'none' });
      return;
    }
    // 触发成功后开始轮询
    loadNarrative();
  }, [loadNarrative, narrativeId]);

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
      showToast({ title: '已保存', icon: 'success' });
    } catch {
      showToast({ title: '保存失败', icon: 'none' });
    } finally {
      setIsSaving(false);
    }
  }, [editing, cards, isSaving]);

  const draftCards = cards.filter((c) => c.review_status === 'draft');
  const canSubmitAll = draftCards.length > 0;

  const submitAll = useCallback(async () => {
    if (isSubmittingAll || draftCards.length === 0) return;
    setIsSubmittingAll(true);
    try {
      await Promise.all(draftCards.map((card) => submitCard(card.card_id)));
      const submittedIds = new Set(draftCards.map((c) => c.card_id));
      setCards((prev) =>
        prev.map((c) =>
          submittedIds.has(c.card_id) ? { ...c, review_status: 'pending_review' } : c,
        ),
      );
      // 卡片全部提交后，同步将叙事本身也提交为待审核，保持列表状态一致。
      if (narrativeId) {
        await submitNarrative(narrativeId);
      }
      showToast({ title: '全部卡片已提交审核' });
      navigate(-1);
    } catch (err) {
      const message = getErrorMessage(err, '提交失败');
      showToast({ title: message, icon: 'none' });
    } finally {
      setIsSubmittingAll(false);
    }
  }, [draftCards, isSubmittingAll, navigate, narrativeId]);

  return {
    cards,
    activeTab,
    editing,
    loading,
    isSaving,
    isSubmittingAll,
    canSubmitAll,
    extracting,
    extractFailed,
    extractError,
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
