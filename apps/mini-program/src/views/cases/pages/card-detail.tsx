import { useState, useEffect, useCallback } from 'react';
import { View, Text, Button, ScrollView } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { getCard } from '../../../logics/cases/services/narrativeApi';
import MarkdownRenderer from '../../../logics/shared/components/MarkdownRenderer';
import './card-detail.scss';

interface CardDetail {
  card_id: string;
  narrative_id: string;
  title: string;
  scenario: string;
  behavior_type: string;
  age_range: [number, number];
  severity: string;
  scene: string;
  ebp_labels: string[];
  family_category: string;
  immediate_action: string;
  comforting_phrase: string;
  observation_metrics: string;
  medical_criteria: string;
  evidence_level: string;
  caution_notes: string;
  contraindications: string;
  review_status: string;
  created_at: string;
}

const FAMILY_CATEGORY_MAP: Record<string, string> = {
  '环境调整': '环境调整',
  '沟通替代': '沟通替代',
  '行为塑造': '行为塑造',
  '危机安全': '危机安全',
  '社交引导': '社交引导',
  '自我管理': '自我管理',
};

export default function CardDetail() {
  const [data, setData] = useState<CardDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchCard = useCallback(() => {
    const params = Taro.getCurrentInstance().router?.params;
    const cardId = params?.cardId;
    if (!cardId) {
      setError('缺少卡片 ID');
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    getCard(cardId)
      .then((res) => setData(res as unknown as CardDetail))
      .catch(() => setError('加载失败，请稍后重试'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchCard();
  }, [fetchCard]);

  if (loading) {
    return (
      <View className="card-detail-page">
        <View className="card-detail-loading">
          <View className="card-detail-loading__skeleton" />
          <Text className="card-detail-loading__text">加载中…</Text>
        </View>
      </View>
    );
  }

  if (error || !data) {
    return (
      <View className="card-detail-page">
        <View className="card-detail-navbar">
          <Button className="card-detail-navbar__back" onClick={() => Taro.navigateBack()}>←</Button>
          <Text className="card-detail-navbar__title">案例卡片</Text>
        </View>
        <View className="card-detail-loading">
          <Text className="card-detail-loading__text">{error || '未找到案例卡片'}</Text>
          <Button className="card-detail-retry-btn" onClick={fetchCard}>重试</Button>
        </View>
      </View>
    );
  }

  return (
    <View className="card-detail-page">
      <View className="card-detail-navbar">
        <Button className="card-detail-navbar__back" onClick={() => Taro.navigateBack()}>←</Button>
        <Text className="card-detail-navbar__title">案例卡片</Text>
      </View>

      <ScrollView className="card-detail-scroll" scrollY>
        {/* 概览 */}
        <View className="card-detail-overview">
          <Text className="card-detail-overview__title">{data.title}</Text>
          <View className="card-detail-overview__tags">
            <Text className="card-detail-overview__tag">{data.behavior_type}</Text>
            <Text className="card-detail-overview__tag">{data.severity}</Text>
            <Text className="card-detail-overview__tag">{data.scene}</Text>
            {FAMILY_CATEGORY_MAP[data.family_category] && (
              <Text className="card-detail-overview__tag card-detail-overview__tag--category">{FAMILY_CATEGORY_MAP[data.family_category]}</Text>
            )}
          </View>
          <View className="card-detail-overview__meta">
            <Text className="card-detail-overview__meta-item">适用年龄: {data.age_range[0]}-{data.age_range[1]} 岁</Text>
            <Text className="card-detail-overview__meta-item">循证等级: {data.evidence_level}</Text>
          </View>
        </View>

        {/* 适用场景 */}
        <View className="card-detail-section">
          <Text className="card-detail-section__title">适用场景</Text>
          <View className="card-detail-section__content">
            <Text className="card-detail-section__text">{data.scenario}</Text>
          </View>
        </View>

        {/* 四段式干预建议 */}
        <View className="card-detail-section">
          <Text className="card-detail-section__title">即时安全干预动作</Text>
          <View className="card-detail-section__content">
            <MarkdownRenderer content={data.immediate_action} />
          </View>
        </View>

        <View className="card-detail-section">
          <Text className="card-detail-section__title">情绪安抚话术</Text>
          <View className="card-detail-section__content">
            <MarkdownRenderer content={data.comforting_phrase} />
          </View>
        </View>

        <View className="card-detail-section">
          <Text className="card-detail-section__title">后续观察指标</Text>
          <View className="card-detail-section__content">
            <MarkdownRenderer content={data.observation_metrics} />
          </View>
        </View>

        <View className="card-detail-section">
          <Text className="card-detail-section__title">就医判断标准</Text>
          <View className="card-detail-section__content">
            <MarkdownRenderer content={data.medical_criteria} />
          </View>
        </View>

        {/* 注意事项 */}
        {data.caution_notes && (
          <View className="card-detail-section">
            <Text className="card-detail-section__title">注意事项</Text>
            <View className="card-detail-section__content">
              <MarkdownRenderer content={data.caution_notes} />
            </View>
          </View>
        )}

        {/* 禁忌人群 */}
        {data.contraindications && (
          <View className="card-detail-section">
            <Text className="card-detail-section__title">禁忌人群</Text>
            <View className="card-detail-section__content">
              <Text className="card-detail-section__text">{data.contraindications}</Text>
            </View>
          </View>
        )}

        {/* 循证标签 */}
        {data.ebp_labels.length > 0 && (
          <View className="card-detail-section">
            <Text className="card-detail-section__title">循证实践标签</Text>
            <View className="card-detail-tags">
              {data.ebp_labels.map((label) => (
                <Text key={label} className="card-detail-tags__item">{label}</Text>
              ))}
            </View>
          </View>
        )}
      </ScrollView>
    </View>
  );
}
