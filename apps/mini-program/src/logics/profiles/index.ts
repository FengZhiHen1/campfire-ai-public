/**
 * PROF-07 档案数据逻辑 — 模块入口
 *
 * 导出：
 * - profileCoordination — CSLT-08 横向协作接口
 * - useProfile — PROF-06 views 层档案数据 Hook
 * - useMicroSurvey — PROF-06 views 层微问卷 Hook
 */

import { useSessionStore } from '../shared/store/userStore';
import { useProfileStore } from './store/profileStore';
import * as profileApi from './services/profileApi';
import { hasBeenDisplayed, markAsDisplayed } from './hooks/useMicroSurvey';

export { useProfile } from './hooks/useProfile';
export { useMicroSurvey } from './hooks/useMicroSurvey';
export type {
  UseProfileReturn,
  UseMicroSurveyReturn,
  ProfileCoordination,
  MicroSurveyState,
  MicroSurveyAnswer,
  ProfileListState,
  ProfileSubmitState,
  ColdStartFormData,
  AuthRequiredError,
  NetworkError,
  ServerError,
  ProfileLimitExceededError,
  ProfileConflictError,
  InterventionFeedback,
} from './types';

import type { ProfileCoordination } from './types';

// ============================================================================
// ProfileCoordination — CSLT-08 横向协作接口
// ============================================================================

export const profileCoordination: ProfileCoordination = {
  /**
   * 冷启动检测：查询当前账号是否已有档案。
   * 优先读取 Store 缓存，缓存为空时发起 HTTP 请求。
   * 网络失败时返回 false（安全默认——无档案则弹出引导）。
   */
  async checkProfileExists(): Promise<boolean> {
    try {
      const sessionState = useSessionStore.getState().sessionState;
      if (sessionState !== 'authenticated') {
        return false;
      }

      const store = useProfileStore.getState();

      // 缓存命中
      if (store.list.length > 0) {
        return true;
      }

      // 缓存为空 → 实时查询
      const data = await profileApi.listProfiles();
      store.setList(data);
      store.setListState('ready');
      return data.length > 0;
    } catch {
      // 网络失败 → 安全默认（无档案）
      return false;
    }
  },

  /**
   * 微问卷触发：CSLT-08 SSE COMPLETE 后调用。
   * 同一 consultationId 仅触发一次（去重）。
   */
  triggerMicroSurvey(consultationId: string): void {
    // 步骤 3.1：去重检查
    if (hasBeenDisplayed(consultationId)) {
      return;
    }

    markAsDisplayed(consultationId);

    // 步骤 3.2：设置显示状态
    const store = useProfileStore.getState();
    store.setMicroSurveyState('showing');
  },

  /**
   * 档案变更订阅：注册回调，返回 unsubscribe 函数。
   * CSLT-08 可订阅档案变更事件以刷新编排上下文。
   */
  onProfileChanged(callback: (profileId: string) => void): () => void {
    const store = useProfileStore.getState();
    store.addChangeListener(callback);
    return () => {
      store.removeChangeListener(callback);
    };
  },
};
