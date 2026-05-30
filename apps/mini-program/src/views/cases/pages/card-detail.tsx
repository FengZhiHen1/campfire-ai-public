import { useState, useEffect, useCallback } from 'react';
import { View, Text, Button, ScrollView } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { getCard } from '../../../logics/cases/services/narrativeApi';
import MarkdownRenderer from '../../../logics/shared/components/MarkdownRenderer';
import './card-detail.scss';

interface CardDetail {
  card_id: string;
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
}

const QUARTET_SECTIONS = [
  { key: 'immediate_action', label: '即时安全干预动作', accent: 'immediate' },
  { key: 'comforting_phrase', label: '情绪安抚话术', accent: 'comforting' },
  { key: 'observation_metrics', label: '后续观察指标', accent: 'observation' },
  { key: 'medical_criteria', label: '就医判断标准', accent: 'medical' },
] as const;

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
      <View className="cd-page">
        <View className="cd-loading">
          <View className="cd-loading__skeleton" />
          <Text className="cd-loading__text">加载中…</Text>
        </View>
      </View>
    );
  }

  if (error || !data) {
    return (
      <View className="cd-page">
        <View className="cd-navbar">
          <Button className="cd-navbar__back" onClick={() => Taro.navigateBack()}>←</Button>
          <Text className="cd-navbar__title">案例卡片</Text>
        </View>
        <View className="cd-loading">
          <Text className="cd-loading__text">{error || '未找到案例卡片'}</Text>
          <Button className="cd-retry-btn" onClick={fetchCard}>重试</Button>
        </View>
      </View>
    );
  }

  return (
    <View className="cd-page">
      <View className="cd-navbar">
        <Button className="cd-navbar__back" onClick={() => Taro.navigateBack()}>←</Button>
        <Text className="cd-navbar__title">案例卡片</Text>
      </View>

      <ScrollView className="cd-scroll" scrollY>
        {/* 概览 */}
        <View className="cd-overview">
          <Text className="cd-overview__title">{data.title}</Text>
          <View className="cd-overview__tags">
            <Text className="cd-overview__tag">{data.behavior_type}</Text>
            <Text className="cd-overview__tag">{data.severity}</Text>
            <Text className="cd-overview__tag">{data.scene}</Text>
            {data.family_category && (
              <Text className="cd-overview__tag cd-overview__tag--category">{data.family_category}</Text>
            )}
          </View>
          <View className="cd-overview__meta">
            <Text className="cd-overview__meta-item">适用年龄: {data.age_range[0]}-{data.age_range[1]} 岁</Text>
            <Text className="cd-overview__meta-item">循证等级: {data.evidence_level}</Text>
          </View>
          {data.scenario && (
            <View className="cd-scenario">
              <Text className="cd-scenario__text">{data.scenario}</Text>
            </View>
          )}
        </View>

        {/* 四段式 */}
        {QUARTET_SECTIONS.map(({ key, label, accent }) => {
          const content = (data as unknown as Record<string, string>)[key];
          if (!content) return null;
          return (
            <View key={key} className="cd-quartet-card">
              <View className={`cd-quartet-card__accent cd-quartet-card__accent--${accent}`} />
              <View className="cd-quartet-card__body">
                <Text className={`cd-quartet-card__title cd-quartet-card__title--${accent}`}>{label}</Text>
                <View className="cd-quartet-card__content">
                  <MarkdownRenderer content={content} />
                </View>
              </View>
            </View>
          );
        })}

        {/* 注意事项 */}
        {data.caution_notes && (
          <View className="cd-section">
            <Text className="cd-section__title">注意事项</Text>
            <View className="cd-section__content">
              <MarkdownRenderer content={data.caution_notes} />
            </View>
          </View>
        )}

        {/* 禁忌人群 */}
        {data.contraindications && (
          <View className="cd-section">
            <Text className="cd-section__title">禁忌人群</Text>
            <View className="cd-section__content">
              <Text className="cd-section__text">{data.contraindications}</Text>
            </View>
          </View>
        )}

        {/* 循证标签 */}
        {data.ebp_labels.length > 0 && (
          <View className="cd-section">
            <Text className="cd-section__title">循证实践标签</Text>
            <View className="cd-tags">
              {data.ebp_labels.map((label) => (
                <Text key={label} className="cd-tags__item">{label}</Text>
              ))}
            </View>
          </View>
        )}
      </ScrollView>
    </View>
  );
}
