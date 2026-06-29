/**
 * CASE-09 案例管理逻辑 — 案例列表页 Hook。
 *
 * 封装 CasesIndex 页面的全部业务逻辑：分页查询、Tab 切换、搜索过滤、
 * 角色判定、菜单项、空状态文案。View 层仅负责 JSX 渲染。
 *
 * 调用路径：views/cases/pages/index → useCaseListPage → narrativeApi
 */

import { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
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
  activeTab: ActiveTab;
  searchKeyword: string;
  loading: boolean;
  error: string | null;
  allItems: NarrativeListItem[];
  filteredItems: NarrativeListItem[];
  hasMore: boolean;
  menuVisible: boolean;
  canSeeFAB: boolean;
  canSeeReviewBtn: boolean;
  canSeeMyTab: boolean;
  currentUserId: string;
  emptyState: EmptyState;
  menuItems: MenuItem[];
  setSearchKeyword: (kw: string) => void;
  setActiveTab: (tab: ActiveTab) => void;
  setMenuVisible: (v: boolean) => void;
  goDetail: (narrativeId: string) => void;
  goSubmit: () => void;
  goReview: () => void;
  refresh: () => void;
  loadMore: () => void;
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
  if (roles.includes('family')) return 'family';
  console.warn('[useCaseListPage] 未知角色静默降级为 family:', roles);
  return 'family';
}

// ============================================================================
// Hook
// ============================================================================

export function useCaseListPage(): UseCaseListPageReturn {
  const navigate = useNavigate();
  const user = useSessionStore((s) => s.user);
  const role: UserRole = useMemo(() => resolveRole(user?.roles), [user?.roles]);
  const currentUserId: string = user?.userId ?? '';

  const [activeTab, setActiveTab] = useState<ActiveTab>('public');
  const [searchKeyword, setSearchKeyword] = useState('');
  const [page, setPage] = useState(1);
  const [allItems, setAllItems] = useState<NarrativeListItem[]>([]);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [menuVisible, setMenuVisible] = useState(false);

  // ---- 数据请求 ----
  const loadData = useCallback(
    async (pageNum: number, append: boolean, scope: string, keyword?: string) => {
      setLoading(true);
      setError(null);
      try {
        const res = await listNarratives(scope, pageNum, 15, keyword);
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
    [],
  );

  // activeTab 变更时重新加载首页
  useEffect(() => {
    const scope = activeTab === 'public' ? 'public' : 'my';
    setPage(1);
    setAllItems([]);
    setHasMore(true);
    setSearchKeyword('');
    loadData(1, false, scope);
  }, [activeTab, loadData]);

  // 分页加载（page > 1 时 append）
  useEffect(() => {
    if (page === 1) return;
    const scope = activeTab === 'public' ? 'public' : 'my';
    loadData(page, true, scope, searchKeyword || undefined);
  }, [page]);

  // TODO: Replace useReachBottom with IntersectionObserver in View layer
  const loadMore = useCallback(() => {
    if (!loading && hasMore) {
      setPage((p) => p + 1);
    }
  }, [loading, hasMore]);

  // ---- 服务端搜索 ----
  useEffect(() => {
    const scope = activeTab === 'public' ? 'public' : 'my';
    const timer = setTimeout(() => {
      setPage(1);
      setAllItems([]);
      setHasMore(true);
      loadData(1, false, scope, searchKeyword || undefined);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchKeyword]);

  // 本地过滤仅作为兜底（服务端已支持搜索时此项仅返回 allItems）
  const filteredItems = useMemo(() => {
    if (!searchKeyword.trim()) return allItems;
    return allItems;
  }, [allItems, searchKeyword]);

  // ---- 事件处理 ----
  const goDetail = useCallback((narrativeId: string) => {
    navigate(`/cases/${narrativeId}`);
  }, [navigate]);

  const goSubmit = useCallback(() => {
    navigate('/cases/narrative');
  }, [navigate]);

  const goReview = useCallback(() => {
    navigate('/cases/review');
  }, [navigate]);

  const refresh = useCallback(() => {
    const scope = activeTab === 'public' ? 'public' : 'my';
    setPage(1);
    setAllItems([]);
    setHasMore(true);
    loadData(1, false, scope, searchKeyword || undefined);
  }, [loadData, activeTab, searchKeyword]);

  // ---- 角色相关 ----
  // TODO: 暂时关闭权限隔离，后续恢复
  const canSeeFAB = true; // role === 'teacher' || role === 'expert' || role === 'admin';
  const canSeeReviewBtn = true; // role === 'expert' || role === 'admin';
  const canSeeMyTab = true; // role !== 'family';

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
        subtitle: '案例库正在建设中，敬请期待',
        showClearBtn: false,
      };
    }
    return {
      title: '您还没有提交过案例',
      subtitle: '分享您的干预经验，帮助更多家庭',
      showClearBtn: false,
    };
  }, [searchKeyword, activeTab]);

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
    loadMore,
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
