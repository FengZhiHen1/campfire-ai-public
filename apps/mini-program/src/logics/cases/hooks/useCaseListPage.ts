/**
 * CASE-09 案例管理逻辑 — 案例列表页 Hook。
 *
 * 封装 CasesIndex 页面的全部业务逻辑：分页查询、Tab 切换、搜索过滤、
 * 角色判定、菜单项、空状态文案。View 层仅负责 JSX 渲染。
 *
 * 调用路径：views/cases/pages/index → useCaseListPage → narrativeApi
 */

import { useState, useEffect, useMemo, useCallback } from 'react';
import Taro, { useReachBottom } from '@tarojs/taro';
import { listNarratives } from '../services/narrativeApi';
import { useSessionStore } from '../../shared/store/userStore';
import { STATUS_TEXT_MAP, STATUS_CLASS_MAP, SOURCE_LABEL_MAP } from '../types/constants';
import type { NarrativeListItem } from '../types';

// ============================================================================
// 类型定义
// ============================================================================

type UserRole = 'family' | 'teacher' | 'expert' | 'admin';

type ActiveTab = 'public' | 'my';

interface MenuItem {
  label: string;
  action: () => void;
}

interface EmptyState {
  title: string;
  subtitle: string;
  showClearBtn: boolean;
}

/** useCaseListPage 的返回值 */
export interface UseCaseListPageReturn {
  // 状态
  activeTab: ActiveTab;
  searchKeyword: string;
  loading: boolean;
  error: string | null;
  allItems: NarrativeListItem[];
  filteredItems: NarrativeListItem[];
  hasMore: boolean;
  menuVisible: boolean;
  // 角色相关
  canSeeFAB: boolean;
  canSeeReviewBtn: boolean;
  canSeeMyTab: boolean;
  currentUserId: string;
  // 空状态
  emptyState: EmptyState;
  // 菜单项
  menuItems: MenuItem[];
  // 操作
  setSearchKeyword: (kw: string) => void;
  setActiveTab: (tab: ActiveTab) => void;
  setMenuVisible: (v: boolean) => void;
  goDetail: (narrativeId: string) => void;
  goSubmit: () => void;
  goReview: () => void;
  refresh: () => void;
  // 常量映射（View 层渲染用）
  statusTextMap: Record<string, string>;
  statusClassMap: Record<string, string>;
  sourceLabelMap: Record<string, string>;
}

// ============================================================================
// 辅助函数
// ============================================================================

function resolveRole(roles?: string[]): UserRole {
  if (!roles || roles.length === 0) return 'family';
  if (roles.includes('admin')) return 'admin';
  if (roles.includes('expert')) return 'expert';
  if (roles.includes('teacher')) return 'teacher';
  return 'family';
}

// ============================================================================
// Hook
// ============================================================================

