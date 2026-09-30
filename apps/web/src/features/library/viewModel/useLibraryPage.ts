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

import type { ExpandedLibraryItem, LibraryKind } from '../../../shared/types/library';
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
  items: ExpandedLibraryItem[];
  status: LibraryStatus;
  failure: LibraryFailure | null;
  loadingMore: boolean;
  hasMore: boolean;
  /** 当前展开的条目标识；一次只展开一条（契约第 4 节）。 */
  expandedId: string | null;
  /** deep-link 的结果；`none` 表示普通进入。 */
  deepLink: DeepLinkOutcome;

  setLibrary(kind: LibraryKind): void;
  setQuery(value: string): void;
  reload(): Promise<void>;
  loadMore(): Promise<void>;
  toggleExpand(itemId: string): Promise<void>;
  dismissDeepLinkCard(): void;
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
  const [items, setItems] = useState<ExpandedLibraryItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [status, setStatus] = useState<LibraryStatus>('loading');
  const [failure, setFailure] = useState<LibraryFailure | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [deepLink, setDeepLink] = useState<DeepLinkOutcome>({ kind: 'none' });

  // 迟到的响应不得覆盖新结果（CORE-03 身份守卫）：检索、切库、展开、分页都可能并发。
  const loadToken = useRef(0);
  const firstRun = useRef(true);

  /** 取第一页并按需展开一条。 */
  const load = useCallback(
    async (options?: { expand?: string | null }): Promise<void> => {
      const token = loadToken.current + 1;
      loadToken.current = token;
      setStatus('loading');
      setFailure(null);
      try {
        const page = await new SearchLibraryUseCase(port).execute({
          library,
          query,
          ...(options?.expand !== undefined && options.expand !== null ? { expand: options.expand } : {}),
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

  useEffect(() => {
    // deep-link：只解析一次进入参数（URL 变化由路由重挂页面承担）。
    const request = initialRequest;
    if (request.itemId === null) return;
    void new ResolveDeepLinkUseCase(port)
      .execute(request.itemId)
      .then((outcome) => {
        setDeepLink(outcome);
        if (outcome.kind === 'in-library') {
          // 按目标条目的库别切分区：citation 跳转要落在它所属的库里。
          setLibraryState(outcome.item.library);
          setExpandedId(outcome.item.item_id);
        }
      })
      .catch(() => {
        // 单条查询失败不改变整页：按普通进入处理（契约第 5 节：非法 id 不报错、不留在空页）。
        setDeepLink({ kind: 'none' });
      });
  }, [initialRequest, port]);

  const setLibrary = useCallback((kind: LibraryKind): void => {
    setLibraryState(kind);
    // 换库要收起展开态：展开内容是上一条的，跨库保留会错配。
    setExpandedId(null);
  }, []);

  const setQuery = useCallback((value: string): void => {
    setQueryState(value);
  }, []);

  const reload = useCallback(async (): Promise<void> => {
    await load(expandedId === null ? undefined : { expand: expandedId });
  }, [expandedId, load]);

  const loadMore = useCallback(async (): Promise<void> => {
    if (cursor === null || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await new SearchLibraryUseCase(port).execute({ library, query, cursor });
      setItems((current) => [...current, ...page.items]);
      setCursor(page.nextCursor);
    } catch (error) {
      // 触底失败不改整页：已取到的结果仍然有效，游标留在原处让使用者再试。
      setFailure(failureFromError(error));
    } finally {
      setLoadingMore(false);
    }
  }, [cursor, library, loadingMore, port, query]);

  const toggleExpand = useCallback(
    async (itemId: string): Promise<void> => {
      if (expandedId === itemId) {
        // 收起：重新取一遍不带 expand 的第一页。
        setExpandedId(null);
        await load();
        return;
      }
      setExpandedId(itemId);
      // 展开内容随列表返回（契约第 4 节），因此这里必须重取一次带 expand 的列表。
      await load({ expand: itemId });
    },
    [expandedId, load],
  );

  const dismissDeepLinkCard = useCallback((): void => {
    setDeepLink({ kind: 'none' });
  }, []);

  return {
    library,
    query,
    items,
    status,
    failure,
    loadingMore,
    hasMore: cursor !== null,
    expandedId,
    deepLink,
    setLibrary,
    setQuery,
    reload,
    loadMore,
    toggleExpand,
    dismissDeepLinkCard,
  };
}
