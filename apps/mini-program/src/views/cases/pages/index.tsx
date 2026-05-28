import { useState, useEffect, useMemo, useCallback } from 'react';
import { View, Text, Button, Input } from '@tarojs/components';
import Taro, { useReachBottom } from '@tarojs/taro';
import type { CaseListItem } from '@campfire/ts-shared';
import { useCaseList } from '../../../logics/cases/hooks/useCaseList';
import { useSessionStore } from '../../../logics/shared/store/userStore';
import './index.scss';

// ============================================================================
// 常量定义
// ============================================================================

/** 用户角色 */
type UserRole = 'family' | 'teacher' | 'expert' | 'admin';

/** 行为类型选项 */
const BEHAVIOR_OPTIONS = [
  { label: '全部', value: '' },
  { label: '自伤行为', value: 'self_harm' },
  { label: '攻击行为', value: 'aggression' },
  { label: '逃跑/走失', value: 'elopement' },
  { label: '拒绝服药', value: 'medication_refusal' },
  { label: '情绪爆发', value: 'meltdown' },
  { label: '其他', value: 'other' },
];

/** 审核状态选项 */
const STATUS_OPTIONS = [
  { label: '全部', value: '' },
  { label: '草稿', value: 'draft' },
  { label: '审核中', value: 'pending_review' },
  { label: '已通过', value: 'approved' },
  { label: '已驳回', value: 'rejected' },
];

/** 循证等级选项 */
const EVIDENCE_OPTIONS = [
  { label: '全部', value: '' },
  { label: 'A级', value: 'A' },
  { label: 'B级', value: 'B' },
  { label: 'C级', value: 'C' },
  { label: 'D级', value: 'D' },
];

/** 排序方式 */
const SORT_OPTIONS = [
  { label: '最新发布', value: 'latest' },
  { label: '最高循证', value: 'evidence' },
  { label: '最多引用', value: 'cited' },
  { label: '最近更新', value: 'updated' },
];

/** 状态显示映射 */
const STATUS_TEXT_MAP: Record<string, string> = {
  draft: '草稿',
  pending_review: '审核中',
  approved: '已通过',
  rejected: '已驳回',
};

/** 状态样式映射 */
const STATUS_CLASS_MAP: Record<string, string> = {
  draft: 'draft',
  pending_review: 'pending',
  approved: 'approved',
  rejected: 'rejected',
};

/** 循证等级样式映射 */
const EVIDENCE_CLASS_MAP: Record<string, string> = {
  A: 'a',
  B: 'b',
  C: 'c',
  D: 'd',
};

// ============================================================================
// 辅助函数
// ============================================================================

/** 从 roles 数组解析主角色 */
function resolveRole(roles?: string[]): UserRole {
  if (!roles || roles.length === 0) return 'family';
  if (roles.includes('admin')) return 'admin';
  if (roles.includes('expert')) return 'expert';
  if (roles.includes('teacher')) return 'teacher';
  return 'family';
}

/** 格式化年龄范围（Mock：从 scene 推断或返回默认值） */
function formatAgeRange(item: CaseListItem): string {
  // TODO: backend 需在 CaseListItem 中返回 age_range
  const ageMap: Record<string, string> = {
    'home': '3-6岁',
    'school': '学龄期',
    'community': '青少年',
    'hospital': '全年龄',
  };
  return ageMap[item.scene] || '学龄期';
}

/** 获取循证等级（Mock：从 case_id 哈希或返回默认值） */
function getEvidenceLevel(item: CaseListItem): string {
  // TODO: backend 需在 CaseListItem 中返回 evidence_level
  const hash = item.case_id.charCodeAt(item.case_id.length - 1) % 4;
  return ['A', 'B', 'C', 'D'][hash];
}

