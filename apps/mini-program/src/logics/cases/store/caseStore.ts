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

import Taro from '@tarojs/taro';
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
// 自动保存防抖 Timer
// ============================================================================

let autoSaveTimer: ReturnType<typeof setTimeout> | null = null;

// ============================================================================
// Store
// ============================================================================

/**
 * 案例表单 Store。
 * 管理所有表单字段、校验错误和自动保存状态。
 */
export const useCaseStore = create<CaseFormState>((set, get) => ({
  fields: { ...DEFAULT_FIELDS },
  errors: {},
  isSubmitting: false,
  lastSavedAt: null,
  isDirty: false,

  /**
   * 更新单个字段值，标记 dirty 并触发防抖自动保存。
   */
  setField: (name, value) => {
    set((state) => ({
      fields: { ...state.fields, [name]: value },
      isDirty: true,
    }));
    scheduleAutoSave();
  },

  /**
   * 批量更新字段值。
   */
  setFields: (partial) => {
    set((state) => ({
      fields: { ...state.fields, ...partial },
      isDirty: true,
    }));
    scheduleAutoSave();
  },

  /**
   * 重置表单为默认值。
   */
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
    Taro.removeStorageSync(DRAFT_STORAGE_KEY);
  },

  /**
   * 从本地存储加载草稿。
   *
   * @returns 是否存在草稿
   */
  loadDraft: (): boolean => {
    try {
      const saved: string | null = Taro.getStorageSync(DRAFT_STORAGE_KEY);
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

  /**
   * 将当前字段保存到本地存储。
   */
  saveDraft: () => {
    const { fields } = get();
    try {
      Taro.setStorageSync(DRAFT_STORAGE_KEY, JSON.stringify(fields));
      set({ lastSavedAt: new Date().toISOString(), isDirty: false });
    } catch {
      // 存储失败不阻断主流程
    }
  },

  /**
   * 设置校验错误。
   */
  setErrors: (errors) => set({ errors }),

  /**
   * 清除校验错误。
   */
  clearErrors: () => set({ errors: {} }),

  /**
   * 设置提交状态（防重入保护）。
   * 重复调用 setSubmitting(true) 在 isSubmitting 已为 true 时无操作。
   */
  setSubmitting: (value) => {
    if (get().isSubmitting === value) return;
    set({ isSubmitting: value });
  },
}));

// ============================================================================
// 自动保存调度
// ============================================================================

/**
 * 调度自动保存（30 秒防抖）。
 * 每次字段变更时调用，重置 30 秒计时器。
 * 30 秒无变更后自动保存到 Taro.Storage。
 */
function scheduleAutoSave(): void {
  if (autoSaveTimer !== null) {
    clearTimeout(autoSaveTimer);
  }
  autoSaveTimer = setTimeout(() => {
    const state = useCaseStore.getState();
    if (state.isDirty) {
      state.saveDraft();
    }
    autoSaveTimer = null;
  }, AUTO_SAVE_DEBOUNCE_MS);
}
