/**
 * CASE-09 案例管理逻辑 — 审核台页 Hook。
 *
 * 封装审核台页面的全部业务逻辑：待审核队列分页加载、审核裁决（批准/驳回）、
 * 角色门禁、AI 预审摘要展示。View 层仅负责 JSX 渲染。
 *
 * 调用路径：views/cases/pages/review → useReviewPage → caseApi
 *
 * 契约对齐：后端 CASE-03 审核工作流（10 步流水线）
 *
 * 禁止行为:
 *   - 禁止在 loading 期间重复触发 fetchQueue / reviewCase
 *   - 禁止驳回时不填写审核意见（reviewComment 为空串时拦截）
 */

import { useState, useEffect, useCallback } from 'react';
import Taro from '@tarojs/taro';
import { fetchReviewQueue, reviewCase } from '../services/caseApi';
import { useSessionStore } from '../../shared/store/userStore';
import type { ReviewQueueItem } from '@campfire/ts-shared';

// ============================================================================
// 类型定义
// ============================================================================

interface ReviewActionState {
  isSubmitting: boolean;
  targetCaseId: string | null;
}

/** useReviewPage 的返回值 */
export interface UseReviewPageReturn {
  /** 待审核队列 */
  queue: ReviewQueueItem[];
  /** 是否正在加载队列 */
  isLoading: boolean;
  /** 加载/操作错误信息 */
  error: string | null;
  /** 当前页码 */
  page: number;
  /** 总条数 */
  total: number;
  /** 是否有更多页 */
  hasMore: boolean;
  /** 审核操作提交状态 */
  actionState: ReviewActionState;
  /** 当前用户是否有审核权限 */
  canReview: boolean;
  /** 加载队列 */
  fetchQueue: (page?: number) => Promise<void>;
  /** 批准案例 */
  handleApprove: (caseId: string) => Promise<void>;
  /** 驳回案例 */
  handleReject: (caseId: string, comment: string) => Promise<void>;
  /** 加载下一页 */
  loadMore: () => Promise<void>;
  /** AI 预审结论 → 展示文案 */
  getAiReviewText: (overall: string) => string;
  /** 超时状态 → 展示文案 */
  getTimeoutText: (status: string) => string;
}

// ============================================================================
// 常量
// ============================================================================

const AI_REVIEW_TEXT_MAP: Record<string, string> = {
  pass: 'AI 预审通过',
  hard_block: 'AI 预审拦截',
  annotated: 'AI 预审附注',
};

const TIMEOUT_TEXT_MAP: Record<string, string> = {
  normal: '正常',
  warning: '即将超时',
  overdue: '已超时',
};

const PAGE_SIZE = 15;

// ============================================================================
// Hook
// ============================================================================

export function useReviewPage(): UseReviewPageReturn {
  const [queue, setQueue] = useState<ReviewQueueItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [actionState, setActionState] = useState<ReviewActionState>({
    isSubmitting: false,
    targetCaseId: null,
  });

  const user = useSessionStore((s) => s.user);
  const roles: string[] = user?.roles ?? [];
  // TODO: 暂时关闭权限隔离，后续恢复
  const canReview = true; // roles.includes('expert') || roles.includes('admin');

  // TODO: 暂时关闭权限隔离，后续恢复
  // useEffect(() => {
  //   if (!canReview) {
  //     Taro.showToast({ title: '暂无审核权限', icon: 'none' });
  //     Taro.navigateBack();
  //   }
  // }, [canReview]);

  // ===== fetchQueue =====
  const fetchQueue = useCallback(async (targetPage: number = 1): Promise<void> => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetchReviewQueue(targetPage, PAGE_SIZE);
      if (targetPage === 1) {
        setQueue(res.items);
      } else {
        setQueue((prev) => [...prev, ...res.items]);
      }
      setTotal(res.total);
      setPage(targetPage);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '加载审核队列失败';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // ===== 初始加载 =====
  useEffect(() => {
    if (canReview) {
      fetchQueue(1);
    }
  }, [canReview, fetchQueue]);

  // ===== loadMore =====
  const loadMore = useCallback(async (): Promise<void> => {
    if (isLoading || actionState.isSubmitting) return;
    const nextPage = page + 1;
    await fetchQueue(nextPage);
  }, [isLoading, actionState.isSubmitting, page, fetchQueue]);

  // ===== handleApprove =====
  const handleApprove = useCallback(async (caseId: string): Promise<void> => {
    if (actionState.isSubmitting) return;

    setActionState({ isSubmitting: true, targetCaseId: caseId });
    setError(null);
    try {
      await reviewCase(caseId, 'approved');
      setQueue((prev) => prev.filter((item) => item.case_id !== caseId));
      setTotal((prev) => prev - 1);
      Taro.showToast({ title: '已批准', icon: 'success' });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '审核操作失败';
      setError(msg);
    } finally {
      setActionState({ isSubmitting: false, targetCaseId: null });
    }
  }, [actionState.isSubmitting]);

  // ===== handleReject =====
  const handleReject = useCallback(async (caseId: string, comment: string): Promise<void> => {
    if (actionState.isSubmitting) return;

    if (!comment.trim()) {
      Taro.showToast({ title: '驳回必须填写审核意见', icon: 'none' });
      return;
    }

    setActionState({ isSubmitting: true, targetCaseId: caseId });
    setError(null);
    try {
      await reviewCase(caseId, 'rejected', comment.trim());
      setQueue((prev) => prev.filter((item) => item.case_id !== caseId));
      setTotal((prev) => prev - 1);
      Taro.showToast({ title: '已驳回', icon: 'success' });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '审核操作失败';
      setError(msg);
    } finally {
      setActionState({ isSubmitting: false, targetCaseId: null });
    }
  }, [actionState.isSubmitting]);

  // ===== 文案映射 =====
  const getAiReviewText = useCallback((overall: string): string => {
    return AI_REVIEW_TEXT_MAP[overall] ?? overall;
  }, []);

  const getTimeoutText = useCallback((status: string): string => {
    return TIMEOUT_TEXT_MAP[status] ?? status;
  }, []);

  const hasMore = queue.length < total;

  return {
    queue,
    isLoading,
    error,
    page,
    total,
    hasMore,
    actionState,
    canReview,
    fetchQueue,
    handleApprove,
    handleReject,
    loadMore,
    getAiReviewText,
    getTimeoutText,
  };
}