export function useCaseListPage(): UseCaseListPageReturn {
  // ---- 全局状态 ----
  const user = useSessionStore((s) => s.user);
  const role: UserRole = useMemo(() => resolveRole(user?.roles), [user?.roles]);
  const currentUserId: string = user?.userId ?? '';

  // ---- 本地状态 ----
  const [activeTab, setActiveTab] = useState<ActiveTab>(() =>
    role === 'family' ? 'public' : 'public',
  );
  const [searchKeyword, setSearchKeyword] = useState('');
  const [page, setPage] = useState(1);
  const [allItems, setAllItems] = useState<NarrativeListItem[]>([]);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [menuVisible, setMenuVisible] = useState(false);

  const scope = activeTab === 'public' ? 'public' : 'my';

  // ---- 数据请求 ----
  const loadData = useCallback(
    async (pageNum: number, append: boolean) => {
      setLoading(true);
      setError(null);
      try {
        const res = await listNarratives(scope, pageNum, 15);
        if (append) {
          setAllItems((prev) => [...prev, ...res.items]);
        } else {
          setAllItems(res.items);
        }
        setHasMore(res.items.length >= 15 && res.items.length + (pageNum - 1) * 15 < res.total);
      } catch {
        setError('加载失败，请稍后重试');
        if (!append) setAllItems([]);
      } finally {
        setLoading(false);
      }
    },
    [scope],
  );

  useEffect(() => {
    setPage(1);
    setAllItems([]);
    setHasMore(true);
    setSearchKeyword('');
    loadData(1, false);
  }, [activeTab, loadData]);

  useEffect(() => {
    if (page === 1) return;
    loadData(page, true);
  }, [page]);

  useReachBottom(() => {
    if (!loading && hasMore) {
      setPage((p) => p + 1);
    }
  });

  // ---- 前端搜索过滤 ----
  const filteredItems = useMemo(() => {
    if (!searchKeyword.trim()) return allItems;
    const kw = searchKeyword.trim().toLowerCase();
    return allItems.filter(
      (item) =>
        item.title.toLowerCase().includes(kw) ||
        item.source_type.toLowerCase().includes(kw),
    );
  }, [allItems, searchKeyword]);

  // ---- 事件处理 ----
  const goDetail = useCallback((narrativeId: string) => {
    Taro.navigateTo({ url: `/views/cases/pages/detail?narrativeId=${narrativeId}` });
  }, []);

  const goSubmit = useCallback(() => {
    Taro.navigateTo({ url: '/views/cases/pages/narrative-submit' });
  }, []);

  const goReview = useCallback(() => {
    Taro.navigateTo({ url: '/views/cases/pages/review' });
  }, []);

  const refresh = useCallback(() => {
    setPage(1);
    setAllItems([]);
    setHasMore(true);
    loadData(1, false);
  }, [loadData]);

  // ---- 角色相关 ----
  const canSeeFAB = role === 'teacher' || role === 'expert' || role === 'admin';
  const canSeeReviewBtn = role === 'expert' || role === 'admin';
  const canSeeMyTab = role !== 'family';

  // ---- 菜单项 ----
  const menuItems: MenuItem[] = useMemo(() => {
    const items: MenuItem[] = [];
    if (canSeeMyTab) {
      items.push({
        label: '我的投稿',
        action: () => { setActiveTab('my'); setMenuVisible(false); },
      });
      items.push({
        label: '草稿箱',
        action: () => { setActiveTab('my'); setMenuVisible(false); },
      });
    }
    if (canSeeReviewBtn) {
      items.push({
        label: '审核统计',
        action: () => { setMenuVisible(false); },
      });
    }
    return items;
  }, [canSeeMyTab, canSeeReviewBtn]);

  // ---- 空状态文案 ----
  const emptyState: EmptyState = useMemo(() => {
    if (searchKeyword) {
      return { title: '未找到匹配的案例', subtitle: '尝试更换关键词', showClearBtn: true };
    }
    if (activeTab === 'public') {
      return {
        title: '暂无已发布案例',
        subtitle: role === 'family'
          ? '专家团队正在审核案例中，请稍后再来'
          : '案例库正在建设中，敬请期待',
        showClearBtn: false,
      };
    }
    return {
      title: '您还没有提交过案例',
      subtitle: '分享您的干预经验，帮助更多家庭',
      showClearBtn: false,
    };
  }, [searchKeyword, activeTab, role]);

  return {
    activeTab,
    searchKeyword,
    loading,
    error,
    allItems,
    filteredItems,
    hasMore,
    menuVisible,
    canSeeFAB,
    canSeeReviewBtn,
    canSeeMyTab,
    currentUserId,
    emptyState,
    menuItems,
    setSearchKeyword,
    setActiveTab,
    setMenuVisible,
    goDetail,
    goSubmit,
    goReview,
    refresh,
    statusTextMap: STATUS_TEXT_MAP,
    statusClassMap: STATUS_CLASS_MAP,
    sourceLabelMap: SOURCE_LABEL_MAP,
  };
}
