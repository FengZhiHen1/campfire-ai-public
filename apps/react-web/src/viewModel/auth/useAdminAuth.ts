/**
 * 模块: react-web.viewModel.auth.useAdminAuth
 * 职责: 平台管理 Hook（admin）——邀请码生成/列表/停用 + 准入审核列表/通过/驳回。
 * 边界:
 *   - 依赖: application/auth（用例）、infrastructure（仓储组装）
 *   - 被依赖: view/pages/admin
 */

import { useCallback, useEffect, useState } from 'react';
import type {
  InviteCodeCreateRequest,
  InviteCodeItem,
  ReviewListItem,
} from '@campfire/ts-shared/auth';
import { authUseCases } from '@/application/auth';
import type { IAuthRepository } from '@/application/auth';
import { authRepository } from '@/infrastructure/repositories/AuthRepository';

const repo: IAuthRepository = authRepository;

export function useInviteCodes() {
  const [items, setItems] = useState<InviteCodeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const reload = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await authUseCases.fetchInviteCodes(repo);
      setItems(result.items);
    } catch (err) {
      setError((err as Error).message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const create = useCallback(
    async (request: InviteCodeCreateRequest) => {
      const result = await authUseCases.createInviteCodes(repo, request);
      await reload();
      return result.codes;
    },
    [reload],
  );

  const revoke = useCallback(
    async (code: string) => {
      await authUseCases.revokeInviteCode(repo, code);
      await reload();
    },
    [reload],
  );

  return { items, loading, error, reload, create, revoke };
}

export function useReviews() {
  const [items, setItems] = useState<ReviewListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const reload = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await authUseCases.fetchReviews(repo);
      setItems(result.items);
    } catch (err) {
      setError((err as Error).message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const approve = useCallback(
    async (userId: string) => {
      await authUseCases.approveReview(repo, userId);
      await reload();
    },
    [reload],
  );

  const reject = useCallback(
    async (userId: string, reason: string) => {
      await authUseCases.rejectReview(repo, userId, reason);
      await reload();
    },
    [reload],
  );

  return { items, loading, error, reload, approve, reject };
}
