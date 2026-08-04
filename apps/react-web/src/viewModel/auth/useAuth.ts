/**
 * 模块: react-web.viewModel.auth.useAuth
 * 职责: 认证会话 Hook——登录/注册/登出/会话恢复编排，view 层唯一入口。
 * 边界:
 *   - 依赖: application/auth（用例）、infrastructure（仓储实现组装）、userStore
 *   - 被依赖: view/pages/auth、view/layouts
 * 禁止行为:
 *   - 禁止 view 层直接 import application/infrastructure——必须经此 Hook
 */

import { useCallback } from 'react';
import type { RegisterRequest } from '@campfire/ts-shared/auth';
import { authUseCases } from '@/application/auth';
import type { IAuthRepository } from '@/application/auth';
import { authRepository } from '@/infrastructure/repositories/AuthRepository';
import { registerSessionExpiredHandler } from '@/infrastructure/http/httpClient';
import { tokenStorage } from '@/infrastructure/http/tokenManager';
import { useUserStore } from './userStore';

/** 仓储组装点（本期为单例直注；S6 如需可替换为 DI 容器） */
const repo: IAuthRepository = authRepository;

// 会话失效联动：httpClient 刷新失败 → 清空 store（跳登录由守卫布局响应 sessionState）
let handlerRegistered = false;
function ensureSessionExpiredHandler(): void {
  if (handlerRegistered) return;
  handlerRegistered = true;
  registerSessionExpiredHandler(() => {
    useUserStore.getState().clearSession();
  });
}

export function useAuth() {
  const { user, sessionState, tokenPair, setSession, setUser, clearSession, restoreFromStorage } = useUserStore();
  ensureSessionExpiredHandler();

  const login = useCallback(
    async (phone: string, password: string) => {
      const tokens = await authUseCases.login(repo, phone, password);
      // 先持久化 token 再拉 /me（fetchMe 依赖 httpClient 注入的 token）
      tokenStorage.setTokens(tokens);
      const me = await authUseCases.fetchMe(repo);
      setSession(me, tokens);
      return me;
    },
    [setSession],
  );

  const register = useCallback(async (request: RegisterRequest) => {
    return authUseCases.register(repo, request);
  }, []);

  const logout = useCallback(async () => {
    if (tokenPair) {
      await authUseCases.logout(repo, tokenPair);
    }
    clearSession();
  }, [tokenPair, clearSession]);

  /** 应用启动：恢复本地 Token → 拉取 /me 重建会话 */
  const restoreSession = useCallback(async () => {
    const pair = restoreFromStorage();
    if (!pair) return null;
    try {
      const me = await authUseCases.fetchMe(repo);
      setSession(me, pair);
      return me;
    } catch {
      clearSession();
      return null;
    }
  }, [restoreFromStorage, setSession, clearSession]);

  /** 刷新当前用户信息（准入状态变更后的轮询） */
  const refreshUser = useCallback(async () => {
    const me = await authUseCases.fetchMe(repo);
    setUser(me);
    return me;
  }, [setUser]);

  /** 驳回后补交材料重提（rejected → pending_review） */
  const resubmitReview = useCallback(
    async (realName: string | null) => {
      if (!user) return;
      await authUseCases.resubmitReview(repo, user.userId, realName);
      await refreshUser();
    },
    [user, refreshUser],
  );

  return {
    user,
    sessionState,
    isAuthenticated: sessionState === 'authenticated',
    login,
    register,
    logout,
    restoreSession,
    refreshUser,
    resubmitReview,
  };
}
