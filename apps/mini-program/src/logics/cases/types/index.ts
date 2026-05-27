/**
 * CASE-09 案例管理逻辑 — 内部类型定义。
 *
 * 本模块的内部类型（CaseFormFields、FormErrors、CaseFormState）
 * 字段名和类型与 CASE-01 契约（CaseCreateRequest.json）的 properties 对齐。
 *
 * 设计依据：
 * - 设计文档 §1.1 技术实现思路
 * - 落地规范 §1.3 输入定义
 * - 契约文件 docs/contracts/CASE-01/CaseCreateRequest.json
 */

// ============================================================================
// CaseFormFields — 表单字段（与 CaseCreateRequest 契约对齐）
// ============================================================================

/** 案例表单所有字段 */
export interface CaseFormFields {
  // L1 字段
  title: string;
  narrative: string;
  source_type: string;
  author_id: string;
  // L2 字段
  behavior_type: string;
  age_range: [number, number];
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

// ============================================================================
// FormErrors — 校验错误映射
// ============================================================================

/** 表单校验错误（字段名 → 错误描述） */
export interface FormErrors {
  [field: string]: string;
}

// ============================================================================
// CaseFormState — Store 状态与方法
// ============================================================================

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
  setField: (name: keyof CaseFormFields, value: string | number | boolean | string[] | [number, number]) => void;
  setFields: (partial: Partial<CaseFormFields>) => void;
  resetForm: () => void;
  loadDraft: () => boolean;
  saveDraft: () => void;
  setErrors: (errors: FormErrors) => void;
  clearErrors: () => void;
  setSubmitting: (value: boolean) => void;
}
