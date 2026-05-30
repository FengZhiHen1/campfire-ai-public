/**
 * PROF-07 Zustand MicroSurveyStore — 微问卷状态管理
 *
 * 管理：微问卷显示状态、题目列表。独立于档案 CRUD 状态。
 * 会话级缓存，不持久化。
 *
 * 数据来源:
 *   - ../constants: MUST — DEFAULT_QUESTIONS 初始值
 * 边界:
 *   - 依赖: ../types (MicroSurveyState), ../constants
 *   - 被依赖: hooks/useMicroSurvey.ts, coordination/profileCoordination.ts
 * 禁止行为:
 *   - 禁止在 Store 中发起 HTTP 请求
 *   - 禁止跨 Store 直接修改 ProfileStore 的状态
 */

import { create } from 'zustand';
import type { MicroSurveyState } from '../types';
import type { MicroSurveyQuestion } from '../types';
import { DEFAULT_QUESTIONS } from '../constants';

// ============================================================================
// Store 接口
// ============================================================================

export interface MicroSurveyStoreState {
  state: MicroSurveyState;
  questions: MicroSurveyQuestion[];
}

export interface MicroSurveyStoreActions {
  setState: (state: MicroSurveyState) => void;
  setQuestions: (questions: MicroSurveyQuestion[]) => void;
  /** 重置为初始状态（隐藏 + 默认题目） */
  reset: () => void;
}

export type MicroSurveyStore = MicroSurveyStoreState & MicroSurveyStoreActions;

// ============================================================================
// 初始状态
// ============================================================================

const initialState: MicroSurveyStoreState = {
  state: 'hidden',
  questions: DEFAULT_QUESTIONS,
};

// ============================================================================
// Store 创建
// ============================================================================

export const useMicroSurveyStore = create<MicroSurveyStore>()((set) => ({
  ...initialState,

  setState: (state: MicroSurveyState): void => {
    set({ state });
  },

  setQuestions: (questions: MicroSurveyQuestion[]): void => {
    set({ questions });
  },

  reset: (): void => {
    set(initialState);
  },
}));
