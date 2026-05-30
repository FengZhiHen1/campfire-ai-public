/**
 * PROF-07 档案数据逻辑 — 模块类型定义入口
 *
 * 本文件仅为 re-export 层。所有类型定义分布在：
 * - errors.ts — 业务错误类
 * - state.ts — 前端交互态联合类型
 * - contracts.ts — 对外接口契约
 * - @campfire/ts-shared — 跨模块共享类型
 */

// 错误类
export {
  AuthRequiredError,
  NetworkError,
  ServerError,
  ProfileLimitExceededError,
  ProfileConflictError,
} from './errors';

// 状态类型
export type {
  ProfileListState,
  ProfileSubmitState,
  MicroSurveyState,
  InterventionFeedback,
} from './state';

// 接口契约
export type {
  UseProfileReturn,
  UseMicroSurveyReturn,
  ProfileCoordination,
  MicroSurveyQuestion,
  MicroSurveyAnswer,
  ColdStartFormData,
  InvalidateCacheRequest,
} from './contracts';

// 跨模块共享类型（从 ts-shared 透明传递）
export type {
  ProfileListItem,
  ProfileResponse,
  ProfileCreate,
  ProfileUpdate,
  EventCreate,
  EventUpdate,
  EventResponse,
  EventListItem,
} from '@campfire/ts-shared';
