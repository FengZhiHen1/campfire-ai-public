/**
 * CASE-09 案例管理逻辑 — Zustand 表单状态 Store。
 *
 * 集中管理案例录入表单的全部字段状态，支持 setField / resetForm / loadDraft / saveDraft。
 * 自动保存: 30 秒防抖，Taro.Storage 存储最新草稿。
 *
 * 调用路径：
 *   views/ → hooks/useCaseFormStore → caseStore (Zustand)
 *
 * 设计依据：
 * - 设计文档 §1.1 表单自动保存采用本地存储
 * - 设计文档 §1.4 状态机设计
 * - 落地规范 §1.2 文件归属
 * - 落地规范 §1.5 步骤组 A：表单管理
 * - 项目结构 §6.1 Hook 作为 L1a-L1b 的唯一桥梁
 */

import { create } from 'zustand';
import type { CaseFormFields, CaseFormState, FormErrors } from '../types';

/** 草稿存储 Key */
const DRAFT_STORAGE_KEY: string = 'case_form_draft';

/** 自动保存防抖间隔（毫秒） */
const AUTO_SAVE_DEBOUNCE_MS: number = 30000;

// ============================================================================
// 默认表单字段值
// ============================================================================

const DEFAULT_FIELDS: CaseFormFields = {
  title: '',
  narrative: '',
  source_type: '',
  author_id: '',
  behavior_type: '',
  age_range: [0, 0],
  severity: '',
  scene: '',
  ebp_labels: [],
  family_category: '',
  immediate_action: '',
  comforting_phrase: '',
  observation_metrics: '',
  medical_criteria: '',
  evidence_level: '',
  contraindications: '',
  is_template: false,
  excluded_population: '',
};

// ============================================================================
// Store
// ============================================================================

export const useCaseStore = create<CaseFormState>((set, get) => {
  let autoSaveTimer: ReturnType<typeof setTimeout> | null = null;

  function scheduleAutoSave(): void {
    if (autoSaveTimer !== null) {
      clearTimeout(autoSaveTimer);
    }
    autoSaveTimer = setTimeout(() => {
      const state = get();
      if (state.isDirty) {
        state.saveDraft();
      }
      autoSaveTimer = null;
    }, AUTO_SAVE_DEBOUNCE_MS);
  }

  return {
    fields: { ...DEFAULT_FIELDS },
    errors: {},
    isSubmitting: false,
    lastSavedAt: null,
    isDirty: false,

    setField: (name, value) => {
      set((state) => ({
        fields: { ...state.fields, [name]: value },
        isDirty: true,
      }));
      scheduleAutoSave();
    },

    setFields: (partial) => {
      set((state) => ({
        fields: { ...state.fields, ...partial },
        isDirty: true,
      }));
      scheduleAutoSave();
    },

    resetForm: () => {
      if (autoSaveTimer !== null) {
        clearTimeout(autoSaveTimer);
        autoSaveTimer = null;
      }
      set({
        fields: { ...DEFAULT_FIELDS },
        errors: {},
        isSubmitting: false,
        lastSavedAt: null,
        isDirty: false,
      });
      localStorage.removeItem(DRAFT_STORAGE_KEY);
    },

    loadDraft: (): boolean => {
      try {
        const saved: string | null = localStorage.getItem(DRAFT_STORAGE_KEY);
        if (saved) {
          const parsed: CaseFormFields = JSON.parse(saved);
          set({
            fields: { ...DEFAULT_FIELDS, ...parsed },
            lastSavedAt: new Date().toISOString(),
            isDirty: false,
          });
          return true;
        }
      } catch {
        // 解析失败则忽略
      }
      return false;
    },

    saveDraft: () => {
      const { fields } = get();
      try {
        localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(fields));
        set({ lastSavedAt: new Date().toISOString(), isDirty: false });
      } catch {
        // 存储失败不阻断主流程
      }
    },

    setErrors: (errors) => set({ errors }),

    clearErrors: () => set({ errors: {} }),

    setSubmitting: (value) => {
      if (get().isSubmitting === value) return;
      set({ isSubmitting: value });
    },
  };
});
