/**
 * 模块: features/memory/viewModel/useMemoryPaging
 * 职责: 记忆时间线的触底分页——追加下一页、独立承载触底失败（不混淆整页失败）
 * 数据来源:
 *   - docs/design/pages/记忆页.md: MUST — 状态覆盖表（长列表触底自动分页；触底失败要可见可重试）
 *   - docs/技术设计/面/profile/记忆面HTTP契约.md: MUST — 第 3、6 节
 * 边界:
 *   - 依赖: features/memory/application、features/memory/domain/failures
 *   - 被依赖: features/memory/viewModel/useMemoryPage
 * 禁止行为:
 *   - 禁止把触底失败写进行内错误（没有对应行，永远渲染不出来——禁止静默兜底）
 *   - 禁止触底失败改整页状态（已加载内容仍然有效）
 *
 * 为什么抽出来：触底分页有自己的一套状态（游标、加载中、独立失败），与首屏加载/纠正/删除
 * 互不依赖；把它单独成 hook 后，记忆页主 hook 只负责首屏与写操作。
 *
 * 身份稳定性：本 hook 的返回值在入参不变时保持同一引用（`append` 由调用方用 `useCallback`
 * 固定）。否则每次渲染都产出新的 `loadMore`，会让依赖它的首屏加载 effect 反复重跑。
 */

import { useCallback, useMemo, useRef, useState } from 'react';

import type { MemoryEpisode } from '../../../shared/types/memory';
import type { MemoryPort } from '../application/ports';
import { LoadEpisodesUseCase } from '../application/usecases';
import { type MemoryFailure, failureFromError } from '../domain/failures';

/** 触底分页状态与操作。 */
export interface MemoryPaging {
  loadingMore: boolean;
  loadMoreFailure: MemoryFailure | null;
  /** 还有下一页（尾游标非空）。 */
  hasMore: boolean;
  loadMore(): Promise<void>;
  /** 清空失败与加载中标记（首屏重取前调用，让尾部回到与首屏一致的形态）。 */
  reset(): void;
  /** 记下当前尾游标；首屏每次加载后都会调用（null 表示没有下一页）。 */
  setCursor(nextCursor: string | null): void;
}

/**
 * 记忆时间线触底分页。
 *
 * @param port 记忆端口
 * @param append 追加一页条目（由调用方维护条目的唯一真相；必须用 `useCallback` 固定引用）
 */
export function useMemoryPaging(port: MemoryPort, append: (items: MemoryEpisode[]) => void): MemoryPaging {
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreFailure, setLoadMoreFailure] = useState<MemoryFailure | null>(null);
  // 尾游标是「是否还有下一页」的唯一真相：首屏加载与触底取数都经由 setCursor 更新它。
  const [cursor, setCursor] = useState<string | null>(null);
  const cursorRef = useRef<string | null>(null);
  const loadingMoreRef = useRef(false);

  const loadMore = useCallback(async (): Promise<void> => {
    const current = cursorRef.current;
    if (current === null || loadingMoreRef.current) return;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    // 重试即清除上一次的失败：尾部回到「正在加载」，失败再出现时又是新的一次。
    setLoadMoreFailure(null);
    try {
      const page = await new LoadEpisodesUseCase(port).execute(current);
      // 追加而不是替换：分页是同一份时间线的延续。
      append(page.items);
      cursorRef.current = page.nextCursor;
      setCursor(page.nextCursor);
    } catch (error) {
      // 触底失败不改整页状态：已加载的内容仍然有效，游标留在原处让使用者再试。
      // 失败必须落在自己的状态上——它没有对应的行，写成行内错误永远渲染不出来。
      setLoadMoreFailure(failureFromError(error));
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [append, port]);

  const reset = useCallback((): void => {
    setLoadMoreFailure(null);
    setLoadingMore(false);
    loadingMoreRef.current = false;
  }, []);

  const syncCursor = useCallback((next: string | null): void => {
    cursorRef.current = next;
    setCursor(next);
  }, []);

  return useMemo(
    () => ({ loadingMore, loadMoreFailure, hasMore: cursor !== null, loadMore, reset, setCursor: syncCursor }),
    [loadingMore, loadMoreFailure, cursor, loadMore, reset, syncCursor],
  );
}
