/**
 * PROF-07 档案数据逻辑 — 模块内部类型定义
 *
 * 共享契约类型（ProfileCreate, ProfileUpdate, ProfileResponse, ProfileListItem,
 * EventCreate）从 @campfire/ts-shared 导入，本文件仅定义模块内部类型。
 */

import type {
  ProfileListItem,
  ProfileResponse,
  ProfileCreate,
  ProfileUpdate,
} from '@campfire/ts-shared';

// 重新导出共享类型，方便 hooks 层统一从 types/index.ts 导入
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

// ============================================================================
// 错误类
// ============================================================================

export class AuthRequiredError extends Error {
  constructor(message = '请先登录') {
    super(message);
    this.name = 'AuthRequiredError';
  }
}

export class NetworkError extends Error {
  constructor(message = '加载失败，请检查网络后重试') {
    super(message);
    this.name = 'NetworkError';
  }
}

export class ServerError extends Error {
  constructor(message = '服务异常，请稍后重试') {
    super(message);
    this.name = 'ServerError';
  }
}

export class ProfileLimitExceededError extends Error {
  constructor(message = '已达到档案数量上限（5个），如需新增请先删除已有档案') {
    super(message);
    this.name = 'ProfileLimitExceededError';
  }
}

export class ProfileConflictError extends Error {
  constructor(message = '档案已被其他设备修改，请刷新后重试') {
    super(message);
    this.name = 'ProfileConflictError';
  }
}

// ============================================================================
// 状态联合类型
// ============================================================================

export type ProfileListState = 'idle' | 'loading' | 'ready' | 'error';
export type ProfileSubmitState = 'idle' | 'submitting' | 'success' | 'error';
export type MicroSurveyState = 'hidden' | 'showing' | 'answering' | 'submitted';
export type InterventionFeedback = '有帮助' | '一般' | '无帮助';

// ============================================================================
// 冷启动表单
// ============================================================================

export interface ColdStartFormData {
  birth_date: string;
  diagnosis_type: string;
  primary_behavior: string;
}

// ============================================================================
// 微问卷
// ============================================================================

export interface MicroSurveyQuestion {
  id: string;
  text: string;
  type: 'single-choice' | 'single-choice-with-custom';
  options?: string[];
}

export interface MicroSurveyAnswer {
  consultationId: string;
  triggerFactor?: string;
  interventionFeedback?: string;
}

// ============================================================================
// 缓存失效
// ============================================================================

export interface InvalidateCacheRequest {
  profileId: string;
  changedFields: string[];
}

// ============================================================================
// ProfileCoordination — CSLT-08 横向协作接口
// ============================================================================

export interface ProfileCoordination {
  checkProfileExists(): Promise<boolean>;
  triggerMicroSurvey(consultationId: string): void;
  onProfileChanged(callback: (profileId: string) => void): () => void;
}

// ============================================================================
// useProfile Hook 返回接口
// ============================================================================

export interface UseProfileReturn {
  profiles: ProfileListItem[];
  isLoading: boolean;
  error: Error | null;

  fetchProfiles: () => Promise<void>;
  getProfile: (profileId: string) => Promise<ProfileResponse>;
  createProfile: (data: ProfileCreate) => Promise<ProfileResponse>;
  updateProfile: (profileId: string, data: Partial<ProfileUpdate>) => Promise<ProfileResponse>;
  deleteProfile: (profileId: string) => Promise<void>;
  setDefault: (profileId: string) => Promise<void>;
}

// ============================================================================
// useMicroSurvey Hook 返回接口
// ============================================================================

export interface UseMicroSurveyReturn {
  state: MicroSurveyState;
  questions: MicroSurveyQuestion[];
  submit: (answer: MicroSurveyAnswer) => Promise<void>;
  skip: () => void;
}
