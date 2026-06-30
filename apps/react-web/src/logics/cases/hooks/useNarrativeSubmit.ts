/**
 * CASE-09 案例管理逻辑 — 叙事提交页 Hook。
 *
 * 封装 NarrativeSubmit 页面的全部业务逻辑：表单状态、来源类型选择、
 * 叙事草稿保存（后端持久化）+ AI 提取流程。View 层仅负责 JSX 渲染。
 *
 * 调用路径：views/cases/pages/narrative-submit → useNarrativeSubmit → narrativeApi
 */

import { useState, useCallback, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  createNarrative,
  extractNarrative,
  getNarrative,
  updateNarrative,
} from '../services/narrativeApi';
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
  loadingDraft: boolean;
  submitting: boolean;
  extracting: boolean;
  savingDraft: boolean;
  draftSaved: boolean;
  tipsExpanded: boolean;
  setTipsExpanded: (v: boolean) => void;
  titleCount: number;
  bodyCount: number;
  canSubmit: boolean;
  handleSaveDraft: () => Promise<void>;
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
  const [searchParams] = useSearchParams();
  const narrativeIdFromUrl = searchParams.get('narrativeId') ?? '';
  const isEditMode = searchParams.get('mode') === 'edit' && Boolean(narrativeIdFromUrl);

  const [title, setTitle] = useState('');
  const [sourceType, setSourceType] = useState('专家撰写');
  const [narrative, setNarrative] = useState('');
  const [loadingDraft, setLoadingDraft] = useState(isEditMode);
  const [submitting, setSubmitting] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);
  const [draftSaved, setDraftSaved] = useState(false);
  const [tipsExpanded, setTipsExpanded] = useState(true);

  // 编辑模式：从后端加载已有草稿
  useEffect(() => {
    if (!isEditMode) {
      setLoadingDraft(false);
      return;
    }
    setLoadingDraft(true);
    getNarrative(narrativeIdFromUrl)
      .then((res) => {
        setTitle(res.title);
        setNarrative(res.narrative);
        setSourceType(res.source_type || '专家撰写');
      })
      .catch((err) => {
        const message = getErrorMessage(err, '加载草稿失败');
        showToast({ title: message, icon: 'none' });
      })
      .finally(() => setLoadingDraft(false));
  }, [isEditMode, narrativeIdFromUrl]);

  const titleCount = title.length;
  const bodyCount = narrative.length;
  const canSubmit = Boolean(title.trim() && narrative.trim());

  const handleSaveDraft = useCallback(async () => {
    if (!title.trim() && !narrative.trim()) {
      showToast({ title: '请先输入内容', icon: 'none' });
      return;
    }
    if (savingDraft) return;
    setSavingDraft(true);
    setDraftSaved(false);
    try {
      if (narrativeIdFromUrl) {
        // 已有草稿：更新后端记录
        await updateNarrative(narrativeIdFromUrl, { title, narrative });
        setDraftSaved(true);
        showToast({ title: '草稿已保存', icon: 'success' });
        window.setTimeout(() => setDraftSaved((v) => (v ? false : v)), 1800);
      } else {
        // 新草稿：创建后端记录，并进入编辑模式
        const res = await createNarrative({ title, narrative, source_type: sourceType });
        const newId = res.narrative_id;
        showToast({ title: '草稿已保存', icon: 'success' });
        navigate(`/cases/narrative?mode=edit&narrativeId=${newId}`, { replace: true });
      }
    } catch (err) {
      const message = getErrorMessage(err, '保存草稿失败');
      showToast({ title: message, icon: 'none' });
    } finally {
      setSavingDraft(false);
    }
  }, [title, narrative, sourceType, narrativeIdFromUrl, savingDraft, navigate]);

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
      let targetNarrativeId = narrativeIdFromUrl;
      if (!targetNarrativeId) {
        // 新草稿：先创建，再提取
        const res = await createNarrative({ title, narrative, source_type: sourceType });
        targetNarrativeId = res.narrative_id;
      } else {
        // 已有草稿：先更新，再提取
        await updateNarrative(targetNarrativeId, { title, narrative });
      }
      await triggerExtraction(targetNarrativeId);
    } catch (err) {
      const message = getErrorMessage(err, '提交失败');
      showToast({ title: message, icon: 'none' });
      setSubmitting(false);
    }
  }, [canSubmit, title, narrative, sourceType, narrativeIdFromUrl, triggerExtraction]);

  return {
    title,
    setTitle,
    sourceType,
    setSourceType,
    narrative,
    setNarrative,
    loadingDraft,
    submitting,
    extracting,
    savingDraft,
    draftSaved,
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
