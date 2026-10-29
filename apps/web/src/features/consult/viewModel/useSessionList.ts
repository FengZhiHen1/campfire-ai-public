/**
 * 模块: features/consult/viewModel/useSessionList
 * 职责: 会话列表的取数控制器——分页触底加载、新对话入口与三态
 * 数据来源:
 *   - docs/design/pages/会话列表页.md: MUST — 状态覆盖表（loading/empty/error/edge）与分页触底加载
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 3.1/3.2 节（列表与新会话端点）
 * 边界:
 *   - 依赖: application 用例、domain/conversation、domain/errors
 *   - 被依赖: view 的会话列表页
 * 禁止行为:
 *   - 禁止把取数失败呈现成空列表（错误态必须显式，页面设计状态覆盖表 error 行）
 *   - 禁止让迟到的分页结果覆盖新一轮加载（序号守卫，VM-06）
 */

import { useEffect, useRef, useState } from 'react';

import type { ConsultPort } from '../application/ports';
import { CreateSessionUseCase, ListSessionsUseCase } from '../application/usecases';
import { toConversationRow, type ConversationRow } from '../domain/conversation';
import { failureViewFor, type ConsultFailureView } from '../domain/errors';

/** 列表状态：三态显式 + 触底加载中的附加标记。 */
export type SessionListState =
  | { status: 'loading' }
  | {
      status: 'ready';
      rows: ConversationRow[];
      nextCursor: string | null;
      loadingMore: boolean;
      /** 分页失败（只影响「更多」）：已加载的行与入口保持可用，见 retryLoadMore。 */
      loadMoreFailure: ConsultFailureView | null;
    }
  | { status: 'error'; failure: ConsultFailureView };

/** 会话列表控制器。 */
export interface SessionListController {
  state: SessionListState;
  /** 触底加载下一页（无下一页或已在加载时不动作）。 */
  loadMore(): void;
  /** 分页失败后的手动重试（失败后先停住，否则触底观察者会对同一个坏游标连环重试）。 */
  retryLoadMore(): void;
  /** 重新加载首页（错误态的重试）。 */
  reload(): void;
  /** 新对话入口：建会话后跳转。 */
  startNewConversation(): Promise<void>;
  creating: boolean;
  createFailure: ConsultFailureView | null;
}

/**
 * 会话列表控制器。
 *
 * @param consult 咨询端口
 * @param onCreated 建会话成功后的跳转回调（对话页路由）；`onboardingPending` 取自响应
 */
export function useSessionList(
  consult: ConsultPort,
  onCreated: (sessionId: string, onboardingPending: boolean) => void,
): SessionListController {
  const [attempt, setAttempt] = useState(0);
  /** 已落定的首页结果 + 它属于哪一轮任务（key 不匹配即仍在 loading）。 */
  const [settled, setSettled] = useState<{ key: string; rows: ConversationRow[]; nextCursor: string | null } | null>(
    null,
  );
  /** 首页加载失败；同样按任务 key 归属，避免上一轮的失败挂在新一轮上。 */
  const [settledError, setSettledError] = useState<{ key: string; failure: ConsultFailureView } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [creating, setCreating] = useState(false);
  const creatingRef = useRef(false);
  const [createFailure, setCreateFailure] = useState<ConsultFailureView | null>(null);
  // 分页失败单独存放（不并进 settledError）：并进去会让 state 变成 error，
  // 已加载的行整体消失，一次网络抖动看起来像「记录没了」。
  const [loadMoreFault, setLoadMoreFault] = useState<{ key: string; failure: ConsultFailureView } | null>(null);
  const loadMoreFaultRef = useRef<{ key: string; failure: ConsultFailureView } | null>(null);
  // 序号守卫（VM-06）：只有最新一轮加载允许写状态。
  const generation = useRef(0);
  const loadingMoreRef = useRef(false);
  const taskKey = `${String(attempt)}`;

  const writeLoadMoreFault = (fault: { key: string; failure: ConsultFailureView } | null): void => {
    loadMoreFaultRef.current = fault;
    setLoadMoreFault(fault);
  };

  useEffect(() => {
    const current = generation.current + 1;
    generation.current = current;
    loadingMoreRef.current = false;

    const load = async (): Promise<void> => {
      try {
        const response = await new ListSessionsUseCase(consult).execute({});
        if (generation.current !== current) return;
        const now = Date.now();
        setSettledError(null);
        setSettled({
          key: taskKey,
          rows: response.items.map((item) => toConversationRow(item, now)),
          nextCursor: response.next_cursor,
        });
      } catch (caught) {
        if (generation.current !== current) return;
        setSettledError({ key: taskKey, failure: failureViewFor(caught) });
      }
    };

    void load();
  }, [consult, taskKey]);

  const ready = settled !== null && settled.key === taskKey;
  const failure = settledError !== null && settledError.key === taskKey ? settledError.failure : null;
  const loadMoreFailure = loadMoreFault !== null && loadMoreFault.key === taskKey ? loadMoreFault.failure : null;
  const state: SessionListState =
    failure !== null
      ? { status: 'error', failure }
      : ready
        ? { status: 'ready', rows: settled.rows, nextCursor: settled.nextCursor, loadingMore, loadMoreFailure }
        : { status: 'loading' };

  const loadMore = (): void => {
    if (!ready || settled.nextCursor === null) return;
    if (loadingMoreRef.current) return;
    // 失败后停住：触底观察者会在每次渲染后重新 observe，不拦住会连环重试同一个坏游标。
    // 只认本轮任务的失败（上一轮重新加载留下的失败按 key 自然失效，不必在 effect 里清状态）。
    const fault = loadMoreFaultRef.current;
    if (fault !== null && fault.key === taskKey) return;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    const current = generation.current;
    const cursor = settled.nextCursor;

    void (async () => {
      try {
        const response = await new ListSessionsUseCase(consult).execute({ cursor });
        if (generation.current !== current) return;
        const now = Date.now();
        setSettled((previous) =>
          previous === null || previous.key !== taskKey
            ? previous
            : {
                ...previous,
                rows: [...previous.rows, ...response.items.map((item) => toConversationRow(item, now))],
                nextCursor: response.next_cursor,
              },
        );
      } catch (caught) {
        if (generation.current !== current) return;
        // 分页失败不清空已加载内容：错误只影响「更多」，入口与已有列表保持可用。
        // 按当前任务 key 归属（重新加载首页时会被清掉）。
        writeLoadMoreFault({ key: taskKey, failure: failureViewFor(caught) });
      } finally {
        loadingMoreRef.current = false;
        setLoadingMore(false);
      }
    })();
  };

  const retryLoadMore = (): void => {
    if (loadMoreFaultRef.current === null || loadMoreFaultRef.current.key !== taskKey) return;
    writeLoadMoreFault(null);
    loadMore();
  };

  const reload = (): void => {
    setSettled(null);
    setSettledError(null);
    writeLoadMoreFault(null);
    setLoadingMore(false);
    setAttempt((value) => value + 1);
  };

  const startNewConversation = async (): Promise<void> => {
    if (creatingRef.current) return;
    creatingRef.current = true;
    setCreating(true);
    setCreateFailure(null);
    try {
      const response = await new CreateSessionUseCase(consult).execute();
      onCreated(response.session_id, response.onboarding_pending);
    } catch (caught) {
      setCreateFailure(failureViewFor(caught));
    } finally {
      creatingRef.current = false;
      setCreating(false);
    }
  };

  return { state, loadMore, retryLoadMore, reload, startNewConversation, creating, createFailure };
}
