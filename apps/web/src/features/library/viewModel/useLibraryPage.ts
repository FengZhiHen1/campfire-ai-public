/**
 * 模块: features/library/viewModel/useLibraryPage
 * 职责: 案例库浏览页状态——库别分区、检索（防抖）、就地展开、触底分页与 deep-link 三态
 * 数据来源:
 *   - docs/design/pages/案例库浏览页.md: MUST — 状态覆盖表（检索失败与空结果可区分、deep-link 三态）
 *   - docs/技术设计/面/profile/资料库面HTTP契约.md: MUST — 第 3、4、5 节
 * 边界:
 *   - 依赖: features/library/application、features/library/domain
 *   - 被依赖: features/library/view/LibraryPage
 * 禁止行为:
 *   - 禁止按前端缓存的旧载荷判断撤下（撤下判定来自服务端，契约第 5 节）
 *   - 禁止在检索失败时清空已输入词（案例库浏览页状态覆盖表）
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import type { LibraryListItem, LibraryKind } from '../../../shared/types/library';
import type { LibraryPort } from '../application/ports';
import { ResolveDeepLinkUseCase, SearchLibraryUseCase } from '../application/usecases';
import { type DeepLinkOutcome, parseDeepLink } from '../domain/deepLink';
import { type LibraryFailure, failureFromError } from '../domain/failures';

/** 页面加载状态。 */
export type LibraryStatus = 'loading' | 'ready' | 'error';

/** 检索防抖时长：检索是即输即查，但每次按键都发请求会打满检索链。 */
export const SEARCH_DEBOUNCE_MS = 250;

/** 案例库浏览页状态与操作。 */
export interface LibraryPageState {
  library: LibraryKind;
  /** 输入框里的词（立即回显）。 */
  query: string;
  items: LibraryListItem[];
  status: LibraryStatus;
  failure: LibraryFailure | null;
  loadingMore: boolean;
  hasMore: boolean;
  /**
   * 触底分页的失败。
   *
   * 与整页 `failure` 分开：分页失败不改整页状态（已取到的结果仍然有效），
   * 而错误卡只在整页失败态渲染——两者混用会让分页失败在界面上零反馈。
   */
  loadMoreFailure: LibraryFailure | null;
  /** 当前展开的条目标识；一次只展开一条（契约第 4 节）。 */
  expandedId: string | null;
  /** deep-link 的结果；`none` 表示普通进入。 */
  deepLink: DeepLinkOutcome;

  setLibrary(kind: LibraryKind): void;
  setQuery(value: string): void;
  reload(): Promise<void>;
  loadMore(): Promise<void>;
  toggleExpand(itemId: string): Promise<void>;
}

/**
 * 案例库浏览页状态。
 *
 * @param port 资料库端口
 * @param search URL 查询串（`?item=` / `?section=`）；由调用方从路由读入，
 *   使本 hook 不依赖 react-router（viewModel 只接数据）。
 */
