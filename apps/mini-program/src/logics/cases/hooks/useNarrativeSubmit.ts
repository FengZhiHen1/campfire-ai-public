/**
 * CASE-09 案例管理逻辑 — 叙事提交页 Hook。
 *
 * 封装 NarrativeSubmit 页面的全部业务逻辑：表单状态、来源类型选择、
 * 叙事创建 + AI 提取流程。View 层仅负责 JSX 渲染。
 *
 * 调用路径：views/cases/pages/narrative-submit → useNarrativeSubmit → narrativeApi
 */

import { useState, useCallback } from 'react';
import Taro from '@tarojs/taro';
import { createNarrative, extractNarrative } from '../services/narrativeApi';
import { SOURCE_TYPE_OPTIONS, WRITING_TIPS, NARRATIVE_BODY_PLACEHOLDER } from '../types/constants';

// ============================================================================
// 类型定义
// ============================================================================

/** useNarrativeSubmit 的返回值 */
export interface UseNarrativeSubmitReturn {
  title: string;
  setTitle: (v: string) => void;
  sourceType: string;
  setSourceType: (v: string) => void;
  narrative: string;
  setNarrative: (v: string) => void;
  submitting: boolean;
  extracting: boolean;
  tipsExpanded: boolean;
  setTipsExpanded: (v: boolean) => void;
  titleCount: number;
  bodyCount: number;
  canSubmit: boolean;
  handleSaveDraft: () => void;
  handleSubmit: () => Promise<void>;
  sourceOptions: readonly string[];
  writingTips: readonly string[];
  bodyPlaceholder: string;
}

// ============================================================================
// Hook
// ============================================================================

export function useNarrativeSubmit(): UseNarrativeSubmitReturn {
  const [title, setTitle] = useState(() => {
    try { return Taro.getStorageSync('narrative_draft_title') || ''; } catch { return ''; }
  });
  const [sourceType, setSourceType] = useState(() => {
    try { return Taro.getStorageSync('narrative_draft_source') || '专家撰写'; } catch { return '专家撰写'; }
  });
  const [narrative, setNarrative] = useState(() => {
    try { return Taro.getStorageSync('narrative_draft_body') || ''; } catch { return ''; }
  });
  const [submitting, setSubmitting] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [tipsExpanded, setTipsExpanded] = useState(true);

  const titleCount = title.length;
  const bodyCount = narrative.length;
  const canSubmit = Boolean(title.trim() && narrative.trim());

  const persistDraft = useCallback(() => {
    try {
      Taro.setStorageSync('narrative_draft_title', title);
      Taro.setStorageSync('narrative_draft_source', sourceType);
      Taro.setStorageSync('narrative_draft_body', narrative);
    } catch { /* 存储失败不阻断 */ }
  }, [title, sourceType, narrative]);

  const handleSaveDraft = useCallback(() => {
    if (!title.trim() && !narrative.trim()) {
      Taro.showToast({ title: '请先输入内容', icon: 'none' });
      return;
    }
    persistDraft();
    Taro.showToast({ title: '草稿已保存', icon: 'success' });
  }, [title, narrative, persistDraft]);

  const clearDraft = useCallback(() => {
    try {
      Taro.removeStorageSync('narrative_draft_title');
      Taro.removeStorageSync('narrative_draft_source');
      Taro.removeStorageSync('narrative_draft_body');
    } catch { /* 清理失败不阻断 */ }
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const res = await createNarrative({ title, narrative, source_type: sourceType });
      const narrativeId = res.narrative_id;
      clearDraft();
      await triggerExtraction(narrativeId);
    } catch {
      Taro.showToast({ title: '提交失败', icon: 'none' });
      setSubmitting(false);
    }
  }, [canSubmit, title, narrative, sourceType, clearDraft]);

  const triggerExtraction = useCallback(async (narrativeId: string) => {
    setExtracting(true);
    try {
      await extractNarrative(narrativeId);
      setSubmitting(false);
      setExtracting(false);
      Taro.redirectTo({
        url: `/views/cases/pages/extraction-result?narrativeId=${narrativeId}`,
      });
    } catch {
      setSubmitting(false);
      setExtracting(false);
      Taro.showToast({ title: '提取失败，请稍后重试', icon: 'none' });
    }
  }, []);

  return {
    title,
    setTitle,
    sourceType,
    setSourceType,
    narrative,
    setNarrative,
    submitting,
    extracting,
    tipsExpanded,
    setTipsExpanded,
    titleCount,
    bodyCount,
    canSubmit,
    handleSaveDraft,
    handleSubmit,
    sourceOptions: SOURCE_TYPE_OPTIONS,
    writingTips: WRITING_TIPS,
    bodyPlaceholder: NARRATIVE_BODY_PLACEHOLDER,
  };
}