/** 排序函数 */
function sortCases(items: CaseListItem[], sortBy: string): CaseListItem[] {
  const sorted = [...items];
  switch (sortBy) {
    case 'latest':
      return sorted.sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at));
    case 'updated':
      return sorted.sort((a, b) => +new Date(b.updated_at) - +new Date(a.updated_at));
    case 'evidence':
      return sorted.sort((a, b) => {
        const order = { A: 4, B: 3, C: 2, D: 1 };
        return (order[getEvidenceLevel(b) as keyof typeof order] || 0) - (order[getEvidenceLevel(a) as keyof typeof order] || 0);
      });
    case 'cited':
      // TODO: backend 需返回引用计数
      return sorted;
    default:
      return sorted;
  }
}

// ============================================================================
// 组件
// ============================================================================

export default function CasesIndex() {
  // --------------------------------------------------------------------------
  // 全局状态
  // --------------------------------------------------------------------------
  const user = useSessionStore((s) => s.user);
  const role = useMemo(() => resolveRole(user?.roles), [user?.roles]);
  const currentUserId = user?.userId ?? '';

  // --------------------------------------------------------------------------
  // 本地状态
  // --------------------------------------------------------------------------
  const [activeTab, setActiveTab] = useState<'public' | 'my'>(
    role === 'family' ? 'public' : 'public',
  );
  const [searchKeyword, setSearchKeyword] = useState('');
  const [behaviorFilter, setBehaviorFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [evidenceFilter, setEvidenceFilter] = useState('');
  const [sortBy, setSortBy] = useState('latest');
  const [page, setPage] = useState(1);
  const [allItems, setAllItems] = useState<CaseListItem[]>([]);
  const [hasMore, setHasMore] = useState(true);
  const [menuVisible, setMenuVisible] = useState(false);
  const [showFilterPanel, setShowFilterPanel] = useState<string | null>(null);

  // --------------------------------------------------------------------------
  // 数据请求
  // --------------------------------------------------------------------------
  const scope = activeTab === 'public' ? 'public' : 'my';

  const { data, loading, error, refresh } = useCaseList({
    status: statusFilter || undefined,
    behaviorType: behaviorFilter || undefined,
    scope,
    page,
    pageSize: 15,
  });

  // 数据到达后追加到 allItems
  useEffect(() => {
    if (data) {
      if (page === 1) {
        setAllItems(data.items);
      } else {
        setAllItems((prev) => [...prev, ...data.items]);
      }
      setHasMore(data.items.length >= 15 && data.items.length + (page - 1) * 15 < data.total);
    }
  }, [data]);

  // 筛选条件变化时重置分页
  useEffect(() => {
    setPage(1);
    setAllItems([]);
  }, [activeTab, behaviorFilter, statusFilter, evidenceFilter, sortBy, searchKeyword]);

  // 触底加载
  useReachBottom(() => {
    if (!loading && hasMore) {
      setPage((p) => p + 1);
    }
  });

  // --------------------------------------------------------------------------
  // 过滤与排序
  // --------------------------------------------------------------------------
  const filteredItems = useMemo(() => {
    let items = [...allItems];

    // 搜索过滤
    if (searchKeyword.trim()) {
      const kw = searchKeyword.trim().toLowerCase();
      items = items.filter(
        (item) =>
          item.title.toLowerCase().includes(kw) ||
          item.behavior_type.toLowerCase().includes(kw) ||
          item.scene.toLowerCase().includes(kw),
      );
    }

    // 循证等级过滤（前端过滤，因为 API 暂不支持）
    if (evidenceFilter) {
      items = items.filter((item) => getEvidenceLevel(item) === evidenceFilter);
    }

    // 排序
    items = sortCases(items, sortBy);

    return items;
  }, [allItems, searchKeyword, evidenceFilter, sortBy]);

  // --------------------------------------------------------------------------
  // 事件处理
  // --------------------------------------------------------------------------
  const goDetail = useCallback((caseId: string) => {
    Taro.navigateTo({ url: `/views/cases/pages/detail?caseId=${caseId}` });
  }, []);

  const goSubmit = useCallback(() => {
    Taro.navigateTo({ url: '/views/cases/pages/narrative-submit' });
  }, []);

  const goReview = useCallback(() => {
    Taro.navigateTo({ url: '/views/cases/pages/review' });
  }, []);

  const handleFilterSelect = (type: string, value: string) => {
    switch (type) {
      case 'behavior':
        setBehaviorFilter(value);
        break;
      case 'status':
        setStatusFilter(value);
        break;
      case 'evidence':
        setEvidenceFilter(value);
        break;
      case 'sort':
        setSortBy(value);
        break;
    }
    setShowFilterPanel(null);
  };

  const clearAllFilters = () => {
    setBehaviorFilter('');
    setStatusFilter('');
    setEvidenceFilter('');
    setSortBy('latest');
    setSearchKeyword('');
  };

  const hasActiveFilters = behaviorFilter || statusFilter || evidenceFilter || sortBy !== 'latest';

  // --------------------------------------------------------------------------
  // 角色相关渲染控制
  // --------------------------------------------------------------------------
  const canSeeFAB = role === 'teacher' || role === 'expert' || role === 'admin';
  const canSeeReviewBtn = role === 'expert' || role === 'admin';
  const canSeeStatusFilter = role !== 'family';
  const canSeeMyTab = role !== 'family';

  // --------------------------------------------------------------------------
  // 菜单项
  // --------------------------------------------------------------------------
  const menuItems = useMemo(() => {
    const items: { label: string; action: () => void }[] = [];
    if (role === 'teacher' || role === 'expert' || role === 'admin') {
      items.push({ label: '我的投稿', action: () => { setActiveTab('my'); setMenuVisible(false); } });
      items.push({ label: '草稿箱', action: () => { setStatusFilter('draft'); setActiveTab('my'); setMenuVisible(false); } });
    }
    items.push({ label: '我的收藏', action: () => { setMenuVisible(false); } });
    if (role === 'expert' || role === 'admin') {
      items.push({ label: '审核统计', action: () => { setMenuVisible(false); } });
    }
    return items;
  }, [role]);

  // --------------------------------------------------------------------------
  // 空状态文案
  // --------------------------------------------------------------------------
  const emptyState = useMemo(() => {
    if (searchKeyword || hasActiveFilters) {
      return {
        title: '未找到符合条件的案例',
        subtitle: '尝试更换筛选条件或关键词',
        showClearBtn: true,
      };
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
  }, [searchKeyword, hasActiveFilters, activeTab, role]);

  // --------------------------------------------------------------------------
  // 渲染
  // --------------------------------------------------------------------------
  return (
    <View className="cases-page">
      {/* ========== 顶部导航栏 ========== */}
      <View className="cases-navbar">
        <Button className="cases-navbar__back" onClick={() => Taro.navigateBack()}>
          &lt;
        </Button>
        <Text className="cases-navbar__title">真实案例库</Text>
        {canSeeReviewBtn && (
          <Button className="cases-navbar__review" onClick={goReview}>
            审核台
          </Button>
        )}
        <Button className="cases-navbar__menu-btn" onClick={() => setMenuVisible(!menuVisible)}>
          ···
        </Button>

        {/* 下拉菜单 */}
        {menuVisible && (
          <View className="cases-navbar__menu">
            {menuItems.map((item, idx) => (
              <View
                key={idx}
                className="cases-navbar__menu-item"
                onClick={item.action}
              >
                <Text>{item.label}</Text>
              </View>
            ))}
          </View>
        )}
      </View>

      {/* ========== Tab 切换 ========== */}
      {canSeeMyTab && (
        <View className="cases-tabs">
          <Button
            className={`cases-tabs__btn ${activeTab === 'public' ? 'cases-tabs__btn--active' : ''}`}
            onClick={() => setActiveTab('public')}
          >
            公共案例库
          </Button>
          <Button
            className={`cases-tabs__btn ${activeTab === 'my' ? 'cases-tabs__btn--active' : ''}`}
            onClick={() => setActiveTab('my')}
          >
            我的提交
          </Button>
        </View>
      )}

      {/* ========== 搜索栏 ========== */}
      <View className="cases-search">
        <View className="cases-search__input-wrap">
          <Text className="cases-search__icon">🔍</Text>
          <Input
            className="cases-search__input"
            type="text"
            placeholder="搜索案例库…"
            value={searchKeyword}
            onInput={(e) => setSearchKeyword(e.detail.value)}
          />
          {searchKeyword && (
            <Text className="cases-search__clear" onClick={() => setSearchKeyword('')}>
              ×
            </Text>
          )}
        </View>
      </View>

      {/* ========== 筛选栏 ========== */}
      <View className="cases-filters">
        {/* 行为类型 */}
        <Button
          className={`cases-filters__picker ${behaviorFilter ? 'cases-filters__picker--active' : ''}`}
          onClick={() => setShowFilterPanel(showFilterPanel === 'behavior' ? null : 'behavior')}
        >
          <Text className="cases-filters__picker-text">
            {BEHAVIOR_OPTIONS.find((o) => o.value === behaviorFilter)?.label || '行为类型'}
          </Text>
          <Text className="cases-filters__picker-chevron">▼</Text>
        </Button>

        {/* 审核状态 */}
        {canSeeStatusFilter && (
          <Button
            className={`cases-filters__picker ${statusFilter ? 'cases-filters__picker--active' : ''}`}
            onClick={() => setShowFilterPanel(showFilterPanel === 'status' ? null : 'status')}
          >
            <Text className="cases-filters__picker-text">
              {STATUS_OPTIONS.find((o) => o.value === statusFilter)?.label || '审核状态'}
            </Text>
            <Text className="cases-filters__picker-chevron">▼</Text>
          </Button>
        )}

        {/* 循证等级 */}
        <Button
          className={`cases-filters__picker ${evidenceFilter ? 'cases-filters__picker--active' : ''}`}
          onClick={() => setShowFilterPanel(showFilterPanel === 'evidence' ? null : 'evidence')}
        >
          <Text className="cases-filters__picker-text">
            {EVIDENCE_OPTIONS.find((o) => o.value === evidenceFilter)?.label || '循证等级'}
          </Text>
          <Text className="cases-filters__picker-chevron">▼</Text>
        </Button>

        {/* 排序 */}
        <Button
          className={`cases-filters__picker ${sortBy !== 'latest' ? 'cases-filters__picker--active' : ''}`}
          onClick={() => setShowFilterPanel(showFilterPanel === 'sort' ? null : 'sort')}
        >
          <Text className="cases-filters__picker-text">
            {SORT_OPTIONS.find((o) => o.value === sortBy)?.label || '排序'}
          </Text>
          <Text className="cases-filters__picker-chevron">▼</Text>
        </Button>
      </View>

      {/* 筛选下拉面板 */}
      {showFilterPanel && (
        <View className="cases-filter-panel">
          {(showFilterPanel === 'behavior' ? BEHAVIOR_OPTIONS :
            showFilterPanel === 'status' ? STATUS_OPTIONS :
            showFilterPanel === 'evidence' ? EVIDENCE_OPTIONS :
            SORT_OPTIONS
          ).map((opt) => (
            <View
              key={opt.value}
              className={`cases-filter-panel__item ${
                (showFilterPanel === 'behavior' && behaviorFilter === opt.value) ||
                (showFilterPanel === 'status' && statusFilter === opt.value) ||
                (showFilterPanel === 'evidence' && evidenceFilter === opt.value) ||
                (showFilterPanel === 'sort' && sortBy === opt.value)
                  ? 'cases-filter-panel__item--active'
                  : ''
              }`}
              onClick={() => handleFilterSelect(showFilterPanel, opt.value)}
            >
              <Text>{opt.label}</Text>
            </View>
          ))}
        </View>
      )}

      {/* 点击外部关闭筛选面板和菜单 */}
      {(showFilterPanel || menuVisible) && (
        <View
          className="cases-overlay"
          onClick={() => {
            setShowFilterPanel(null);
            setMenuVisible(false);
          }}
        />
      )}

      {/* ========== 列表区域 ========== */}
      <View className="cases-list">
        {/* 骨架屏 */}
        {loading && allItems.length === 0 && (
          <View className="cases-loading">
            <View className="cases-loading__skeleton" />
            <View className="cases-loading__skeleton" />
            <View className="cases-loading__skeleton" />
          </View>
        )}

        {/* 空状态 */}
        {!loading && filteredItems.length === 0 && (
          <View className="cases-empty">
            <View className="cases-empty__icon">
              <View className="cases-empty__illustration" />
            </View>
            <Text className="cases-empty__title">{emptyState.title}</Text>
            <Text className="cases-empty__subtitle">{emptyState.subtitle}</Text>
            {emptyState.showClearBtn && (
              <Button className="cases-empty__btn cases-empty__btn--text" onClick={clearAllFilters}>
                清除全部筛选
              </Button>
            )}
            {!emptyState.showClearBtn && activeTab === 'my' && canSeeFAB && (
              <Button className="cases-empty__btn" onClick={goSubmit}>
                录入第一个案例
              </Button>
            )}
            {error && (
              <Button className="cases-empty__btn" onClick={refresh}>
                重新加载
              </Button>
            )}
          </View>
        )}

        {/* 案例列表 */}
        {filteredItems.map((item) => {
          const stClass = STATUS_CLASS_MAP[item.status] || 'draft';
          const stText = STATUS_TEXT_MAP[item.status] || item.status;
          const evidenceLevel = getEvidenceLevel(item);
          const evClass = EVIDENCE_CLASS_MAP[evidenceLevel] || 'd';
          const ageLabel = formatAgeRange(item);
          const isMine = item.author_id === currentUserId;

          return (
            <View
              key={item.case_id}
              className="case-card"
              onClick={() => goDetail(item.case_id)}
            >
              <View className={`case-card__accent case-card__accent--${stClass}`} />
              <View className="case-card__body">
                <View className="case-card__header">
                  <Text className="case-card__title">{item.title}</Text>
                  <View className={`case-card__badge case-card__badge--${evClass}`}>
                    <Text className="case-card__badge-letter">{evidenceLevel}</Text>
                    <Text className="case-card__badge-level">级</Text>
                  </View>
                </View>

                <View className="case-card__tags">
                  <Text className="case-card__tag case-card__tag--primary">
                    {item.behavior_type || '其他'}
                  </Text>
                  <Text className="case-card__tag case-card__tag--default">
                    {ageLabel}
                  </Text>
                  {isMine && (
                    <Text className="case-card__tag case-card__tag--mine">我</Text>
                  )}
                </View>

                <View className="case-card__footer">
                  {role !== 'family' && (
                    <>
                      <View className={`case-card__status-dot case-card__status-dot--${stClass}`} />
                      <Text className="case-card__status-text">{stText}</Text>
                    </>
                  )}
                  <Text className="case-card__time">
                    {item.created_at?.slice(0, 10)}
                  </Text>
                </View>
              </View>
            </View>
          );
        })}

        {/* 加载更多指示器 */}
        {loading && allItems.length > 0 && (
          <View className="cases-load-more">
            <View className="cases-load-more__spinner" />
            <Text className="cases-load-more__text">加载中…</Text>
          </View>
        )}

        {/* 无更多数据 */}
        {!hasMore && !loading && filteredItems.length > 0 && (
          <Text className="cases-no-more">—— 已展示全部案例 ——</Text>
        )}
      </View>

      {/* ========== FAB ========== */}
      {canSeeFAB && (
        <Button className="cases-fab" onClick={goSubmit}>+</Button>
      )}
    </View>
  );
}