export function useLibraryPage(port: LibraryPort, search: string): LibraryPageState {
  // 进入参数只解析一次，并作为初始 state 的输入：用 ref 存它会在渲染期读 ref
  // （React 的 refs 规则不许），而惰性 initializer 天然只跑一次。
  const [initialRequest] = useState(() => parseDeepLink(search));
  const [library, setLibraryState] = useState<LibraryKind>(initialRequest.section ?? 'case');
  const [query, setQueryState] = useState('');
  const [items, setItems] = useState<LibraryListItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [status, setStatus] = useState<LibraryStatus>('loading');
  const [failure, setFailure] = useState<LibraryFailure | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreFailure, setLoadMoreFailure] = useState<LibraryFailure | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [deepLink, setDeepLink] = useState<DeepLinkOutcome>({ kind: 'none' });

  // 迟到的响应不得覆盖新结果（CORE-03 身份守卫）：检索、切库、展开、分页都可能并发。
  const loadToken = useRef(0);
  const firstRun = useRef(true);
  // 展开态的镜像。自动取数（改词、deep-link 切库别）必须带上它：一次不带 expand 的
  // 自动取会用「不含正文」的结果替换列表，而 expandedId 还挂着——行看着是展开的、
  // 正文却是空的。读 state 做不到（那会把 expandedId 变成自动取数的依赖，展开/收起
  // 各多打一次请求），故用 ref 记住它。
  const expandedIdRef = useRef<string | null>(null);

  /** 置展开态：state 与镜像一起改，保证随后的取数看得到这次变更。 */
  const applyExpandedId = useCallback((itemId: string | null): void => {
    expandedIdRef.current = itemId;
    setExpandedId(itemId);
  }, []);

  /** 取第一页并按需展开一条。 */
  const load = useCallback(
    async (options?: { expand?: string; library?: LibraryKind }): Promise<void> => {
      const token = loadToken.current + 1;
      loadToken.current = token;
      // 未显式给 expand 就取当前展开态（收起时镜像已是 null，于是这一项自然消失）。
      const expand = options?.expand ?? expandedIdRef.current;
      // 库别同理：deep-link 判定为「在库」后要按目标库别取，而此刻 state 里的
      // `library` 还是切换前的值，闭包读不到新值。
      const targetLibrary = options?.library ?? library;
      setStatus('loading');
      setFailure(null);
      // 重取本页后上一轮的触底失败不再适用：新的一页会给出新的尾部形态。
      setLoadMoreFailure(null);
      try {
        const page = await new SearchLibraryUseCase(port).execute({
          library: targetLibrary,
          query,
          ...(expand !== null ? { expand } : {}),
        });
        if (loadToken.current !== token) return;
        setItems(page.items);
        setCursor(page.nextCursor);
        setStatus('ready');
      } catch (error) {
        if (loadToken.current !== token) return;
        setFailure(failureFromError(error));
        setStatus('error');
      }
    },
    [library, port, query],
  );

  useEffect(() => {
    // 首次进入立刻取（0ms 仍然是异步回调，不在 effect 体里同步 setState）；
    // 之后每次改词/换库都走防抖。
    const delay = firstRun.current ? 0 : SEARCH_DEBOUNCE_MS;
    const timer = setTimeout(() => {
      firstRun.current = false;
      void load();
    }, delay);
    return () => {
      clearTimeout(timer);
    };
  }, [load]);

  // deep-link 只解析一次：URL 变化由路由重挂页面承担。`load` 会随检索词/库别换身份，
  // 因此不能靠依赖数组限制次数——没有这道闸，每次按键都会重新解析一次 deep-link，
  // 并把使用者刚收起的展开态重新撑开。
  const deepLinkResolved = useRef(false);

  useEffect(() => {
    if (deepLinkResolved.current) return;
    const request = initialRequest;
    if (request.itemId === null) return;
    deepLinkResolved.current = true;
    void new ResolveDeepLinkUseCase(port)
      .execute(request.itemId)
      .then((outcome) => {
        setDeepLink(outcome);
        if (outcome.kind !== 'in-library') return;
        // 「定位并展开」两半都要做：按目标条目的库别切分区，并按 `expand=<item_id>`
        // 重取本页。只置 expandedId 不动列表的话，展开内容永远不会出现——
        // 展开内容随列表返回，而不是随单条查询返回（契约第 4 节）。
        applyExpandedId(outcome.item.item_id);
        setLibraryState(outcome.item.library);
        void load({ library: outcome.item.library });
      })
      .catch(() => {
        // 单条查询失败不改变整页：按普通进入处理（契约第 5 节：非法 id 不报错、不留在空页）。
        setDeepLink({ kind: 'none' });
      });
  }, [applyExpandedId, initialRequest, load, port]);

  const setLibrary = useCallback(
    (kind: LibraryKind): void => {
      setLibraryState(kind);
      // 换库要收起展开态：展开内容是上一条的，跨库保留会错配。
      applyExpandedId(null);
    },
    [applyExpandedId],
  );

  const setQuery = useCallback((value: string): void => {
    setQueryState(value);
  }, []);

  const reload = useCallback(async (): Promise<void> => {
    await load(expandedId === null ? undefined : { expand: expandedId });
  }, [expandedId, load]);

  const loadMore = useCallback(async (): Promise<void> => {
    if (cursor === null || loadingMore) return;
    setLoadingMore(true);
    // 重试即清除上一次的失败：尾部回到「正在加载」，失败再出现时又是新的一次。
    setLoadMoreFailure(null);
    try {
      const page = await new SearchLibraryUseCase(port).execute({ library, query, cursor });
      setItems((current) => [...current, ...page.items]);
      setCursor(page.nextCursor);
    } catch (error) {
      // 触底失败不改整页：已取到的结果仍然有效，游标留在原处让使用者再试。
      // 失败落在自己的状态上——整页 `failure` 只在 status==='error' 时渲染错误卡，
      // 写进那里等于把这次失败藏起来。
      setLoadMoreFailure(failureFromError(error));
    } finally {
      setLoadingMore(false);
    }
  }, [cursor, library, loadingMore, port, query]);

  const toggleExpand = useCallback(
    async (itemId: string): Promise<void> => {
      if (expandedId === itemId) {
        // 收起：镜像先归零，随后这次取数就不带 expand。
        applyExpandedId(null);
        await load();
        return;
      }
      applyExpandedId(itemId);
      // 展开内容随列表返回（契约第 4 节），因此这里必须重取一次带 expand 的列表。
      await load({ expand: itemId });
    },
    [applyExpandedId, expandedId, load],
  );

  return {
    library,
    query,
    items,
    status,
    failure,
    loadingMore,
    hasMore: cursor !== null,
    loadMoreFailure,
    expandedId,
    deepLink,
    setLibrary,
    setQuery,
    reload,
    loadMore,
    toggleExpand,
  };
}
