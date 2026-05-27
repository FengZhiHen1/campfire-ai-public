/** CASE-01 案例录入管理 — 前端接口类型定义 */

/** 附件引用结构 */
export interface AttachmentRef {
  file_name: string;
  minio_path: string;
  file_type: string;
  file_size: number;
  uploaded_at: string; // ISO datetime
  sort_order: number;
}

/** PII 单条警告 */
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

/** 案例创建请求 */
export interface CaseCreateRequest {
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
  excluded_population?: string;
  attachment_refs?: AttachmentRef[];
}

/** 案例更新请求（部分更新 + 乐观锁） */
export interface CaseUpdate {
  title?: string;
  narrative?: string;
  source_type?: string;
  behavior_type?: string;
  age_range?: [number, number];
  severity?: string;
  scene?: string;
  ebp_labels?: string[];
  family_category?: string;
  immediate_action?: string;
  comforting_phrase?: string;
  observation_metrics?: string;
  medical_criteria?: string;
  evidence_level?: string;
  contraindications?: string;
  is_template?: boolean;
  excluded_population?: string;
  attachment_refs?: AttachmentRef[];
  updated_at: string; // ISO datetime, 必填(乐观锁)
}

/** 案例详情响应 */
export interface CaseResponse {
  case_id: string;
  status: string;
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
  excluded_population?: string;
  attachment_refs?: AttachmentRef[];
  review_comment?: string;
  created_at: string; // ISO datetime
  updated_at: string; // ISO datetime
  pii_warnings?: PiiWarning[];
  ebp_inconsistency_warning?: string;
}

/** 案例列表条目 */
export interface CaseListItem {
  case_id: string;
  title: string;
  status: string;
  source_type: string;
  behavior_type: string;
  severity: string;
  scene: string;
  author_id: string;
  is_template: boolean;
  created_at: string; // ISO datetime
  updated_at: string; // ISO datetime
}

/** 泛型分页响应 */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}
