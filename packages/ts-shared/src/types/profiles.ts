/** PROF-01 档案管理 — 前端接口类型定义 */

/** 档案创建请求 */
export interface ProfileCreate {
  nickname?: string | null;
  birth_date: string;           // YYYY-MM-DD
  diagnosis_type: string;       // DiagnosisType 枚举值
  primary_behavior: string;     // ProfileBehaviorType 枚举值
  language_level?: string | null;
  sensory_features?: string[];
  triggers?: string[];
  medication_notes?: string | null;
}

/** 档案更新请求（Merge Patch，全部字段可选） */
export interface ProfileUpdate {
  nickname?: string | null;
  birth_date?: string;
  diagnosis_type?: string;
  primary_behavior?: string;
  language_level?: string | null;
  sensory_features?: string[];
  triggers?: string[];
  medication_notes?: string | null;
}

/** 档案详情响应 */
export interface ProfileResponse {
  profile_id: string;
  nickname: string | null;
  birth_date: string;
  age_range: string;            // 服务端实时计算
  diagnosis_type: string;
  primary_behavior: string;
  language_level: string | null;
  sensory_features: string[];
  triggers: string[];
  medication_notes: string | null;
  is_default: boolean;
  caregiver_id: string;
  created_at: string;           // ISO datetime
  updated_at: string;           // ISO datetime
}

/** 档案列表条目 */
export interface ProfileListItem {
  profile_id: string;
  nickname: string | null;
  age_range: string;
  diagnosis_type: string;
  primary_behavior: string;
  is_default: boolean;
}

/** 事件创建请求（PROF-03 契约，微问卷沉淀时使用） */
export interface EventCreate {
  event_time: string;           // ISO datetime
  behavior_type: string;
  severity_level: string;
  setting?: string | null;
  trigger_description: string;
  manifestation: string;
  intervention_tried: string;
  intervention_result: string;
  tags?: string[] | null;
}

/** 事件更新请求（Merge Patch，全部字段可选） */
export interface EventUpdate {
  event_time?: string;
  behavior_type?: string;
  severity_level?: string;
  setting?: string | null;
  trigger_description?: string;
  manifestation?: string;
  intervention_tried?: string;
  intervention_result?: string;
  tags?: string[] | null;
}

/** 事件详情响应 */
export interface EventResponse {
  event_id: string;
  profile_id: string;
  recorded_by: string;
  recorded_by_role: string;
  event_time: string;           // ISO datetime
  behavior_type: string;
  severity_level: string;
  setting: string | null;
  trigger_description: string;
  manifestation: string;
  intervention_tried: string;
  intervention_result: string;
  is_professional: boolean;
  tags: string[] | null;
  created_at: string;           // ISO datetime
  updated_at: string;           // ISO datetime
}

/** 事件列表条目 */
export interface EventListItem {
  event_id: string;
  event_time: string;           // ISO datetime
  behavior_type: string;
  severity_level: string;
  has_professional_note: boolean;
  created_at: string;           // ISO datetime
}
