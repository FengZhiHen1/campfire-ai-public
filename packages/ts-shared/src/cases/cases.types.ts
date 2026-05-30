/**
 * 模块: @campfire/ts-shared.cases.types
 * 职责: 案例管理域的前端接口类型定义——案例创建/更新/查询/审核的请求与响应 DTO。
 *       所有类型与后端 py-schemas 中的 CASE 模块对齐，作为前后端数据契约的前端镜像。
 * 数据来源:
 *   - py-schemas (cases): MUST — 后端 Pydantic case_schemas，字段名、类型、约束与此对齐
 *   - 项目结构.md §6.1: SHOULD — 定义 ts-shared 的边界和职责范围
 * 边界:
 *   - 依赖: 无外部运行时依赖（纯类型定义层）
 *   - 被依赖: apps/mini-program（通过 @campfire/ts-shared 导入类型）
 * 禁止行为:
 *   - 禁止在此文件中包含任何运行时逻辑（函数实现、API 调用、状态管理）
 *   - 禁止使用 any 类型——所有字段必须精确类型化
 *   - 禁止定义与后端 py-schemas 不一致的字段名或类型
 */

import type { CaseStatus, SourceType, BehaviorType, SeverityLevel,
  SceneType, EvidenceLevel, FamilyDisplayCategory } from './cases.enums';

// === 附件与审核 ===

/** 附件引用结构——对应后端 minio 对象存储的文件元数据 */
export interface AttachmentRef {
  file_name: string;
  minio_path: string;
  file_type: string;
  file_size: number;
  uploaded_at: string;   // ISO 8601 datetime
  sort_order: number;
}

/** PII 单条警告——对应后端 PII 检测器的单条命中结果 */
export interface PiiWarning {
  pii_type: string;
  detected_text: string;
  position_start: number;
  position_end: number;
}

/** PII 检测完整结果 */
export interface PiiDetectionResult {
  has_pii: boolean;
  warnings: PiiWarning[];
}

// === 案例 CRUD ===

/** 案例创建请求——MVP 核心字段必填，非核心可选 */
export interface CaseCreateRequest {
  // MVP 核心必填
  title: string;
  behavior_type: BehaviorType;
  severity: SeverityLevel;
  scene: SceneType;
  immediate_action: string;
  comforting_phrase: string;
  observation_metrics: string;
  medical_criteria: string;
  evidence_level: EvidenceLevel;

  // 可选字段
  narrative?: string;
  source_type?: SourceType;
  author_id?: string;
  age_range?: [number, number];  // [min, max]
  ebp_labels?: string[];
  family_category?: FamilyDisplayCategory;
  contraindications?: string;
  is_template?: boolean;
  excluded_population?: string;
  attachment_refs?: AttachmentRef[];
}

/** 案例更新请求——部分更新 + 乐观锁（updated_at 必填） */
export interface CaseUpdate {
  title?: string;
  narrative?: string;
  source_type?: SourceType;
  behavior_type?: BehaviorType;
  age_range?: [number, number];
  severity?: SeverityLevel;
  scene?: SceneType;
  ebp_labels?: string[];
  family_category?: FamilyDisplayCategory;
  immediate_action?: string;
  comforting_phrase?: string;
  observation_metrics?: string;
  medical_criteria?: string;
  evidence_level?: EvidenceLevel;
  contraindications?: string;
  is_template?: boolean;
  excluded_population?: string;
  attachment_refs?: AttachmentRef[];
  updated_at: string;  // ISO 8601 datetime，乐观锁必填
}

/** 案例详情响应 */
export interface CaseResponse {
  case_id: string;
  status: CaseStatus;
  title: string;
  narrative: string;
  source_type: SourceType;
  author_id: string;
  behavior_type: BehaviorType;
  age_range: [number, number];
  severity: SeverityLevel;
  scene: SceneType;
  ebp_labels: string[];
  family_category: FamilyDisplayCategory;
  immediate_action: string;
  comforting_phrase: string;
  observation_metrics: string;
  medical_criteria: string;
  evidence_level: EvidenceLevel;
  contraindications: string;
  is_template: boolean;
  excluded_population?: string;
  attachment_refs?: AttachmentRef[];
  review_comment?: string;
  created_at: string;   // ISO 8601 datetime
  updated_at: string;   // ISO 8601 datetime
  pii_warnings?: PiiWarning[];
  ebp_inconsistency_warning?: string;
  is_owner?: boolean;
}

/** 案例列表条目 */
export interface CaseListItem {
  case_id: string;
  title: string;
  status: CaseStatus;
  source_type: SourceType;
  behavior_type: BehaviorType;
  severity: SeverityLevel;
  scene: SceneType;
  author_id: string;
  is_template: boolean;
  evidence_level: EvidenceLevel;
  age_range: [number, number];  // 修复原 string 类型不一致
  citation_count: number;
  created_at: string;  // ISO 8601 datetime
  updated_at: string;  // ISO 8601 datetime
}

// === 案例审核 ===

/** 审核裁决请求 */
export interface ReviewRequest {
  decision: 'approved' | 'rejected';
  review_comment?: string;
  override_reason?: string;
  pii_override_confirmed?: boolean;
}

/** 单条 AI 预审检查结果 */
export interface CheckItem {
  status: 'pass' | 'fail' | 'annotated';
  details?: string[];
  is_hard_gate: boolean;
}

/** AI 预审结果摘要 */
export interface AiReviewSummary {
  format_check: CheckItem;
  pii_check: CheckItem;
  required_fields_check: CheckItem;
  ebp_consistency_check: CheckItem;
  overall: 'pass' | 'hard_block' | 'annotated';
}

/** 审核裁决响应 */
export interface CaseReviewResponse {
  case_id: string;
  new_status: 'approved' | 'rejected';
  ai_review_summary: AiReviewSummary;
  expert_decision: string;
  review_comment?: string;
  reviewer_id: string;
  reviewed_at: string;  // ISO 8601 datetime
}

/** 待审核队列条目 */
export interface ReviewQueueItem {
  case_id: string;
  title: string;
  author_name: string;
  behavior_type: string;
  submitted_at: string;       // ISO 8601 datetime
  ai_review_overall: string;  // pass | hard_block | annotated
  deadline: string;           // ISO 8601 datetime
  timeout_status: 'normal' | 'warning' | 'overdue';
}
