/**
 * 模块: @campfire/ts-shared.profiles.types
 * 职责: 档案管理域的前端接口类型定义——档案 CRUD 与事件记录的请求/响应 DTO。
 *       与后端 py-schemas 中的 PROF 模块对齐。
 * 数据来源:
 *   - py-schemas (profiles): MUST — 后端 Pydantic profile_schemas
 *   - PROF-01/PROF-03 设计文档: SHOULD — 字段语义
 * 边界:
 *   - 依赖: profiles.enums.ts（枚举类型引用）
 *   - 被依赖: mini-program（通过 @campfire/ts-shared 导入）
 * 禁止行为:
 *   - 禁止包含运行时逻辑
 *   - 禁止使用 any 类型
 *   - 禁止字段名与后端不一致
 */

import type { DiagnosisType, LanguageLevel, SensoryFeature, AgeRange, ProfileBehaviorType } from './profiles.enums';

// === 档案 CRUD ===

/** 档案创建请求 */
export interface ProfileCreate {
  nickname?: string | null;
  birth_date: string;              // YYYY-MM-DD
  diagnosis_type: DiagnosisType;
  primary_behavior: ProfileBehaviorType;
  language_level?: LanguageLevel | null;
  sensory_features?: SensoryFeature[];
  triggers?: string[];             // Trigger 枚举值或自定义文本
  medication_notes?: string | null;
}

/** 档案更新请求——Merge Patch，全部字段可选 */
export interface ProfileUpdate {
  nickname?: string | null;
  birth_date?: string;
  diagnosis_type?: DiagnosisType;
  primary_behavior?: ProfileBehaviorType;
  language_level?: LanguageLevel | null;
  sensory_features?: SensoryFeature[];
  triggers?: string[];             // Trigger 枚举值或自定义文本
  medication_notes?: string | null;
}

/** 档案详情响应 */
export interface ProfileResponse {
  profile_id: string;
  nickname: string | null;
  birth_date: string;
  age_range: AgeRange;             // 服务端实时计算
  diagnosis_type: DiagnosisType;
  primary_behavior: ProfileBehaviorType;
  language_level: LanguageLevel | null;
  sensory_features: SensoryFeature[];
  triggers: string[];              // Trigger 枚举值或自定义文本（后端返回中文）
  medication_notes: string | null;
  is_default: boolean;
  caregiver_id: string;
  created_at: string;              // ISO 8601 datetime
  updated_at: string;              // ISO 8601 datetime
  /** 关联事件记录数量（首页统计展示，可选） */
  event_count?: number;
  /** 关联咨询记录数量（首页统计展示，可选） */
  consult_count?: number;
}

/** 档案列表条目 */
export interface ProfileListItem {
  profile_id: string;
  nickname: string | null;
  birth_date?: string;              // YYYY-MM-DD（列表展示出生日期，可选）
  age_range: AgeRange;
  diagnosis_type: DiagnosisType;
  primary_behavior: ProfileBehaviorType;
  is_default: boolean;
  /** 关联事件记录数量（首页统计展示，可选） */
  event_count?: number;
  /** 关联咨询记录数量（首页统计展示，可选） */
  consult_count?: number;
}

// === 事件记录 ===

/** 事件创建请求 */
export interface EventCreate {
  event_time: string;              // ISO 8601 datetime
  behavior_type: string;
  severity_level: string;
  setting?: string | null;
  trigger_description: string;
  manifestation: string;
  intervention_tried: string;
  intervention_result: string;
  tags?: string[] | null;
}

/** 事件更新请求——Merge Patch */
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
  event_time: string;              // ISO 8601 datetime
  behavior_type: string;
  severity_level: string;
  setting: string | null;
  trigger_description: string;
  manifestation: string;
  intervention_tried: string;
  intervention_result: string;
  is_professional: boolean;
  tags: string[] | null;
  created_at: string;              // ISO 8601 datetime
  updated_at: string;              // ISO 8601 datetime
}

/** 事件列表条目 */
export interface EventListItem {
  event_id: string;
  event_time: string;              // ISO 8601 datetime
  behavior_type: string;
  severity_level: string;
  setting?: string | null;
  trigger_description?: string;
  manifestation?: string;
  intervention_tried?: string;
  intervention_result?: string;
  has_professional_note: boolean;
  created_at: string;              // ISO 8601 datetime
}
