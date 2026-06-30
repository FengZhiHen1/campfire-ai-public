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
  tags?: string[];
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
  extraction_status: string;
  extraction_error: string | null;
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

