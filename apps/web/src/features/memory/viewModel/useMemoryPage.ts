/**
 * 模块: features/memory/viewModel/useMemoryPage
 * 职责: 记忆页状态——时间线与触底分页、删除二次确认、纠正流与两步结果呈现
 * 数据来源:
 *   - docs/design/pages/记忆页.md: MUST — 状态覆盖表（loading/empty/error、中间态、保留已填内容）
 *   - docs/技术设计/面/profile/记忆面HTTP契约.md: MUST — 第 3、5、6 节
 * 边界:
 *   - 依赖: features/memory/application、features/memory/domain
 *   - 被依赖: features/memory/view/MemoryPage
 * 禁止行为:
 *   - 禁止在纠正失败时清空已填内容（记忆页第 62 行）
 *   - 禁止把中间态笼统呈现成成功或失败（两步的失败语义不同）
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import type { MemoryEpisode } from '../../../shared/types/memory';
import type { MemoryPort } from '../application/ports';
import { CorrectEpisodeUseCase, DeleteEpisodeUseCase, LoadEpisodesUseCase } from '../application/usecases';
import { toDatetimeLocalValue } from '../domain/episodes';
import { type CorrectionDraft, CorrectionValidationError, type CorrectionFieldErrors } from '../domain/formValidation';
import {
  CORRECTION_INTERMEDIATE_COPY,
  CORRECTION_WRITTEN_COPY,
  type MemoryFailure,
  failureFromError,
  memoryFailureDescription,
  memoryFailureTitle,
} from '../domain/failures';

/** 页面加载状态。 */
export type MemoryStatus = 'loading' | 'ready' | 'error';

/** 纠正流状态：草稿在提交失败后必须原样保留。 */
export interface MemoryCorrectionState {
  target: MemoryEpisode;
  draft: CorrectionDraft;
  errors: CorrectionFieldErrors;
  submitting: boolean;
  failure: MemoryFailure | null;
}

/** 记忆页状态与操作。 */
export interface MemoryPageState {
  items: MemoryEpisode[];
  status: MemoryStatus;
  failure: MemoryFailure | null;
  /** 触底分页：正在加载下一页。 */
  loadingMore: boolean;
  hasMore: boolean;
  /**
   * 触底分页的失败。
   *
   * 与 `rowFailure` 分开：它没有对应的行，需要尾部自己的可见形态承载
   * （写成行内错误时没有任何一行能匹配上，失败会被静默吞掉）。
   */
  loadMoreFailure: MemoryFailure | null;
  /** 待删除确认的记忆；非空即渲染 .confirm-sheet。 */
  deleteTarget: MemoryEpisode | null;
  /** 正在删除的那一条标识。 */
  deletingId: string | null;
  /** 行内错误（删除失败等）。 */
  rowFailure: { episodeKey: string; failure: MemoryFailure } | null;
  correction: MemoryCorrectionState | null;
  /** 一次性提示：纠正成功，或中间态（原记录已撤下、新记录没写成）。 */
  notice: { kind: 'written' | 'superseded-only'; text: string } | null;

  retry(): Promise<void>;
  loadMore(): Promise<void>;
  askDelete(episode: MemoryEpisode): void;
  cancelDelete(): void;
  confirmDelete(): Promise<void>;
  openCorrection(episode: MemoryEpisode): void;
  closeCorrection(): void;
  updateCorrectionDraft(patch: Partial<CorrectionDraft>): void;
  submitCorrection(): Promise<void>;
  dismissNotice(): void;
}

/** 失败的可读文案（整页与行内共用一句）。 */
export function failureMessage(failure: MemoryFailure): string {
  return `${memoryFailureTitle(failure)}——${memoryFailureDescription(failure)}`;
}

/**
 * 记忆页状态。
 *
 * @param port 记忆端口
 */
