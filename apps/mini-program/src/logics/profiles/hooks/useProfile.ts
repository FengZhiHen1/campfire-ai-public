/**
 * useProfile Hook — PROF-06 views 层获取档案数据和操作方法的唯一入口。
 *
 * 职责：
 * - 返回 UseProfileReturn（profiles, isLoading, error, CRUD 方法）
 * - 所有操作前置校验 sessionState === 'authenticated'
 * - 列表采用 SWR 策略（先返回缓存，后台刷新）
 * - 禁止在 useEffect 中自动调用 fetchProfiles()
 * - 禁止直接操作 DOM 或调用 Taro.navigateTo()
 *
 * 数据来源:
 *   - useAuth: MUST — 认证状态校验
 *   - profileStore: MUST — 档案列表/详情/错误缓存
 *   - profileApi: MUST — 档案 CRUD HTTP 接口
 * 边界:
 *   - 依赖: ../store/profileStore, ../services/profileApi, ../../shared/hooks/useAuth
 *   - 被依赖: PROF-06 views/profiles/
 * 禁止行为:
 *   - 禁止在 useEffect 中自动触发 fetchProfiles()
 *   - 禁止直接 import views/ 下的任何文件
 */

import { useCallback, useMemo } from 'react';
import { useAuth } from '../../shared/hooks/useAuth';
import { useProfileStore } from '../store/profileStore';
import * as profileApi from '../services/profileApi';
import {
  AuthRequiredError,
  NetworkError,
  ServerError,
} from '../types';
import type {
  UseProfileReturn,
  ProfileCreate,
  ProfileUpdate,
  ProfileResponse,
} from '../types';

// ============================================================================
// 内部工具
// ============================================================================

function classifyError(err: unknown, fallback: Error): Error {
  if (err instanceof AuthRequiredError) return err;
  if (err instanceof NetworkError) return err;
  if (err instanceof ServerError) return err;
  if (err instanceof Error) {
    const msg = err.message.toLowerCase();
    if (msg.includes('failed to fetch') || msg.includes('network') || msg.includes('timeout')) {
      return new NetworkError('加载失败，请检查网络后重试');
    }
  }
  return fallback;
}

/**
 * Fire-and-forget 缓存失效通知。
 * PROF-02 未就绪时 404 为预期行为，静默忽略。
 */
async function invalidateCacheSafe(profileId: string): Promise<void> {
  try {
    await profileApi.invalidateCache(profileId, ['all']);
  } catch (e: unknown) {
    console.warn('[PROF-07] invalidate cache failed, PROF-02 may not be ready', e);
  }
}

// ============================================================================
// useProfile Hook
// ============================================================================

