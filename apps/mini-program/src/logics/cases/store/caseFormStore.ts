/**
 * CASE-01 案例录入管理 — Zustand 表单状态 Store。
 *
 * 集中管理案例录入表单的全部字段状态，支持 setField / resetForm / loadDraft / saveDraft。
 * 自动保存: 30 秒防抖，Taro.Storage 存储最新草稿。
 *
 * 调用路径：
 *   views/ (Props) → caseFormStore (Zustand) → caseApiService (httpClient)
 *
 * 设计依据：
 * - 落地规范 §1.2 前端 Store
 * - 设计文档 §1.1 表单自动保存采用本地存储
 * - 项目结构 §9.4 Hook 作为 L1a-L1b 的唯一桥梁
 */

import Taro from '@tarojs/taro';
import { create } from 'zustand';

/** 草稿存储 Key */
const DRAFT_STORAGE_KEY: string = 'case_form_draft';

/** 自动保存防抖间隔（毫秒） */
const AUTO_SAVE_DEBOUNCE_MS: number = 30000;

// ============================================================================
// 类型定义
// ============================================================================

/** 案例表单所有字段 */
export interface CaseFormFields {
  // L1 字段
  title: string;
  narrative: string;
  source_type: string;
  // L2 字段
  behavior_type: string;
  age_range_min: number;
  age_range_max: number;
  severity: string;
  scene: string;
  ebp_labels: string[];
  family_category: string;
  immediate_action: string;
  comforting_phrase: string;
  observation_metrics: string;
  medical_criteria: string;
  evidence_level: string;
  contraindications: string;
  is_template: boolean;
  // 选填字段
  excluded_population: string;
}

/** 表单校验错误 */
export interface FormErrors {
  [field: string]: string;
}

/** Store 状态与方法 */
export interface CaseFormState {
  // 表单字段
  fields: CaseFormFields;
  // 校验错误
  errors: FormErrors;
  // 提交状态
  isSubmitting: boolean;
  // 自动保存状态
  lastSavedAt: string | null;
  isDirty: boolean;
  // 方法
  setField: (name: keyof CaseFormFields, value: string | number | boolean | string[]) => void;
  setFields: (partial: Partial<CaseFormFields>) => void;
  resetForm: () => void;
  loadDraft: () => boolean;
  saveDraft: () => void;
  setErrors: (errors: FormErrors) => void;
  clearErrors: () => void;
  setSubmitting: (value: boolean) => void;
}

// ============================================================================
// 默认表单字段值
// ============================================================================

const DEFAULT_FIELDS: CaseFormFields = {
  title: '',
  narrative: '',
  source_type: '',
  behavior_type: '',
  age_range_min: 0,
  age_range_max: 0,
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
export const useCaseFormStore = create<CaseFormState>((set, get) => ({
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
   * 设置提交状态。
   */
  setSubmitting: (value) => set({ isSubmitting: value }),
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
    const state = useCaseFormStore.getState();
    if (state.isDirty) {
      state.saveDraft();
    }
    autoSaveTimer = null;
  }, AUTO_SAVE_DEBOUNCE_MS);
}
