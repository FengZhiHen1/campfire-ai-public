import { View, Text, Button, Input } from '@tarojs/components';
import { useCaseListPage } from '../../../logics/cases';
import './index.scss';

// ============================================================================
// 组件：案例列表页（纯渲染层）
//
// 所有业务逻辑在 useCaseListPage Hook 中。
// 本组件只负责 JSX 渲染和事件绑定，不包含任何数据处理、API 调用或状态管理。
// ============================================================================

export default function CasesIndex() {
  const {
    activeTab, searchKeyword, loading, error, filteredItems, hasMore,
    menuVisible, canSeeFAB, canSeeReviewBtn, canSeeMyTab, currentUserId, emptyState, menuItems,
    setSearchKeyword, setActiveTab, setMenuVisible,
    goDetail, goSubmit, goReview, refresh,
    statusTextMap, statusClassMap, sourceLabelMap,
  } = useCaseListPage();

  return (
    <View className="cases-page">
      {/* 顶部导航栏 */}
      <View className="cases-navbar">
        <Text className="cases-navbar__title">真实案例库</Text>
        {canSeeReviewBtn && (
          <Button className="cases-navbar__review" onClick={goReview}>审核台</Button>
        )}
        <Button className="cases-navbar__menu-btn" onClick={() => setMenuVisible(!menuVisible)}>
          ···
        </Button>
        {menuVisible && (
          <View className="cases-navbar__menu">
            {menuItems.map((item, idx) => (
              <View key={idx} className="cases-navbar__menu-item" onClick={item.action}>
                <Text>{item.label}</Text>
              </View>
            ))}
          </View>
        )}
      </View>

      {/* Tab 切换 */}
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

      {/* 搜索栏 */}
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
            <Text className="cases-search__clear" onClick={() => setSearchKeyword('')}>×</Text>
          )}
        </View>
      </View>

      {/* 点击外部关闭菜单 */}
      {menuVisible && (
        <View className="cases-overlay" onClick={() => setMenuVisible(false)} />
      )}

      {/* 列表区域 */}
      <View className="cases-list">
        {/* 骨架屏 */}
        {loading && filteredItems.length === 0 && (
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
              <Button className="cases-empty__btn cases-empty__btn--text" onClick={() => setSearchKeyword('')}>
                清除搜索
              </Button>
            )}
            {!emptyState.showClearBtn && activeTab === 'my' && canSeeFAB && (
              <Button className="cases-empty__btn" onClick={goSubmit}>录入第一个案例</Button>
            )}
            {error && (
              <Button className="cases-empty__btn" onClick={refresh}>重新加载</Button>
            )}
          </View>
        )}

        {/* 案例列表 */}
        {filteredItems.map((item) => {
          const stClass = statusClassMap[item.status] || 'draft';
          const stText = statusTextMap[item.status] || item.status;
          const sourceLabel = sourceLabelMap[item.source_type] || item.source_type;
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
                  <Text className="case-card__tag case-card__tag--primary">{sourceLabel}</Text>
                  {isMine && (
                    <Text className="case-card__tag case-card__tag--mine">我</Text>
                  )}
                </View>
                <View className="case-card__footer">
                  <View className={`case-card__status-dot case-card__status-dot--${stClass}`} />
                  <Text className="case-card__status-text">{stText}</Text>
                  <Text className="case-card__time">{item.created_at?.slice(0, 10)}</Text>
                </View>
              </View>
            </View>
          );
        })}

        {/* 加载更多 */}
        {loading && filteredItems.length > 0 && (
          <View className="cases-load-more">
            <View className="cases-load-more__spinner" />
            <Text className="cases-load-more__text">加载中…</Text>
          </View>
        )}

        {/* 加载更多失败 — 且有已有数据时展示内联错误 */}
        {error && !loading && filteredItems.length > 0 && (
          <View className="cases-empty">
            <Text className="cases-empty__subtitle">{error}</Text>
            <Button className="cases-empty__btn" onClick={refresh}>重新加载</Button>
          </View>
        )}

        {/* 无更多 */}
        {!hasMore && !loading && !error && filteredItems.length > 0 && (
          <Text className="cases-no-more">—— 已展示全部案例 ——</Text>
        )}
      </View>

      {/* FAB */}
      {canSeeFAB && (
        <Button className="cases-fab" onClick={goSubmit}>+</Button>
      )}
    </View>
  );
}
