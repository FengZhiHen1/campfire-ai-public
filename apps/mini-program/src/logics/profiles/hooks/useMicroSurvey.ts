/**
 * useMicroSurvey Hook — 微问卷状态管理。
 *
 * 职责：
 * - 管理微问卷弹出/回答/跳过/去重状态
 * - 回答后调用 profileApi.updateProfile() 写入触发因素
 * - 可选调用 PROF-03 EventCreate（自定义触发因素时）
 * - 同一 consultationId 仅弹出一次（模块作用域 Set 去重）
 *
 * 设计依据：PROF-07 落地规范 §1.5 流程 3、§1.6.2
 */

import { useCallback, useMemo } from 'react';
import { useProfileStore } from '../store/profileStore';
import * as profileApi from '../services/profileApi';
import { httpClient } from '../../shared/services/httpClient';
import type { EventCreate } from '../types';
import type { UseMicroSurveyReturn, MicroSurveyAnswer } from '../types';

// ============================================================================
// 模块作用域：去重 Set（页面刷新自然清空）
// ============================================================================

const displayedConsultationIds = new Set<string>();

// ============================================================================
// 触发因素预设枚举值（用于判断是否为自定义文本）
// ============================================================================

const PRESET_TRIGGERS: string[] = [
  '噪音', '环境变化', '陌生人', '任务中断', '社交压力', '感官过载', '身体不适',
];

function isCustomTrigger(value: string): boolean {
  return !PRESET_TRIGGERS.includes(value);
}

// ============================================================================
// useMicroSurvey Hook
// ============================================================================

export function useMicroSurvey(): UseMicroSurveyReturn {
  const state = useProfileStore((s) => s.microSurvey.state);
  const questions = useProfileStore((s) => s.microSurvey.questions);

  // ==========================================================================
  // submit — 提交微问卷回答
  // ==========================================================================

  const submit = useCallback(async (answer: MicroSurveyAnswer): Promise<void> => {
    const store = useProfileStore.getState();

    // 获取当前活跃档案（默认档案）
    const defaultProfile = store.list.find((p) => p.is_default) ?? store.list[0];
    if (!defaultProfile) {
      console.warn('[PROF-07] microSurvey submit: no profile available');
      store.setMicroSurveyState('hidden');
      return;
    }

    const profileId = defaultProfile.profile_id;

    store.setMicroSurveyState('answering');

    try {
      // 写入触发因素：需先获取完整档案以得到现有 triggers 列表
      if (answer.triggerFactor) {
        const fullProfile = await profileApi.getProfile(profileId);
        const existingTriggers = fullProfile.triggers ?? [];
        if (!existingTriggers.includes(answer.triggerFactor)) {
          const updatedTriggers = [...existingTriggers, answer.triggerFactor];
          await profileApi.updateProfile(profileId, { triggers: updatedTriggers });
        }

        // 可选事件记录（仅自定义文本时触发）
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

      // 提交完成
      store.setMicroSurveyState('submitted');

      // 2 秒后自动关闭
      setTimeout(() => {
        useProfileStore.getState().setMicroSurveyState('hidden');
      }, 2000);
    } catch {
      // 失败 → 回退到展示状态，保留用户选择
      store.setMicroSurveyState('showing');
      // views 层通过 store state 变化展示 toast "保存失败，请重试"
    }
  }, []);

  // ==========================================================================
  // skip — 跳过微问卷
  // ==========================================================================

  const skip = useCallback((): void => {
    useProfileStore.getState().setMicroSurveyState('hidden');
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
// 模块作用域函数（供 ProfileCoordination 和 Hook 内部使用）
// ============================================================================

/** 检查 consultationId 是否已弹出过 */
export function hasBeenDisplayed(consultationId: string): boolean {
  return displayedConsultationIds.has(consultationId);
}

/** 标记 consultationId 为已弹出 */
export function markAsDisplayed(consultationId: string): void {
  displayedConsultationIds.add(consultationId);
}

// ============================================================================
// 内部工具
// ============================================================================

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

    await httpClient.request({
      url: '/api/v1/events',
      method: 'POST',
      data: eventData,
      header: { 'Content-Type': 'application/json' },
    });
  } catch {
    // fire-and-forget：失败不影响主流程
  }
}
