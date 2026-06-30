/**
 * CASE-09 案例管理逻辑 — 叙事提交页 Hook。
 *
 * 封装 NarrativeSubmit 页面的全部业务逻辑：表单状态、来源类型选择、
 * 叙事创建 + AI 提取流程。View 层仅负责 JSX 渲染。
 *
 * 调用路径：views/cases/pages/narrative-submit → useNarrativeSubmit → narrativeApi
 */

import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { createNarrative, extractNarrative } from '../services/narrativeApi';
import { HttpError } from '../../shared/services/httpClient';
import { showToast } from '../../shared/utils/toast';
import { SOURCE_TYPE_OPTIONS, WRITING_TIPS, NARRATIVE_BODY_PLACEHOLDER } from '../types/constants';

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
  const navigate = useNavigate();
  const [title, setTitle] = useState(() => {
    try { return localStorage.getItem('narrative_draft_title') || ''; } catch { return ''; }
  });
  const [sourceType, setSourceType] = useState(() => {
    try { return localStorage.getItem('narrative_draft_source') || '专家撰写'; } catch { return '专家撰写'; }
  });
  const [narrative, setNarrative] = useState(() => {
    try { return localStorage.getItem('narrative_draft_body') || ''; } catch { return ''; }
  });
  const [submitting, setSubmitting] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [tipsExpanded, setTipsExpanded] = useState(true);

  const titleCount = title.length;
  const bodyCount = narrative.length;
  const canSubmit = Boolean(title.trim() && narrative.trim());

  const persistDraft = useCallback(() => {
    try {
      localStorage.setItem('narrative_draft_title', title);
      localStorage.setItem('narrative_draft_source', sourceType);
      localStorage.setItem('narrative_draft_body', narrative);
    } catch { /* 存储失败不阻断 */ }
  }, [title, sourceType, narrative]);

  const handleSaveDraft = useCallback(() => {
    if (!title.trim() && !narrative.trim()) {
      showToast({ title: '请先输入内容', icon: 'none' });
      return;
    }
    persistDraft();
    showToast({ title: '草稿已保存', icon: 'success' });
  }, [title, narrative, persistDraft]);

  const clearDraft = useCallback(() => {
    try {
      localStorage.removeItem('narrative_draft_title');
      localStorage.removeItem('narrative_draft_source');
      localStorage.removeItem('narrative_draft_body');
    } catch { /* 清理失败不阻断 */ }
  }, []);

  const triggerExtraction = useCallback(async (narrativeId: string) => {
    setExtracting(true);
    try {
      // 火后不理：触发后台提取后立即跳转结果页，不等待 LLM 完成
      await extractNarrative(narrativeId);
    } catch (err) {
      // 即使提取触发失败也跳转，结果页会轮询真实状态；
      // 但如果是可识别的错误，给用户一个提示。
      const message = getErrorMessage(err, '提取启动失败');
      if (message && message !== '提取启动失败') {
        showToast({ title: `提取启动异常：${message}`, icon: 'none' });
      }
    }
    setSubmitting(false);
    setExtracting(false);
    navigate(`/cases/extraction/${narrativeId}`, { replace: true });
  }, [navigate]);

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const res = await createNarrative({ title, narrative, source_type: sourceType });
      const narrativeId = res.narrative_id;
      console.debug('[narrative-submit] created narrativeId:', narrativeId);
      clearDraft();
      await triggerExtraction(narrativeId);
    } catch (err) {
      const message = getErrorMessage(err, '提交失败');
      showToast({ title: message, icon: 'none' });
      setSubmitting(false);
    }
  }, [canSubmit, title, narrative, sourceType, clearDraft, triggerExtraction]);

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
