/**
 * PROF-07 ProfileCoordination — CSLT-08 横向协作实现
 *
 * 为 CSLT-08 提供三个协作接口：
 * - checkProfileExists: 冷启动检测
 * - triggerMicroSurvey: 微问卷触发
 * - onProfileChanged: 档案变更订阅
 *
 * 数据来源:
 *   - profileStore: MUST — 档案列表缓存
 *   - profileApi: MUST — 实时档案查询
 *   - useMicroSurveyStore: MUST — 微问卷状态
 * 边界:
 *   - 依赖: ../store/profileStore, ../store/microSurveyStore, ../services/profileApi
 *   - 被依赖: ../index.ts (re-export), CSLT-08
 * 禁止行为:
 *   - 禁止在 coordination 层中操作 DOM 或调用 Taro.navigateTo
 *   - 禁止绕过 store 直接读写状态
 */

import { useSessionStore } from '../../shared/store/userStore';
import { useProfileStore } from '../store/profileStore';
import { useMicroSurveyStore } from '../store/microSurveyStore';
import * as profileApi from '../services/profileApi';
import { DEFAULT_QUESTIONS } from '../constants';
import type { ProfileCoordination } from '../types';

// ============================================================================
// 模块作用域：微问卷去重 Set
// ============================================================================

const displayedConsultationIds = new Set<string>();

function hasBeenDisplayed(consultationId: string): boolean {
  return displayedConsultationIds.has(consultationId);
}

function markAsDisplayed(consultationId: string): void {
  displayedConsultationIds.add(consultationId);
}

// ============================================================================
// ProfileCoordination 实例
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
    if (hasBeenDisplayed(consultationId)) {
      return;
    }

    markAsDisplayed(consultationId);
    const microStore = useMicroSurveyStore.getState();
    microStore.setQuestions([...DEFAULT_QUESTIONS]);
    microStore.setState('showing');
  },

  /**
   * 档案变更订阅：注册回调，返回 unsubscribe 函数。
   */
  onProfileChanged(callback: (profileId: string) => void): () => void {
    const store = useProfileStore.getState();
    store.addChangeListener(callback);
    return () => {
      store.removeChangeListener(callback);
    };
  },
};
