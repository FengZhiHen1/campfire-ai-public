/**
 * 模块: features/profile/viewModel/useProfilePage
 * 职责: 档案页的内容状态——对象列表、当前对象、摘要与两组条目、对象切换与重新加载
 * 数据来源:
 *   - docs/design/pages/档案页.md: MUST — 状态覆盖表（loading/empty/error、对象切换就地切换）
 *   - docs/技术设计/面/profile/档案面HTTP契约.md: MUST — 第 3 节（候选层单独成组）
 * 边界:
 *   - 依赖: features/profile/application、features/profile/domain
 *   - 被依赖: features/profile/view/ProfilePage 与同目录的两个交互 hook
 * 禁止行为:
 *   - 禁止在 view 里判断「哪条是候选」（分组由返回值决定，见 domain/items.isCandidate）
 *   - 禁止把单对象失败升级成整页失败（对象切换器必须保持可用）
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import type { ProfileItem, ProfileSummaryField, SupportObject } from '../../../shared/types/profile';
import type { ProfilePort } from '../application/ports';
import { LoadProfileUseCase, pickObjectId } from '../application/usecases';
import { type ProfileFailure, failureFromError } from '../domain/failures';

/** 页面级加载状态。 */
export type ProfileStatus = 'loading' | 'ready' | 'error';

/** 档案页内容状态与操作。 */
export interface ProfilePageState {
  hasMore: boolean;
  loadingMore: boolean;
  loadMoreFailure: ProfileFailure | null;
  loadMore(): Promise<void>;
  objects: SupportObject[];
  selectedObjectId: string | null;
  /** 当前对象是否已归档（归档对象可读、不可新增，契约第 1 节）。 */
  selectedArchived: boolean;
  summary: ProfileSummaryField[];
  hasProfile: boolean;
  items: ProfileItem[];
  candidates: ProfileItem[];
  status: ProfileStatus;
  failure: ProfileFailure | null;
  /** 切换对象：就地切换整页内容。 */
  selectObject(objectId: string): void;
  /** 重新加载对象列表与当前对象内容（新建/归档后的收口）。 */
  reload(): Promise<void>;
  /** 只重新加载当前对象的内容区（条目增删改后）。 */
  reloadObject(): Promise<void>;
}

/**
 * 档案页内容状态。
 *
 * 三件事分开持有：`objects`+`selectedObjectId`（切换器）、内容区（摘要与条目）、
 * 以及状态与失败。分开的理由是失败粒度不同——对象列表失败是整页错误，
 * 单对象内容失败只该让内容区报错（档案页状态覆盖表：「单对象失败不吞全局导航」）。
 */
