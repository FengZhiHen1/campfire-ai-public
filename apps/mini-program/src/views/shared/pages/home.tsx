import { useState, useEffect } from 'react';
import { View, Text, Button } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { consultApi } from '../../../logics/consult';
import type { ConsultationHistoryListItem } from '../../../logics/consult';
import { listProfiles } from '../../../logics/profiles/services/profileApi';
import './home.scss';

interface ProfileItem {
  profile_id: string;
  nickname: string;
  age?: number;
  diagnosis_type?: string;
  primary_behavior?: string;
}

const GREETING_MORNING = '早上好';
const GREETING_AFTERNOON = '下午好';
const GREETING_EVENING = '晚上好';
const BRAND_NAME = '篝火智答';

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour >= 5 && hour < 12) return GREETING_MORNING;
  if (hour >= 12 && hour < 18) return GREETING_AFTERNOON;
  return GREETING_EVENING;
}

function formatTime(dateStr?: string): string {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const oneDay = 24 * 60 * 60 * 1000;

  const hm = `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;

  if (diff < oneDay && now.getDate() === date.getDate()) {
    return `今天 ${hm}`;
  }
  if (diff < oneDay * 2 && now.getDate() - date.getDate() === 1) {
    return `昨天 ${hm}`;
  }
  return `${date.getMonth() + 1}月${date.getDate()}日 ${hm}`;
}

export default function HomePage() {
  const [loading, setLoading] = useState(true);
  const [hasError, setHasError] = useState(false);
  const [consultHistory, setConsultHistory] = useState<ConsultationHistoryListItem[]>([]);
  const [profiles, setProfiles] = useState<ProfileItem[]>([]);

  const load = async () => {
    setLoading(true);
    setHasError(false);
    try {
      const [historyRes, profileRes] = await Promise.all([
        consultApi.fetchHistoryList(1, 5).catch(() => ({ items: [], total: 0, page: 1, page_size: 5 })),
        listProfiles().catch(() => []),
      ]);
      setConsultHistory(historyRes.items || []);
      setProfiles(profileRes as ProfileItem[]);
    } catch {
      setHasError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const greeting = getGreeting();
  const latestConsult = consultHistory[0];
  const latestProfile = profiles[0];

  const goConsult = () => {
    Taro.switchTab({ url: '/views/consult/pages/index' });
  };

  const goConsultHistory = () => {
    Taro.navigateTo({ url: '/views/consult/pages/history' });
  };

  const goProfile = () => {
    Taro.navigateTo({ url: '/views/profiles/pages/edit' });
  };

  return (
    <View className="home-page">
      {/* 顶部问候区 */}
      <View className="home-greeting">
        <View className="home-greeting__brand">
          <Text className="home-greeting__brand-text">{BRAND_NAME}</Text>
          <Text className="home-greeting__brand-icon">🔥</Text>
        </View>
        <Text className="home-greeting__title">{greeting}</Text>
        <Text className="home-greeting__subtitle">
          {latestProfile ? '今天孩子状态怎么样？' : '欢迎开始使用篝火智答'}
        </Text>
      </View>

      {hasError && (
        <View className='home-error-banner'>
          <Text className='home-error-banner__icon'>⚠️</Text>
          <Text className='home-error-banner__text'>数据加载失败</Text>
          <Button className='home-error-banner__retry' onClick={load}>重试</Button>
        </View>
      )}

      {/* 应急咨询大卡片 */}
      <View className="home-emergency">
        <Text className="home-emergency__icon">🚨</Text>
        <Text className="home-emergency__title">应急咨询</Text>
        <Text className="home-emergency__desc">
          遇到紧急情况？描述当前状况，AI 将在几秒内生成个性化建议
        </Text>
        <Button className="home-emergency__btn" onClick={goConsult}>
          <Text className="home-emergency__btn-icon">🎤</Text>
          <Text>立即咨询</Text>
        </Button>
      </View>

      {/* 最近咨询记录区 */}
      <View className="home-section-header">
        <Text className="home-section-header__title">最近咨询</Text>
        <Button className="home-section-header__link" onClick={goConsultHistory}>
          查看全部 →
        </Button>
      </View>

      {loading ? (
        <View className="home-skeleton" />
      ) : latestConsult ? (
        <View className="home-consult-card" onClick={goConsult}>
          <View className="home-consult-card__header">
            <View className="home-consult-card__level">
              <View className="home-consult-card__level-dot home-consult-card__level-dot--medium" />
              <Text>咨询记录</Text>
            </View>
            <Text className="home-consult-card__time">
              {formatTime(latestConsult.created_at)}
            </Text>
          </View>
          <Text className="home-consult-card__summary">
            {latestConsult.behavior_description || '（暂无描述）'}
          </Text>
          <Text className="home-consult-card__action">→ 继续对话</Text>
        </View>
      ) : (
        <View className="home-consult-empty">
          <Text className="home-consult-empty__icon">💬</Text>
          <Text className="home-consult-empty__text">暂无咨询记录</Text>
          <Text className="home-consult-empty__hint">点击上方"立即咨询"开始第一次对话</Text>
        </View>
      )}

      {/* 个人档案快捷卡片 */}
      <View className="home-section-header">
        <Text className="home-section-header__title">个人档案</Text>
        <Button className="home-section-header__link" onClick={goProfile}>
          查看全部 →
        </Button>
      </View>

      {loading ? (
        <View className="home-skeleton" style={{ height: '200px' }} />
      ) : latestProfile ? (
        <View className="home-profile-card" onClick={goProfile}>
          <View className="home-profile-card__avatar">
            <Text className="home-profile-card__avatar-icon">👤</Text>
          </View>
          <View className="home-profile-card__info">
            <View className="home-profile-card__name-row">
              <Text className="home-profile-card__name">{latestProfile.nickname}</Text>
              {latestProfile.age !== undefined && (
                <Text className="home-profile-card__tag home-profile-card__tag--age">
                  {latestProfile.age}岁
                </Text>
              )}
              {latestProfile.diagnosis_type && (
                <Text className="home-profile-card__tag home-profile-card__tag--diagnosis">
                  {latestProfile.diagnosis_type}
                </Text>
              )}
            </View>
            {latestProfile.primary_behavior && (
              <View className="home-profile-card__name-row">
                <Text className="home-profile-card__tag home-profile-card__tag--behavior">
                  {latestProfile.primary_behavior}
                </Text>
              </View>
            )}
          </View>
          <Text className="home-profile-card__link">→ 查看档案</Text>
        </View>
      ) : (
        <View className="home-profile-create" onClick={goProfile}>
          <View className="home-profile-create__icon">📝</View>
          <View className="home-profile-create__content">
            <Text className="home-profile-create__title">创建孩子的第一份档案</Text>
            <Text className="home-profile-create__subtitle">
              完善的档案能帮助 AI 更精准地匹配案例
            </Text>
            <Text className="home-profile-create__link">创建档案 →</Text>
          </View>
        </View>
      )}
    </View>
  );
}