export function useMemoryPage(port: MemoryPort): MemoryPageState {
  const [items, setItems] = useState<MemoryEpisode[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [status, setStatus] = useState<MemoryStatus>('loading');
  const [failure, setFailure] = useState<MemoryFailure | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreFailure, setLoadMoreFailure] = useState<MemoryFailure | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<MemoryEpisode | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [rowFailure, setRowFailure] = useState<{ episodeKey: string; failure: MemoryFailure } | null>(null);
  const [correction, setCorrection] = useState<MemoryCorrectionState | null>(null);
  const [notice, setNotice] = useState<MemoryPageState['notice']>(null);

  // 迟到的响应不得覆盖新结果（CORE-03 身份守卫）：首屏与重试各算一次加载。
  const loadToken = useRef(0);

  const loadFirstPage = useCallback(
    async (options?: { initial?: boolean }): Promise<void> => {
      const token = loadToken.current + 1;
      loadToken.current = token;
      if (options?.initial !== true) {
        setStatus('loading');
        setFailure(null);
        // 首页重取后上一轮的触底失败不再适用：新的一页会给出新的尾部形态。
        setLoadMoreFailure(null);
      }
      try {
        const page = await new LoadEpisodesUseCase(port).execute();
        if (loadToken.current !== token) return;
        setItems(page.items);
        setCursor(page.nextCursor);
        setStatus('ready');
        setFailure(null);
      } catch (error) {
        if (loadToken.current !== token) return;
        setFailure(failureFromError(error));
        setStatus('error');
      }
    },
    [port],
  );

  useEffect(() => {
    // 首次加载。豁免 set-state-in-effect 的理由与档案页同：这是挂载时向端口取数据，
    // 首次路径上没有任何同步 setState（`initial: true` 跳过状态重置），
    // 状态更新都发生在 await 之后，规则无法跨函数边界证明这一点。
    // oxlint-disable-next-line react/set-state-in-effect
    void loadFirstPage({ initial: true });
  }, [loadFirstPage]);

  const loadMore = useCallback(async (): Promise<void> => {
    if (cursor === null || loadingMore) return;
    setLoadingMore(true);
    // 重试即清除上一次的失败：尾部回到「正在加载」，失败再出现时又是新的一次。
    setLoadMoreFailure(null);
    try {
      const page = await new LoadEpisodesUseCase(port).execute(cursor);
      // 追加而不是替换：分页是同一份时间线的延续。
      setItems((current) => [...current, ...page.items]);
      setCursor(page.nextCursor);
    } catch (error) {
      // 触底失败不改整页状态：已加载的内容仍然有效，游标留在原处让使用者再试。
      // 失败必须落在自己的状态上——它没有对应的行，写成行内错误（空键占位）永远渲染不出来。
      setLoadMoreFailure(failureFromError(error));
    } finally {
      setLoadingMore(false);
    }
  }, [cursor, loadingMore, port]);

  const askDelete = useCallback((episode: MemoryEpisode): void => {
    setDeleteTarget(episode);
  }, []);

  const cancelDelete = useCallback((): void => {
    setDeleteTarget(null);
  }, []);

  const confirmDelete = useCallback(async (): Promise<void> => {
    const target = deleteTarget;
    if (target === null) return;
    setDeleteTarget(null);
    setDeletingId(target.episode_key);
    setRowFailure(null);
    try {
      await new DeleteEpisodeUseCase(port).execute(target.episode_key);
      // 本地移除：已删除的记忆不得再显示（AC-08 的界面侧）。
      setItems((current) => current.filter((item) => item.episode_key !== target.episode_key));
    } catch (error) {
      setRowFailure({ episodeKey: target.episode_key, failure: failureFromError(error) });
    } finally {
      setDeletingId(null);
    }
  }, [deleteTarget, port]);

  const openCorrection = useCallback((episode: MemoryEpisode): void => {
    setCorrection({
      target: episode,
      // 预填原内容与发生时间（记忆页第 61 行）：纠正是在原文上改。
      draft: { content: episode.content, occurredAtLocal: toDatetimeLocalValue(episode.occurred_at) },
      errors: {},
      submitting: false,
      failure: null,
    });
  }, []);

  const closeCorrection = useCallback((): void => {
    setCorrection(null);
  }, []);

  const updateCorrectionDraft = useCallback((patch: Partial<CorrectionDraft>): void => {
    setCorrection((current) =>
      current === null ? null : { ...current, draft: { ...current.draft, ...patch }, errors: {} },
    );
  }, []);

  const submitCorrection = useCallback(async (): Promise<void> => {
    const current = correction;
    if (current === null) return;
    setCorrection({ ...current, submitting: true, failure: null, errors: {} });
    try {
      const outcome = await new CorrectEpisodeUseCase(port).execute(
        current.target.episode_key,
        current.draft,
        current.target.content,
      );
      setCorrection(null);
      if (outcome.kind === 'written') {
        setNotice({ kind: 'written', text: CORRECTION_WRITTEN_COPY });
        // 成功：重新取第一页，新条目出现在它自己的日期位置。
        await loadFirstPage();
        return;
      }
      // 中间态：旧记录已撤下、新记录没写成。如实呈现，不笼统报成功或失败。
      setNotice({ kind: 'superseded-only', text: CORRECTION_INTERMEDIATE_COPY });
      setItems((currentItems) => currentItems.filter((item) => item.episode_key !== current.target.episode_key));
    } catch (error) {
      if (error instanceof CorrectionValidationError) {
        setCorrection({ ...current, submitting: false, failure: null, errors: error.fieldErrors });
        return;
      }
      // 提交失败保留已填内容（记忆页状态覆盖表）：只加失败原因，草稿不动。
      setCorrection({ ...current, submitting: false, failure: failureFromError(error) });
    }
  }, [correction, loadFirstPage, port]);

  const dismissNotice = useCallback((): void => {
    setNotice(null);
  }, []);

  return {
    items,
    status,
    failure,
    loadingMore,
    hasMore: cursor !== null,
    loadMoreFailure,
    deleteTarget,
    deletingId,
    rowFailure,
    correction,
    notice,
    retry: async (): Promise<void> => {
      await loadFirstPage();
    },
    loadMore,
    askDelete,
    cancelDelete,
    confirmDelete,
    openCorrection,
    closeCorrection,
    updateCorrectionDraft,
    submitCorrection,
    dismissNotice,
  };
}
