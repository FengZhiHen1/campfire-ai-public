import { useState, useEffect } from 'react';
import { View, Text, Button } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { getNarrative, type NarrativeDetail, type CardSummary } from '../../../logics/cases/services/narrativeApi';
import './detail.scss';

// ============================================================================
// 常量
// ============================================================================

const STATUS_TEXT_MAP: Record<string, string> = {
  draft: '草稿',
  pending_review: '待审核',
  approved: '已通过',
  rejected: '已驳回',
};

const STATUS_CLASS_MAP: Record<string, string> = {
  draft: 'draft',
  pending_review: 'pending',
  approved: 'approved',
  rejected: 'rejected',
};

const SOURCE_LABEL_MAP: Record<string, string> = {
  '专家撰写': '专家',
  '机构脱敏': '机构',
  '工单沉淀': '工单',
  '家属分享': '家属',
};

const CARD_STATUS_MAP: Record<string, { text: string; cls: string }> = {
  draft: { text: '草稿', cls: 'draft' },
  pending_review: { text: '待审核', cls: 'pending' },
  approved: { text: '已通过', cls: 'approved' },
  rejected: { text: '已驳回', cls: 'rejected' },
};

// ============================================================================
// 组件
// ============================================================================

export default function CasesDetail() {
  const [data, setData] = useState<NarrativeDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const params = Taro.getCurrentInstance().router?.params;
    const narrativeId = params?.narrativeId;
    if (!narrativeId) return;

    setLoading(true);
    getNarrative(narrativeId)
      .then((res) => setData(res))
      .catch(() => Taro.showToast({ title: '加载失败', icon: 'none' }))
      .finally(() => setLoading(false));
  }, []);

  const handleGoExtract = () => {
    if (!data) return;
    Taro.navigateTo({ url: `/views/cases/pages/extraction-result?narrativeId=${data.narrative_id}` });
  };

  const handleEditNarrative = () => {
    if (!data) return;
    Taro.navigateTo({ url: `/views/cases/pages/narrative-submit?mode=edit&narrativeId=${data.narrative_id}` });
  };

  const handleCardClick = (cardId: string) => {
    Taro.navigateTo({ url: `/views/cases/pages/extraction-result?narrativeId=${data?.narrative_id}&cardId=${cardId}` });
  };

  // --------------------------------------------------------------------------
  // 加载态
  // --------------------------------------------------------------------------
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

  // --------------------------------------------------------------------------
  // 正常态
  // --------------------------------------------------------------------------
  const stClass = STATUS_CLASS_MAP[data.status] || 'draft';
  const stText = STATUS_TEXT_MAP[data.status] || data.status;
  const sourceLabel = SOURCE_LABEL_MAP[data.source_type] || data.source_type;
  const isOwner = data.author_id === 'current'; // simplified: narrative detail doesn't expose is_owner
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
          {data.card_count > 0 && (
            <Text className="detail-overview__card-count">{data.card_count} 张卡片</Text>
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
            const cardStatus = CARD_STATUS_MAP[card.review_status] || CARD_STATUS_MAP.draft;
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
                  {card.behavior_type && (
                    <Text className="detail-card-item__tag">{card.behavior_type}</Text>
                  )}
                  {card.severity && (
                    <Text className="detail-card-item__tag">{card.severity}</Text>
                  )}
                  {card.scene && (
                    <Text className="detail-card-item__tag">{card.scene}</Text>
                  )}
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
