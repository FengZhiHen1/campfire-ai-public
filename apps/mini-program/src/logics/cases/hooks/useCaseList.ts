/**
 * CASE-09 案例管理逻辑 — 案例列表 Hook。
 *
 * 封装分页查询、状态筛选和手动刷新。
 * 内部持有 listCases 的调用状态（loading/data/error）。
 * 使用 AbortController 处理竞态——新请求自动取消旧请求。
 *
 * 调用路径：
 *   views/ → hooks/useCaseList → services/caseApi → httpClient
 *
 * 设计依据：
 * - 设计文档 §1.1 技术实现思路（列表 Hook 设计）
 * - 设计文档 §1.6 架构权衡（分页竞态处理）
 * - 落地规范 §1.5 步骤 9：查询列表
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import type { CaseListItem, PaginatedResponse } from '@campfire/ts-shared';
import { listCases } from '../services/caseApi';

// ============================================================================
// 类型定义
// ============================================================================

/** useCaseList 的参数 */
export interface UseCaseListParams {
  /** 可选状态筛选 */
  status?: string;
  /** 页码（从 1 开始） */
  page?: number;
  /** 每页条数 */
  pageSize?: number;
}

/** useCaseList 的返回值 */
export interface UseCaseListReturn {
  /** 分页列表数据 */
  data: PaginatedResponse<CaseListItem> | null;
  /** 是否正在加载 */
  loading: boolean;
  /** 错误信息 */
  error: string | null;
  /** 手动刷新（重新请求当前页） */
  refresh: () => void;
}

// ============================================================================
// Hook
// ============================================================================

/**
 * 案例列表查询 Hook。
 *
 * 当 status / page / pageSize 任一变化时自动重新请求。
 * 连续快速翻页时，新请求通过 AbortController 取消旧请求，
 * 避免旧页面数据覆盖新页面。
 *
 * @param params - 查询参数
 * @returns 列表数据、加载状态、错误和刷新函数
 */
export function useCaseList(params?: UseCaseListParams): UseCaseListReturn {
  const [data, setData] = useState<PaginatedResponse<CaseListItem> | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // 保存当前活跃请求的 AbortController，用于竞态取消
  const abortRef = useRef<AbortController | null>(null);

  // 刷新计数器，每次 refresh() 调用自增以触发重新请求
  const [refreshKey, setRefreshKey] = useState<number>(0);

  /**
   * 核心请求逻辑。
   * 每次调用前取消上一个未完成的请求。
   */
  const fetchData = useCallback(
    async (status?: string, page?: number, pageSize?: number): Promise<void> => {
      // 取消上一个未完成的请求
      if (abortRef.current) {
        abortRef.current.abort();
      }

      const controller = new AbortController();
      abortRef.current = controller;

      setLoading(true);
      setError(null);

      try {
        const result = await listCases(status, page, pageSize, controller.signal);
        // 仅当本请求仍为活跃请求时才更新状态
        if (!controller.signal.aborted) {
          setData(result);
        }
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          const message =
            err instanceof Error ? err.message : 'Failed to fetch case list';
          setError(message);
        }
      } finally {
        // 仅当本请求仍为活跃请求时才清除 loading
        if (abortRef.current === controller) {
          setLoading(false);
          abortRef.current = null;
        }
      }
    },
    [],
  );

  // 参数变化或手动刷新时重新请求
  useEffect(() => {
    fetchData(params?.status, params?.page, params?.pageSize);

    return () => {
      // 组件卸载时取消进行中的请求
      if (abortRef.current) {
        abortRef.current.abort();
      }
    };
  }, [params?.status, params?.page, params?.pageSize, refreshKey, fetchData]);

  /**
   * 手动刷新（保持当前查询参数，重新请求）。
   */
  const refresh = useCallback((): void => {
    setRefreshKey((k) => k + 1);
  }, []);

  return { data, loading, error, refresh };
}
