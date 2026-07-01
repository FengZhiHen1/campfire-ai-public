/**
 * PROF-07 档案数据逻辑 — 对外接口契约
 *
 * 本文件定义模块对外暴露的三个公共接口。
 * 消费方只能通过这些接口与模块交互，禁止直接访问 store 或 API 层。
 *
 * 数据来源:
 *   - PROF-07 落地规范 §1.3, §1.4: MUST — 接口签名
 *   - PROF-01 契约: MUST — ProfileListItem, ProfileResponse, ProfileCreate, ProfileUpdate 类型
 * 边界:
 *   - 依赖: types/state.ts, @campfire/ts-shared
 *   - 被依赖: PROF-06 (views/profiles/), CSLT-08 (logics/consult/)
 * 禁止行为:
 *   - 禁止在接口中添加未在落地规范中声明的字段
 *   - 禁止 consumer 绕过这些接口直接访问 store 或 API
 */

import type {
  ProfileListItem,
  ProfileResponse,
  ProfileCreate,
  ProfileUpdate,
} from '@campfire/ts-shared';
import type {
  MicroSurveyState,
} from './state';

// ============================================================================
// UseProfileReturn — PROF-06 views 层消费的档案数据 Hook 返回值
// ============================================================================

export interface UseProfileReturn {
  /** 当前家属账号下的档案列表，可能为空数组 */
  profiles: ProfileListItem[];
  /** 列表是否正在加载中 */
  isLoading: boolean;
  /** 最近一次操作失败的错误，成功时为 null */
  error: Error | null;

  /** 获取档案列表（SWR 策略）。loading 期间重复调用被忽略。 */
  fetchProfiles: () => Promise<void>;
  /** 获取单个档案详情 */
  getProfile: (profileId: string) => Promise<ProfileResponse>;
  /** 创建档案（冷启动引导 / 手动创建） */
  createProfile: (data: ProfileCreate) => Promise<ProfileResponse>;
  /** 更新档案（Merge Patch），仅传入修改的字段 */
  updateProfile: (profileId: string, data: Partial<ProfileUpdate>) => Promise<ProfileResponse>;
  /** 删除档案 */
  deleteProfile: (profileId: string) => Promise<void>;
  /** 设为默认档案 */
  setDefault: (profileId: string) => Promise<void>;
}

// ============================================================================
// UseMicroSurveyReturn — PROF-06 微问卷浮层组件消费的 Hook 返回值
// ============================================================================

/** 微问卷题目定义 */
export interface MicroSurveyQuestion {
  id: string;
  text: string;
  type: 'single-choice' | 'single-choice-with-custom';
  options?: string[];
}

/** 微问卷回答 */
export interface MicroSurveyAnswer {
  consultationId: string;
  triggerFactor?: string;
  interventionFeedback?: string;
}

export interface UseMicroSurveyReturn {
  /** 当前微问卷状态 */
  state: MicroSurveyState;
  /** 当前会话的题目列表 */
  questions: MicroSurveyQuestion[];
  /** 提交回答。失败时回退到 showing 状态，保留用户选择。 */
  submit: (answer: MicroSurveyAnswer) => Promise<void>;
  /** 跳过微问卷，关闭浮层。同 consultation 不会再次弹出（trigger 时已标记去重）。 */
  skip: () => void;
}

// ============================================================================
// ProfileCoordination — CSLT-08 横向协作接口
// ============================================================================

/**
 * CSLT-08 与 PROF-07 的横向协作约定。
 * CSLT-08 通过 ES Module import 导入此接口的唯一实例。
 */
export interface ProfileCoordination {
  /**
   * 冷启动检测：查询当前账号是否已有档案。
   * 优先读取 Store 缓存，缓存为空时发起 HTTP 请求。
   * 网络失败时返回 false（安全默认——无档案则弹出引导）。
   */
  checkProfileExists(): Promise<boolean>;

  /**
   * 微问卷触发：CSLT-08 SSE COMPLETE 后调用。
   * 同一 consultationId 仅触发一次（内存 Set 去重）。
   */
  triggerMicroSurvey(consultationId: string): void;

  /**
   * 档案变更订阅：注册回调，返回 unsubscribe 函数。
   * CSLT-08 可订阅档案变更事件以刷新编排上下文。
   */
  onProfileChanged(callback: (profileId: string) => void): () => void;
}

// ============================================================================
// 内部类型
// ============================================================================

/** 冷启动表单数据 */
export interface ColdStartFormData {
  birth_date: string;
  diagnosis_type: string;
  primary_behavior: string;
}

/** PROF-02 缓存失效通知请求体（依赖缺口 GAP-01） */
export interface InvalidateCacheRequest {
  profileId: string;
  changedFields: string[];
}
