import { View, Text, Button } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { useCaseDetailPage } from '../../../logics/cases';
import type { CardSummary } from '../../../logics/cases';
import './detail.scss';

// ============================================================================
// 组件：案例详情页（纯渲染层）
//
// 所有业务逻辑在 useCaseDetailPage Hook 中。
// 本组件只负责 JSX 渲染和事件绑定。
// ============================================================================

export default function CasesDetail() {
  const {
    data, loading, error,
    handleGoExtract, handleEditNarrative, handleCardClick, handleRetry,
    statusTextMap, statusClassMap, sourceLabelMap, cardStatusMap,
  } = useCaseDetailPage();

  // ---- 加载态 ----
  if (loading) {
    return (
      <View className="detail-page">
        <View className="detail-navbar">
          <Text className="detail-navbar__title">案例详情</Text>
        </View>
        <View className="detail-loading">
          <View className="detail-loading__skeleton" />
          <Text className="detail-loading__text">加载中…</Text>
        </View>
      </View>
    );
  }

  // ---- 错误态 ----
  if (error) {
    return (
      <View className="detail-page">
        <View className="detail-navbar">
          <Button className="detail-navbar__back" onClick={() => Taro.navigateBack()}>&larr;</Button>
          <Text className="detail-navbar__title">案例详情</Text>
        </View>
        <View className="detail-loading">
          <Text className="detail-loading__text">{error}</Text>
          <Button className="detail-actions__btn detail-actions__btn--primary" onClick={handleRetry}>
            重新加载
          </Button>
        </View>
      </View>
    );
  }

  // ---- 空数据态 ----
  if (!data) {
    return (
      <View className="detail-page">
        <View className="detail-navbar">
          <Button className="detail-navbar__back" onClick={() => Taro.navigateBack()}>&larr;</Button>
          <Text className="detail-navbar__title">案例详情</Text>
        </View>
        <View className="detail-loading">
          <Text className="detail-loading__text">未找到案例</Text>
        </View>
      </View>
    );
  }

  // ---- 正常态 ----
  const stClass = statusClassMap[data.status] || 'draft';
  const stText = statusTextMap[data.status] || data.status;
  const sourceLabel = sourceLabelMap[data.source_type] || data.source_type;
  const isDraft = data.status === 'draft';

  return (
    <View className="detail-page">
      {/* 导航栏 */}
      <View className="detail-navbar">
        <Text className="detail-navbar__title">案例详情</Text>
      </View>

      {/* 概览信息 */}
      <View className="detail-overview">
        <Text className="detail-overview__title">{data.title}</Text>
        <View className="detail-overview__tags">
          <Text className="detail-overview__tag detail-overview__tag--primary">{sourceLabel}</Text>
        </View>
        <View className="detail-overview__meta">
          <View className="detail-overview__status">
            <View className={`detail-overview__status-dot detail-overview__status-dot--${stClass}`} />
            <Text className="detail-overview__status-text">{stText}</Text>
          </View>
          {data.cards.length > 0 && (
            <Text className="detail-overview__card-count">{data.cards.length} 张卡片</Text>
          )}
        </View>
      </View>

      {/* 叙事原文 */}
      <View className="detail-section">
        <Text className="detail-section__title">叙事原文</Text>
        <View className="detail-section__content">
          <Text className="detail-section__text">{data.narrative}</Text>
        </View>
      </View>

      {/* 关联卡片 */}
      {data.cards && data.cards.length > 0 && (
        <View className="detail-section">
          <Text className="detail-section__title">关联卡片 ({data.cards.length})</Text>
          {data.cards.map((card: CardSummary) => {
            const cardStatus = cardStatusMap[card.review_status] || cardStatusMap.draft;
            return (
              <View
                key={card.card_id}
                className="detail-card-item"
                onClick={() => handleCardClick(card.card_id)}
              >
                <View className="detail-card-item__header">
                  <Text className="detail-card-item__title">{card.title}</Text>
                  <View className={`detail-card-item__status detail-card-item__status--${cardStatus.cls}`}>
                    <Text className="detail-card-item__status-text">{cardStatus.text}</Text>
                  </View>
                </View>
                <View className="detail-card-item__tags">
                  {card.behavior_type && <Text className="detail-card-item__tag">{card.behavior_type}</Text>}
                  {card.severity && <Text className="detail-card-item__tag">{card.severity}</Text>}
                  {card.scene && <Text className="detail-card-item__tag">{card.scene}</Text>}
                </View>
              </View>
            );
          })}
        </View>
      )}

      {/* 操作区 */}
      <View className="detail-actions">
        {isDraft && (
          <View className="detail-actions__panel">
            <Text className="detail-actions__panel-title">操作</Text>
            <Button className="detail-actions__btn detail-actions__btn--primary" onClick={handleGoExtract}>
              提取卡片
            </Button>
            <Button className="detail-actions__btn detail-actions__btn--secondary" onClick={handleEditNarrative}>
              编辑原文
            </Button>
          </View>
        )}
        {data.status === 'approved' && (
          <View className="detail-actions__result detail-actions__result--approved">
            <Text className="detail-actions__result-icon">&#10003;</Text>
            <Text className="detail-actions__result-text detail-actions__result-text--approved">该案例已通过审核</Text>
          </View>
        )}
      </View>
    </View>
  );
}
