import { useState, useEffect, useMemo, useCallback } from 'react';
import { View, Text, Button, Input } from '@tarojs/components';
import Taro, { useReachBottom } from '@tarojs/taro';
import { listNarratives, type NarrativeListItem } from '../../../logics/cases/services/narrativeApi';
import { useSessionStore } from '../../../logics/shared/store/userStore';
import './index.scss';

// ============================================================================
// 常量定义
// ============================================================================

type UserRole = 'family' | 'teacher' | 'expert' | 'admin';

/** 状态显示映射 */
const STATUS_TEXT_MAP: Record<string, string> = {
  draft: '草稿',
  pending_review: '待审核',
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

/** 来源类型标签 */
const SOURCE_LABEL_MAP: Record<string, string> = {
  '专家撰写': '专家',
  '机构脱敏': '机构',
  '工单沉淀': '工单',
  '家属分享': '家属',
};

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
  const [activeTab, setActiveTab] = useState<'public' | 'my'>(() =>
    role === 'family' ? 'public' : 'public',
  );
  const [searchKeyword, setSearchKeyword] = useState('');
  const [page, setPage] = useState(1);
  const [allItems, setAllItems] = useState<NarrativeListItem[]>([]);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [menuVisible, setMenuVisible] = useState(false);

  // --------------------------------------------------------------------------
  // 数据请求
  // --------------------------------------------------------------------------
  const scope = activeTab === 'public' ? 'public' : 'my';

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

  // Tab 切换时重置
  useEffect(() => {
    setPage(1);
    setAllItems([]);
    setHasMore(true);
    setSearchKeyword('');
    loadData(1, false);
  }, [activeTab, loadData]);

  // 分页变化时加载
  useEffect(() => {
    if (page === 1) return; // 已在 activeTab 变化时处理
    loadData(page, true);
  }, [page]);

  // 触底加载
  useReachBottom(() => {
    if (!loading && hasMore) {
      setPage((p) => p + 1);
    }
  });

  // --------------------------------------------------------------------------
  // 前端搜索过滤
  // --------------------------------------------------------------------------
  const filteredItems = useMemo(() => {
    if (!searchKeyword.trim()) return allItems;
    const kw = searchKeyword.trim().toLowerCase();
    return allItems.filter(
      (item) =>
        item.title.toLowerCase().includes(kw) ||
        item.source_type.toLowerCase().includes(kw),
    );
  }, [allItems, searchKeyword]);

  // --------------------------------------------------------------------------
  // 事件处理
  // --------------------------------------------------------------------------
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

  // --------------------------------------------------------------------------
  // 角色相关
  // --------------------------------------------------------------------------
  const canSeeFAB = role === 'teacher' || role === 'expert' || role === 'admin';
  const canSeeReviewBtn = role === 'expert' || role === 'admin';
  const canSeeMyTab = role !== 'family';

  // --------------------------------------------------------------------------
  // 菜单项
  // --------------------------------------------------------------------------
  const menuItems = useMemo(() => {
    const items: { label: string; action: () => void }[] = [];
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

  // --------------------------------------------------------------------------
  // 空状态文案
  // --------------------------------------------------------------------------
  const emptyState = useMemo(() => {
    if (searchKeyword) {
      return {
        title: '未找到匹配的案例',
        subtitle: '尝试更换关键词',
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
  }, [searchKeyword, activeTab, role]);

  // --------------------------------------------------------------------------
  // 渲染
  // --------------------------------------------------------------------------
  return (
    <View className="cases-page">
      {/* ========== 顶部导航栏 ========== */}
      <View className="cases-navbar">
        <Text className="cases-navbar__title">真实案例库</Text>
        {canSeeReviewBtn && (
          <Button className="cases-navbar__review" onClick={goReview}>
            审核台
          </Button>
        )}
        <Button className="cases-navbar__menu-btn" onClick={() => setMenuVisible(!menuVisible)}>
          ···
        </Button>

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

      {/* 点击外部关闭菜单 */}
      {menuVisible && (
        <View className="cases-overlay" onClick={() => setMenuVisible(false)} />
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
              <Button
                className="cases-empty__btn cases-empty__btn--text"
                onClick={() => { setSearchKeyword(''); }}
              >
                清除搜索
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
          const sourceLabel = SOURCE_LABEL_MAP[item.source_type] || item.source_type;
          const isMine = item.author_id === currentUserId;

          return (
            <View
              key={item.narrative_id}
              className="case-card"
              onClick={() => goDetail(item.narrative_id)}
            >
              <View className={`case-card__accent case-card__accent--${stClass}`} />
              <View className="case-card__body">
                <View className="case-card__header">
                  <Text className="case-card__title">{item.title}</Text>
                  {item.card_count > 0 && (
                    <View className="case-card__badge case-card__badge--d">
                      <Text className="case-card__badge-letter">{item.card_count}</Text>
                      <Text className="case-card__badge-level">卡</Text>
                    </View>
                  )}
                </View>

                <View className="case-card__tags">
                  <Text className="case-card__tag case-card__tag--primary">
                    {sourceLabel}
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

        {/* 加载更多 */}
        {loading && allItems.length > 0 && (
          <View className="cases-load-more">
            <View className="cases-load-more__spinner" />
            <Text className="cases-load-more__text">加载中…</Text>
          </View>
        )}

        {/* 无更多 */}
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
