/**
 * PROF-07 Zustand ProfileStore — 档案数据状态管理
 *
 * 管理：档案列表缓存、详情缓存、加载/提交状态、变更监听器。
 * 会话级缓存（页面关闭即清空），不持久化到 Taro Storage。
 *
 * 数据来源:
 *   - profileApi: MUST — HTTP 响应数据
 *   - useAuth.sessionState: MUST — 认证状态校验
 * 边界:
 *   - 依赖: ../types, ../services/profileApi
 *   - 被依赖: hooks/useProfile.ts, coordination/profileCoordination.ts
 * 禁止行为:
 *   - 禁止在 Store 中发起 HTTP 请求——那是 API 层和 Hook 层的职责
 *   - 禁止持久化到 localStorage——档案数据为会话级缓存
 */

import { create } from 'zustand';
import type {
  ProfileListItem,
  ProfileResponse,
} from '../types';
import type { ProfileListState, ProfileSubmitState } from '../types';

// ============================================================================
// 变更监听器
// ============================================================================

type ChangeListener = (profileId: string) => void;

// ============================================================================
// Store 接口
// ============================================================================

export interface ProfileStoreState {
  /** 档案列表 */
  list: ProfileListItem[];
  /** 列表加载状态 */
  listState: ProfileListState;
  /** 当前查看的档案详情（会话级缓存） */
  currentDetail: ProfileResponse | null;
  /** 最近错误 */
  error: Error | null;
  /** 提交状态 */
  submitState: ProfileSubmitState;
  /** 变更监听器（不通过 React 订阅，仅通过 getState() 操作） */
  changeListeners: Set<ChangeListener>;
}

export interface ProfileStoreActions {
  // 列表
  setList: (list: ProfileListItem[]) => void;
  addToList: (profile: ProfileResponse) => void;
  removeFromList: (profileId: string) => void;
  updateInList: (profileId: string, updates: Partial<ProfileListItem>) => void;
  setListState: (state: ProfileListState) => void;

  // 详情
  setCurrentDetail: (detail: ProfileResponse | null) => void;

  // 错误
  setError: (error: Error | null) => void;
  clearError: () => void;

  // 提交
  setSubmitState: (state: ProfileSubmitState) => void;

  // 变更监听器
  addChangeListener: (listener: ChangeListener) => void;
  removeChangeListener: (listener: ChangeListener) => void;
  notifyChangeListeners: (profileId: string) => void;
}

export type ProfileStore = ProfileStoreState & ProfileStoreActions;

// ============================================================================
// Store 创建
// ============================================================================

export const useProfileStore = create<ProfileStore>()((set, get) => ({
  // --- 初始状态 ---
  list: [],
  listState: 'idle',
  currentDetail: null,
  error: null,
  submitState: 'idle',
  changeListeners: new Set<ChangeListener>(),

  // --- 列表操作 ---

  setList: (list: ProfileListItem[]): void => {
    set({ list });
  },

  addToList: (profile: ProfileResponse): void => {
    const item: ProfileListItem = {
      profile_id: profile.profile_id,
      nickname: profile.nickname,
      birth_date: profile.birth_date,
      age_range: profile.age_range,
      diagnosis_type: profile.diagnosis_type,
      primary_behavior: profile.primary_behavior,
      is_default: profile.is_default,
      event_count: profile.event_count,
      consult_count: profile.consult_count,
    };
    set((state) => ({
      list: [...state.list, item],
    }));
  },

  removeFromList: (profileId: string): void => {
    set((state) => ({
      list: state.list.filter((p) => p.profile_id !== profileId),
    }));
  },

  updateInList: (profileId: string, updates: Partial<ProfileListItem>): void => {
    set((state) => ({
      list: state.list.map((p) =>
        p.profile_id === profileId ? { ...p, ...updates } : p,
      ),
    }));
  },

  setListState: (listState: ProfileListState): void => {
    set({ listState });
  },

  // --- 详情 ---

  setCurrentDetail: (detail: ProfileResponse | null): void => {
    set({ currentDetail: detail });
  },

  // --- 错误 ---

  setError: (error: Error | null): void => {
    set({ error });
  },

  clearError: (): void => {
    set({ error: null });
  },

  // --- 提交 ---

  setSubmitState: (submitState: ProfileSubmitState): void => {
    set({ submitState });
  },

  // --- 变更监听器 ---

  addChangeListener: (listener: ChangeListener): void => {
    const { changeListeners } = get();
    changeListeners.add(listener);
  },

  removeChangeListener: (listener: ChangeListener): void => {
    const { changeListeners } = get();
    changeListeners.delete(listener);
  },

  notifyChangeListeners: (profileId: string): void => {
    const { changeListeners } = get();
    changeListeners.forEach((fn) => {
      try {
        fn(profileId);
      } catch {
        // 回调异常不阻断通知链
      }
    });
  },
}));
