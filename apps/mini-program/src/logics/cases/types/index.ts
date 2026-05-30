/**
 * CASE-09 案例管理逻辑 — 类型定义。
 *
 * 本模块的所有类型定义集中管理。
 * CaseFormFields / FormErrors / CaseFormState 字段对齐 CASE-01 契约（CaseCreateRequest.json）。
 * NarrativeListItem / NarrativeDetail / CardSummary 原散落在 narrativeApi.ts，现已归并。
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
  title: string;
  narrative: string;
  source_type: string;
  author_id: string;
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
  fields: CaseFormFields;
  errors: FormErrors;
  isSubmitting: boolean;
  lastSavedAt: string | null;
  isDirty: boolean;
  setField: (name: keyof CaseFormFields, value: string | number | boolean | string[] | [number, number]) => void;
  setFields: (partial: Partial<CaseFormFields>) => void;
  resetForm: () => void;
  loadDraft: () => boolean;
  saveDraft: () => void;
  setErrors: (errors: FormErrors) => void;
  clearErrors: () => void;
  setSubmitting: (value: boolean) => void;
}

// ============================================================================
// 叙事相关类型（原在 narrativeApi.ts 内联定义，现归并于此）
// ============================================================================

/** 叙事列表项 */
export interface NarrativeListItem {
  narrative_id: string;
  title: string;
  source_type: string;
  author_id: string;
  status: string;
  card_count: number;
  created_at: string;
}

/** 叙事详情 */
export interface NarrativeDetail {
  narrative_id: string;
  title: string;
  narrative: string;
  source_type: string;
  author_id: string;
  status: string;
  derived_card_ids: string[] | null;
  cards: CardSummary[];
  created_at: string;
  updated_at: string;
}

/** 关联卡片摘要 */
export interface CardSummary {
  card_id: string;
  title: string;
  behavior_type: string;
  severity: string;
  scene: string;
  review_status: string;
  is_owner?: boolean;
}

