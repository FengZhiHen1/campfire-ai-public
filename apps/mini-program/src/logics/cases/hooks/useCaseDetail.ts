/**
 * CASE-09 案例管理逻辑 — 案例详情 Hook。
 *
 * 封装案例详情查询，每次调用 getCase 获取最新数据。
 * caseId 变更时自动取消旧请求并重新查询。
 *
 * 调用路径：
 *   views/ → hooks/useCaseDetail → services/caseApi → httpClient
 *
 * 设计依据：
 * - 设计文档 §1.1 技术实现思路（详情 Hook 设计）
 * - 设计文档 §1.6 架构权衡（请求取消策略）
 * - 落地规范 §1.5 步骤 10：查询详情
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import type { CaseResponse } from '@campfire/ts-shared';
import { getCase } from '../services/caseApi';

// ============================================================================
// 类型定义
// ============================================================================

/** useCaseDetail 的返回值 */
export interface UseCaseDetailReturn {
  /** 案例详情 */
  data: CaseResponse | null;
  /** 是否正在加载 */
  loading: boolean;
  /** 错误信息 */
  error: string | null;
  /** 重新查询当前案例 */
  refetch: () => void;
}

// ============================================================================
// Hook
// ============================================================================

/**
 * 案例详情查询 Hook。
 *
 * 当 caseId 变更时自动取消旧请求并查询新案例。
 * 不含缓存逻辑——案例详情需要实时性，乐观锁编辑要求读取最新的 updated_at。
 *
 * @param caseId - 案例唯一标识，undefined 时不触发请求
 * @returns 详情数据、加载状态、错误和 refetch 函数
 */
export function useCaseDetail(caseId: string | undefined): UseCaseDetailReturn {
  const [data, setData] = useState<CaseResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // 保存当前活跃请求的 AbortController
  const abortRef = useRef<AbortController | null>(null);

  /**
   * 核心查询逻辑。
   * 每次调用前取消上一个未完成的请求。
   */
  const fetchDetail = useCallback(async (id: string): Promise<void> => {
    // 取消上一个未完成的请求
    if (abortRef.current) {
      abortRef.current.abort();
    }

    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);

    try {
      const result = await getCase(id, controller.signal);
      // 仅当本请求仍为活跃请求时才更新状态
      if (!controller.signal.aborted) {
        setData(result);
      }
    } catch (err: unknown) {
      if (!controller.signal.aborted) {
        const message =
          err instanceof Error ? err.message : 'Failed to fetch case detail';
        setError(message);
      }
    } finally {
      // 仅当本请求仍为活跃请求时才清除 loading
      if (abortRef.current === controller) {
        setLoading(false);
        abortRef.current = null;
      }
    }
  }, []);

  // caseId 变更时自动查询
  useEffect(() => {
    if (caseId) {
      // 每次新请求前 abort 上一个 AbortController
      if (abortRef.current) {
        abortRef.current.abort();
      }
      fetchDetail(caseId);
    } else {
      // caseId 为空时重置状态
      setData(null);
      setLoading(false);
      setError(null);
    }

    return () => {
      // 组件卸载时取消进行中的请求
      if (abortRef.current) {
        abortRef.current.abort();
      }
    };
  }, [caseId, fetchDetail]);

  /**
   * 手动重新查询当前案例。
   */
  const refetch = useCallback((): void => {
    if (caseId) {
      fetchDetail(caseId);
    }
  }, [caseId, fetchDetail]);

  return { data, loading, error, refetch };
}
