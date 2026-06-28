/**
 * useMicroSurvey Hook — 微问卷状态管理。
 *
 * 职责：
 * - 管理微问卷弹出/回答/跳过状态
 * - 回答后调用 profileApi.updateProfile() 写入触发因素
 * - 自定义触发因素时通过 eventApi 写入事件记录
 * - 同一 consultationId 仅弹出一次（由 coordination 层去重）
 *
 * 设计依据：PROF-07 落地规范 §1.5 流程 3
 *
 * 数据来源:
 *   - microSurveyStore: MUST — 微问卷显示状态
 *   - profileStore: MUST — 获取当前默认档案
 *   - profileApi: MUST — 标签更新 HTTP 接口
 *   - eventApi: MUST — 事件记录 HTTP 接口
 * 边界:
 *   - 依赖: ../store/microSurveyStore, ../store/profileStore, ../services/profileApi, ../services/eventApi, ../constants
 *   - 被依赖: PROF-06 微问卷浮层组件
 * 禁止行为:
 *   - 禁止直接调用 httpClient——所有 HTTP 请求通过 service 层
 *   - 禁止在 Hook 中操作 DOM 或调用 Taro.navigateTo
 */

import { useCallback, useMemo } from 'react';
import { useProfileStore } from '../store/profileStore';
import { useMicroSurveyStore } from '../store/microSurveyStore';
import * as profileApi from '../services/profileApi';
import * as eventApi from '../services/eventApi';
import { isCustomTrigger, MICRO_SURVEY_AUTO_CLOSE_DELAY } from '../constants';
import type { UseMicroSurveyReturn, MicroSurveyAnswer } from '../types';
import type { EventCreate } from '../types';

// ============================================================================
// useMicroSurvey Hook
// ============================================================================

export function useMicroSurvey(): UseMicroSurveyReturn {
  const state = useMicroSurveyStore((s) => s.state);
  const questions = useMicroSurveyStore((s) => s.questions);

  // ==========================================================================
  // submit — 提交微问卷回答
  // ==========================================================================

  const submit = useCallback(async (answer: MicroSurveyAnswer): Promise<void> => {
    const profileStore = useProfileStore.getState();
    const microStore = useMicroSurveyStore.getState();

    // 获取当前活跃档案（默认档案）
    const defaultProfile = profileStore.list.find((p) => p.is_default) ?? profileStore.list[0];
    if (!defaultProfile) {
      console.warn('[PROF-07] microSurvey submit: no profile available');
      microStore.setState('hidden');
      return;
    }

    const profileId = defaultProfile.profile_id;
    microStore.setState('answering');

    try {
      // 写入触发因素
      if (answer.triggerFactor) {
        const fullProfile = await profileApi.getProfile(profileId);
        const existingTriggers = fullProfile.triggers ?? [];
        if (!existingTriggers.includes(answer.triggerFactor)) {
          const updatedTriggers = [...existingTriggers, answer.triggerFactor];
          await profileApi.updateProfile(profileId, { triggers: updatedTriggers });
        }

        // 自定义触发因素 → 写入事件记录（fire-and-forget）
        if (isCustomTrigger(answer.triggerFactor)) {
          fireAndForgetEvent(profileId, defaultProfile.primary_behavior, answer.triggerFactor);
        }
      }

      // 干预有效性反馈：当前版本仅记录日志
      if (answer.interventionFeedback) {
        console.log('[PROF-07] intervention feedback:', {
          consultationId: answer.consultationId,
          feedback: answer.interventionFeedback,
        });
      }

      microStore.setState('submitted');

      // 自动关闭
      setTimeout(() => {
        useMicroSurveyStore.getState().setState('hidden');
      }, MICRO_SURVEY_AUTO_CLOSE_DELAY);
    } catch {
      // 失败 → 回退到展示状态，保留用户选择
      microStore.setState('showing');
    }
  }, []);

  // ==========================================================================
  // skip — 跳过微问卷
  // ==========================================================================

  const skip = useCallback((): void => {
    useMicroSurveyStore.getState().setState('hidden');
  }, []);

  // ==========================================================================
  // 返回值
  // ==========================================================================

  return useMemo<UseMicroSurveyReturn>(
    () => ({
      state,
      questions,
      submit,
      skip,
    }),
    [state, questions, submit, skip],
  );
}

// ============================================================================
// 内部工具
// ============================================================================

/**
 * Fire-and-forget 事件记录。
 * 仅自定义触发因素时调用，失败不影响主流程。
 */
async function fireAndForgetEvent(
  profileId: string,
  behaviorType: string,
  triggerDescription: string,
): Promise<void> {
  try {
    const eventData: EventCreate = {
      event_time: new Date().toISOString(),
      behavior_type: behaviorType,
      severity_level: '中',
      setting: null,
      trigger_description: triggerDescription,
      manifestation: '（微问卷自动记录）',
      intervention_tried: '（微问卷自动记录）',
      intervention_result: '（微问卷自动记录）',
      tags: null,
    };

    await eventApi.createEvent(profileId, eventData);
  } catch {
    // fire-and-forget：失败不影响主流程
  }
}
