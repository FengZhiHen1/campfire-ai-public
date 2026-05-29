import { useState, useEffect } from 'react';
import { View, Text, Button } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { consultApi } from '../../../logics/consult/services/consultApi';
import type { ConsultationHistoryDetail } from '../../../logics/consult/types';
import './detail.scss';

export default function ConsultDetail() {
  const [data, setData] = useState<ConsultationHistoryDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const instance = Taro.getCurrentInstance();
    const id = instance.router?.params?.id;
    if (!id) {
      setError('缺少咨询记录 ID');
      setLoading(false);
      return;
    }
    consultApi
      .fetchHistoryDetail(id)
      .then((res) => setData(res))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : '加载失败'))
      .finally(() => setLoading(false));
  }, []);

  const getLevelClass = (level: string) => {
    if (level === 'severe') return 'high';
    if (level === 'moderate') return 'medium';
    return 'low';
  };

  const getLevelText = (level: string) => {
    if (level === 'severe') return '重度危机';
    if (level === 'moderate') return '中度危机';
    return '轻度';
  };

  const parsePlanParagraphs = (planText: string): string[] => {
    if (!planText) return [];
    return planText
      .split(/\n\n+/)
      .map((p) => p.trim())
      .filter(Boolean);
  };

  // -------------------- 加载态 --------------------
  if (loading) {
    return (
      <View className="detail-page">
        <View className="detail-navbar">
          <Button className="detail-navbar__back" onClick={() => Taro.navigateBack()}>←</Button>
          <Text className="detail-navbar__title">咨询详情</Text>
        </View>
        <View className="detail-loading">
          <View className="detail-loading__skeleton" />
          <View className="detail-loading__skeleton" />
          <View className="detail-loading__skeleton" />
        </View>
      </View>
    );
  }

  // -------------------- 错误态 --------------------
  if (error || !data) {
    return (
      <View className="detail-page">
        <View className="detail-navbar">
          <Button className="detail-navbar__back" onClick={() => Taro.navigateBack()}>←</Button>
          <Text className="detail-navbar__title">咨询详情</Text>
        </View>
        <View className="detail-error">
          <Text className="detail-error__icon">📡</Text>
          <Text className="detail-error__title">加载失败</Text>
          <Text className="detail-error__subtitle">{error || '未知错误'}</Text>
          <Button className="detail-error__btn" onClick={() => Taro.navigateBack()}>返回</Button>
        </View>
      </View>
    );
  }

  const levelKey = getLevelClass(data.crisis_level);
  const levelText = getLevelText(data.crisis_level);
  const paragraphs = parsePlanParagraphs(data.generated_plan);

  return (
    <View className="detail-page">
      {/* 导航栏 */}
      <View className="detail-navbar">
        <Button className="detail-navbar__back" onClick={() => Taro.navigateBack()}>←</Button>
        <Text className="detail-navbar__title">咨询详情</Text>
      </View>

      {/* 咨询概要 */}
      <View className="detail-header">
        <View className="detail-header__meta">
          <View className={`detail-header__level detail-header__level--${levelKey}`}>
            <View className={`detail-header__level-dot detail-header__level-dot--${levelKey}`} />
            <Text className={`detail-header__level-text detail-header__level-text--${levelKey}`}>
              {levelText}
            </Text>
          </View>
          <Text className="detail-header__time">{data.consultation_time}</Text>
        </View>
        <Text className="detail-header__behavior">{data.behavior_description}</Text>
      </View>

      {/* 生成方案 */}
      <View className="detail-plan">
        <Text className="detail-plan__title">应急干预方案</Text>
        {paragraphs.length > 0 ? (
          paragraphs.map((p, idx) => (
            <Text key={idx} className="detail-plan__para">{p}</Text>
          ))
        ) : (
          <Text className="detail-plan__empty">暂无方案内容</Text>
        )}
      </View>

      {/* 免责声明 */}
      <View className="detail-disclaimer">
        <Text className="detail-disclaimer__icon">ℹ️</Text>
        <Text className="detail-disclaimer__text">{data.disclaimer}</Text>
      </View>

      {/* 生成元信息 */}
      <View className="detail-meta-footer">
        <Text className="detail-meta-footer__item">
          生成耗时 {(data.generation_time_ms / 1000).toFixed(1)}s
        </Text>
        <Text className="detail-meta-footer__item">
          完成原因 {data.finish_reason}
        </Text>
        {data.is_partial && (
          <Text className="detail-meta-footer__item detail-meta-footer__item--warn">
            部分生成
          </Text>
        )}
      </View>

      {/* 新建会话 */}
      <View className="detail-new-session">
        <Button
          className="detail-new-session__btn"
          onClick={() => Taro.redirectTo({ url: '/views/consult/pages/index' })}
        >
          ✨ 开始新咨询
        </Button>
      </View>
    </View>
  );
}