export function useProfile(): UseProfileReturn {
  const { sessionState } = useAuth();

  const profiles = useProfileStore((s) => s.list);
  const listState = useProfileStore((s) => s.listState);
  const error = useProfileStore((s) => s.error);

  const isLoading = listState === 'loading';

  // ==========================================================================
  // fetchProfiles — 获取档案列表（SWR）
  // ==========================================================================

  const fetchProfiles = useCallback(async (): Promise<void> => {
    if (sessionState !== 'authenticated') {
      const err = new AuthRequiredError('请先登录');
      useProfileStore.getState().setError(err);
      useProfileStore.getState().setListState('error');
      throw err;
    }

    const store = useProfileStore.getState();
    if (store.listState === 'loading') {
      return;
    }

    store.setListState('loading');
    store.clearError();

    try {
      const data = await profileApi.listProfiles();
      useProfileStore.getState().setList(data);
      useProfileStore.getState().setListState('ready');
    } catch (err: unknown) {
      const httpErr = err as { statusCode?: number };
      const store2 = useProfileStore.getState();

      if (httpErr.statusCode === 401) {
        store2.setError(new AuthRequiredError('登录已过期'));
      } else {
        store2.setError(classifyError(err, new NetworkError('加载失败，请检查网络后重试')));
      }

      store2.setListState('error');
      console.error('[PROF-07] listProfiles failed', {
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }, [sessionState]);

  // ==========================================================================
  // getProfile — 获取单个档案详情
  // ==========================================================================

  const getProfile = useCallback(async (profileId: string): Promise<ProfileResponse> => {
    if (sessionState !== 'authenticated') {
      throw new AuthRequiredError('请先登录');
    }

    try {
      const detail = await profileApi.getProfile(profileId);
      useProfileStore.getState().setCurrentDetail(detail);
      return detail;
    } catch (err: unknown) {
      throw classifyError(err, new ServerError('服务异常，请稍后重试'));
    }
  }, [sessionState]);

  // ==========================================================================
  // createProfile — 创建档案（冷启动引导 / 手动创建）
  // ==========================================================================

  const createProfile = useCallback(async (data: ProfileCreate): Promise<ProfileResponse> => {
    if (sessionState !== 'authenticated') {
      throw new AuthRequiredError('请先登录');
    }

    const store = useProfileStore.getState();
    store.setSubmitState('submitting');

    try {
      const response = await profileApi.createProfile(data);

      store.addToList(response);
      store.setListState('ready');
      store.setSubmitState('idle');
      store.notifyChangeListeners(response.profile_id);

      invalidateCacheSafe(response.profile_id);

      return response;
    } catch (err: unknown) {
      const httpErr = err as { statusCode?: number; data?: { detail?: Record<string, string> } };

      if (httpErr.statusCode === 422) {
        store.setSubmitState('idle');
      } else if (httpErr.statusCode === 409) {
        store.setSubmitState('idle');
      } else {
        store.setSubmitState('error');
      }

      console.error('[PROF-07] createProfile failed', {
        error: err instanceof Error ? err.message : String(err),
        statusCode: httpErr.statusCode,
      });

      throw err;
    }
  }, [sessionState]);

  // ==========================================================================
  // updateProfile — 更新档案（Merge Patch）
  // ==========================================================================

  const updateProfile = useCallback(async (
    profileId: string,
    data: Partial<ProfileUpdate>,
  ): Promise<ProfileResponse> => {
    if (sessionState !== 'authenticated') {
      throw new AuthRequiredError('请先登录');
    }

    const store = useProfileStore.getState();
    store.setSubmitState('submitting');

    try {
      const response = await profileApi.updateProfile(profileId, data);

      store.updateInList(profileId, {
        nickname: response.nickname,
        age_range: response.age_range,
        diagnosis_type: response.diagnosis_type,
        primary_behavior: response.primary_behavior,
        is_default: response.is_default,
      });
      store.setCurrentDetail(response);
      store.setSubmitState('idle');

      store.notifyChangeListeners(profileId);
      invalidateCacheSafe(profileId);

      return response;
    } catch (err: unknown) {
      const httpErr = err as { statusCode?: number };
      if (httpErr.statusCode === 422 || httpErr.statusCode === 409) {
        store.setSubmitState('idle');
      } else {
        store.setSubmitState('error');
      }

      console.error('[PROF-07] updateProfile failed', {
        profileId,
        error: err instanceof Error ? err.message : String(err),
      });

      throw err;
    }
  }, [sessionState]);

  // ==========================================================================
  // deleteProfile — 删除档案
  // ==========================================================================

  const deleteProfile = useCallback(async (profileId: string): Promise<void> => {
    if (sessionState !== 'authenticated') {
      throw new AuthRequiredError('请先登录');
    }

    try {
      await profileApi.deleteProfile(profileId);

      const store = useProfileStore.getState();
      const wasDefault = store.list.find((p) => p.profile_id === profileId)?.is_default;

      store.removeFromList(profileId);

      if (wasDefault) {
        const remaining = useProfileStore.getState().list;
        if (remaining.length > 0) {
          try {
            await profileApi.setDefaultProfile(remaining[0].profile_id);
            store.updateInList(remaining[0].profile_id, { is_default: true });
          } catch {
            console.warn('[PROF-07] auto-promote default failed after delete');
          }
        }
      }

      store.notifyChangeListeners(profileId);
      invalidateCacheSafe(profileId);
    } catch (err: unknown) {
      console.error('[PROF-07] deleteProfile failed', {
        profileId,
        error: err instanceof Error ? err.message : String(err),
      });
      throw err;
    }
  }, [sessionState]);

  // ==========================================================================
  // setDefault — 设为默认档案
  // ==========================================================================

  const setDefault = useCallback(async (profileId: string): Promise<void> => {
    if (sessionState !== 'authenticated') {
      throw new AuthRequiredError('请先登录');
    }

    const store = useProfileStore.getState();
    const current = store.list.find((p) => p.profile_id === profileId);
    if (current?.is_default) {
      return;
    }

    try {
      await profileApi.setDefaultProfile(profileId);

      const updatedList = store.list.map((p) => ({
        ...p,
        is_default: p.profile_id === profileId,
      }));
      useProfileStore.getState().setList(updatedList);

      store.notifyChangeListeners(profileId);
      invalidateCacheSafe(profileId);
    } catch (err: unknown) {
      console.error('[PROF-07] setDefault failed', {
        profileId,
        error: err instanceof Error ? err.message : String(err),
      });
      throw err;
    }
  }, [sessionState]);

  // ==========================================================================
  // 返回值（useMemo 防止不必要的重渲染）
  // ==========================================================================

  return useMemo<UseProfileReturn>(
    () => ({
      profiles,
      isLoading,
      error,
      fetchProfiles,
      getProfile,
      createProfile,
      updateProfile,
      deleteProfile,
      setDefault,
    }),
    [profiles, isLoading, error, fetchProfiles, getProfile, createProfile, updateProfile, deleteProfile, setDefault],
  );
}