export function useProfilePage(port: ProfilePort): ProfilePageState {
  const [objects, setObjects] = useState<SupportObject[]>([]);
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null);
  const [summary, setSummary] = useState<ProfileSummaryField[]>([]);
  const [hasProfile, setHasProfile] = useState(false);
  const [items, setItems] = useState<ProfileItem[]>([]);
  const [candidates, setCandidates] = useState<ProfileItem[]>([]);
  const [status, setStatus] = useState<ProfileStatus>('loading');
  const [failure, setFailure] = useState<ProfileFailure | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreFailure, setLoadMoreFailure] = useState<ProfileFailure | null>(null);
  const moreToken = useRef<number | null>(null);

  // 迟到的响应不得覆盖新的选择（CORE-03 身份守卫）：切换对象会并发发起请求，
  // 只认最后一次发起的那一个。用 ref 记住「当前最新的一次加载」的序号。
  const loadToken = useRef(0);

  const applyObjectContent = useCallback(
    async (objectId: string, token: number): Promise<void> => {
      const loader = new LoadProfileUseCase(port);
      const content = await loader.loadObject(objectId);
      if (loadToken.current !== token) return;
      setSummary(content.summary);
      setHasProfile(content.hasProfile);
      setItems(content.items);
      setCandidates(content.candidates);
      setCursor(content.nextCursor);
      setLoadingMore(false);
      setLoadMoreFailure(null);
      setStatus('ready');
      setFailure(null);
    },
    [port],
  );

  const loadAll = useCallback(
    async (preferred: string | null, options?: { initial?: boolean }): Promise<void> => {
      const token = loadToken.current + 1;
      loadToken.current = token;
      // 首次加载不做这一次同步重置：状态初值本来就是 loading/null，
      // 而在 effect 里同步 setState 会触发一次多余渲染（React 的
      // set-state-in-effect 规则禁止）。非首次（reload）走这条路是对的。
      if (options?.initial !== true) {
        setStatus('loading');
        setFailure(null);
      }
      try {
        const loader = new LoadProfileUseCase(port);
        const snapshot = await loader.execute(preferred);
        if (loadToken.current !== token) return;
        setObjects(snapshot.objects);
        setSelectedObjectId(snapshot.selectedObjectId);
        setSummary(snapshot.summary);
        setHasProfile(snapshot.hasProfile);
        setItems(snapshot.items);
        setCandidates(snapshot.candidates);
        setCursor(snapshot.nextCursor);
        setLoadingMore(false);
        setLoadMoreFailure(null);
        setStatus('ready');
      } catch (error) {
        if (loadToken.current !== token) return;
        setFailure(failureFromError(error));
        setStatus('error');
      }
    },
    [port],
  );

  useEffect(() => {
    // 首次加载：没有偏好对象，由用例取列表第一个。
    //
    // 豁免 set-state-in-effect 的理由：这是「挂载时向外部系统取数据」的经典场景，
    // 规则建议的替代（渲染期派生、事件驱动）都不适用——数据只能来自端口。
    // 首次加载路径上没有任何同步 setState（`initial: true` 跳过了状态重置），
    // 状态更新都发生在 await 之后；规则无法跨函数边界证明这一点，故在此显式豁免。
    // oxlint-disable-next-line react/set-state-in-effect
    void loadAll(null, { initial: true });
  }, [loadAll]);

  const selectObject = useCallback(
    (objectId: string): void => {
      if (objectId === selectedObjectId) return;
      setSelectedObjectId(objectId);
      setStatus('loading');
      setFailure(null);
      // 先清空内容再拉：留着上一个对象的内容会让「切换是浏览不是导航」变成
      // 一次内容错配（旧对象的条目显示在新对象名下）。
      setSummary([]);
      setItems([]);
      setCandidates([]);
      setCursor(null);
      setLoadingMore(false);
      setLoadMoreFailure(null);
      const token = loadToken.current + 1;
      loadToken.current = token;
      void applyObjectContent(objectId, token).catch((error: unknown) => {
        if (loadToken.current !== token) return;
        setFailure(failureFromError(error));
        setStatus('error');
      });
    },
    [applyObjectContent, selectedObjectId],
  );

  const reload = useCallback(async (): Promise<void> => {
    await loadAll(selectedObjectId);
  }, [loadAll, selectedObjectId]);

  const reloadObject = useCallback(async (): Promise<void> => {
    if (selectedObjectId === null) return;
    const token = loadToken.current + 1;
    loadToken.current = token;
    try {
      await applyObjectContent(selectedObjectId, token);
    } catch (error) {
      if (loadToken.current !== token) return;
      setFailure(failureFromError(error));
      setStatus('error');
    }
  }, [applyObjectContent, selectedObjectId]);

  // 选中对象是否已归档：对象不存在时按「未归档」处理（没有对象就没有归档语义），
  // 因此这里先判存在再判时间，而不是靠 `?.` 的 undefined 穿透。
  const selectedObject = objects.find((object) => object.id === selectedObjectId);

  const loadMore = async (): Promise<void> => {
    const token = loadToken.current;
    if (selectedObjectId === null || cursor === null || status !== 'ready' || moreToken.current === token) return;
    moreToken.current = token;
    setLoadingMore(true);
    setLoadMoreFailure(null);
    try {
      const next = await new LoadProfileUseCase(port).loadNextPage(selectedObjectId, cursor);
      if (loadToken.current !== token) return;
      setItems((current) => [...new Map([...current, ...next.items].map((item) => [item.item_id, item])).values()]);
      setCandidates((current) => [...new Map([...current, ...next.candidates].map((item) => [item.item_id, item])).values()]);
      setCursor(next.next_cursor);
    } catch (error) {
      if (loadToken.current === token) setLoadMoreFailure(failureFromError(error));
    } finally {
      if (moreToken.current === token) moreToken.current = null;
      if (loadToken.current === token) setLoadingMore(false);
    }
  };

  return {
    hasMore: cursor !== null,
    loadingMore,
    loadMoreFailure,
    loadMore,
    objects,
    selectedObjectId,
    selectedArchived: selectedObject !== undefined && selectedObject.archived_at !== null,
    summary,
    hasProfile,
    items,
    candidates,
    status,
    failure,
    selectObject,
    reload,
    reloadObject,
  };
}

/**
 * 由对象列表与偏好标识算出选中项；导出给测试直接断言选择规则。
 *
 * 这里只是转出用例层的规则，避免测试为了一个纯函数去构造整个 hook。
 */
export { pickObjectId };
