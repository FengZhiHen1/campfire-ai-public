/**
 * PROF-07 档案数据逻辑 — 模块入口
 *
 * 本文件仅为 re-export 层。所有实现分布在：
 * - coordination/profileCoordination.ts — CSLT-08 横向协作
 * - hooks/useProfile.ts — 档案数据 Hook
 * - hooks/useMicroSurvey.ts — 微问卷 Hook
 * - store/profileStore.ts — 档案 CRUD 状态
 * - store/microSurveyStore.ts — 微问卷状态
 * - services/profileApi.ts — 档案 HTTP API
 * - services/eventApi.ts — 事件 HTTP API
 * - constants.ts — 静态配置
 * - types/ — 类型定义
 */

// Hook 导出（PROF-06 views 层消费）
export { useProfile } from './hooks/useProfile';
export { useMicroSurvey } from './hooks/useMicroSurvey';

// Coordination 导出（CSLT-08 消费）
export { profileCoordination } from './coordination/profileCoordination';

// 常量导出
export {
  DIAGNOSIS_OPTIONS,
  DIAGNOSIS_VALUES,
  BEHAVIOR_OPTIONS,
  BEHAVIOR_VALUES,
  LANGUAGE_OPTIONS,
  LANGUAGE_VALUES,
  SENSORY_FEATURE_TAGS,
  TRIGGER_TAGS,
  PRESET_TAGS,
  MAX_PROFILE_COUNT,
} from './constants';

// 类型导出
export type {
  UseProfileReturn,
  UseMicroSurveyReturn,
  ProfileCoordination,
  MicroSurveyQuestion,
  MicroSurveyAnswer,
  ColdStartFormData,
  InvalidateCacheRequest,
  ProfileListState,
  ProfileSubmitState,
  MicroSurveyState,
  InterventionFeedback,
  AuthRequiredError,
  NetworkError,
  ServerError,
  ProfileLimitExceededError,
  ProfileConflictError,
  ProfileListItem,
  ProfileResponse,
  ProfileCreate,
  ProfileUpdate,
  EventCreate,
  EventUpdate,
  EventResponse,
  EventListItem,
} from './types';
