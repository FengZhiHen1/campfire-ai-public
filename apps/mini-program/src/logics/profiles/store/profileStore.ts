/**
 * PROF-07 Zustand ProfileStore — 档案数据状态管理
 *
 * 管理：档案列表缓存、详情缓存、加载/提交状态、微问卷状态、变更监听器。
 * 会话级缓存（页面关闭即清空），不持久化到 Taro Storage。
 */

import { create } from 'zustand';
import type {
  ProfileListItem,
  ProfileResponse,
} from '../types';

import {
  type ProfileListState,
  type ProfileSubmitState,
  type MicroSurveyState,
  type MicroSurveyQuestion,
} from '../types';

// ============================================================================
// 微问卷题目常量
// ============================================================================

const INTERVENTION_FEEDBACK_OPTIONS: string[] = ['有帮助', '一般', '无帮助'];

const DEFAULT_QUESTIONS: MicroSurveyQuestion[] = [
  {
    id: 'trigger',
    text: '本次触发了什么因素？',
    type: 'single-choice-with-custom',
  },
  {
    id: 'effectiveness',
    text: '刚才的建议是否有帮助？',
    type: 'single-choice',
    options: INTERVENTION_FEEDBACK_OPTIONS,
  },
];

// ============================================================================
// 变更监听器类型
// ============================================================================

type ChangeListener = (profileId: string) => void;

// ============================================================================
// Store 接口
// ============================================================================

export interface ProfileStoreState {
  // 档案列表
  list: ProfileListItem[];
  listState: ProfileListState;

  // 当前查看的档案详情（会话级缓存）
  currentDetail: ProfileResponse | null;

  // 最近错误
  error: Error | null;

  // 提交状态
  submitState: ProfileSubmitState;

  // 微问卷
  microSurvey: {
    state: MicroSurveyState;
    questions: MicroSurveyQuestion[];
  };

  // 变更监听器（模块作用域，不通过 React 订阅）
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

  // 微问卷
  setMicroSurveyState: (state: MicroSurveyState) => void;
  setMicroSurveyQuestions: (questions: MicroSurveyQuestion[]) => void;

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
  microSurvey: {
    state: 'hidden',
    questions: DEFAULT_QUESTIONS,
  },
  changeListeners: new Set<ChangeListener>(),

  // --- 列表操作 ---

  setList: (list: ProfileListItem[]): void => {
    set({ list });
  },

  addToList: (profile: ProfileResponse): void => {
    const item: ProfileListItem = {
      profile_id: profile.profile_id,
      nickname: profile.nickname,
      age_range: profile.age_range,
      diagnosis_type: profile.diagnosis_type,
      primary_behavior: profile.primary_behavior,
      is_default: profile.is_default,
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

  // --- 微问卷 ---

  setMicroSurveyState: (state: MicroSurveyState): void => {
    set((prev) => ({
      microSurvey: { ...prev.microSurvey, state },
    }));
  },

  setMicroSurveyQuestions: (questions: MicroSurveyQuestion[]): void => {
    set((prev) => ({
      microSurvey: { ...prev.microSurvey, questions },
    }));
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
