import { useState, useEffect, useCallback } from 'react';
import { View, Text, Button } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { useProfile } from '../../../logics/profiles';
import { useProfileStore } from '../../../logics/profiles/store/profileStore';
import { listEvents } from '../../../logics/profiles/services/eventApi';
import { useQuickRecord } from '../../../logics/profiles/hooks/useQuickRecord';
import EventTimeline from '../components/EventTimeline';
import QuickRecordSheet from '../components/QuickRecordSheet';
import type { EventListItem } from '../../../logics/profiles/types';
import './index.scss';

export default function ProfileIndex() {
  const { profiles, isLoading, error, fetchProfiles, getProfile } = useProfile();
  const selectedDetail = useProfileStore((s) => s.currentDetail);

  const [selectedIdx, setSelectedIdx] = useState(0);
  const [events, setEvents] = useState<EventListItem[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [showQuickRecord, setShowQuickRecord] = useState(false);

  const selectedProfile = profiles[selectedIdx] ?? null;

  const handleEventsRefresh = useCallback((refreshed: EventListItem[]) => {
    console.debug('[profile] handleEventsRefresh', { count: refreshed.length, items: refreshed.map((e) => e.event_id?.slice(0, 8)) });
    setEvents(refreshed);
  }, []);

  const quickRecord = useQuickRecord(
    selectedProfile?.profile_id ?? '',
    handleEventsRefresh,
  );

  // 首次挂载时拉取档案列表
  useEffect(() => {
    fetchProfiles();
  }, [fetchProfiles]);

  // 加载选中档案详情和事件列表
  useEffect(() => {
    if (selectedProfile) {
      console.debug('[profile] useEffect loadEvents', { profileId: selectedProfile.profile_id });
      getProfile(selectedProfile.profile_id);
      setEventsLoading(true);
      listEvents(selectedProfile.profile_id)
        .then((data) => { console.debug('[profile] listEvents done', { count: data.length }); setEvents(data); })
        .catch(() => setEvents([]))
        .finally(() => setEventsLoading(false));
    } else {
      setEvents([]);
    }
  }, [selectedProfile, getProfile]);

  const goEdit = useCallback(() => {
    if (!selectedProfile) return;
    Taro.navigateTo({
      url: `/views/profiles/pages/edit?mode=edit&profileId=${selectedProfile.profile_id}`,
    });
  }, [selectedProfile]);

  const goCreate = useCallback(() => {
    Taro.navigateTo({ url: '/views/profiles/pages/edit?mode=create' });
  }, []);

  const handleQuickRecordSubmit = useCallback(() => {
    quickRecord.submit().then((success) => {
      if (success) setShowQuickRecord(false);
    });
  }, [quickRecord]);

  // 冷启动态
  if (!isLoading && profiles.length === 0) {
    return (
      <View className="profile-index-page">
        <View className="profile-index-navbar">
          <View className="profile-index-navbar__brand">
            <Text className="profile-index-navbar__icon">🔥</Text>
            <Text className="profile-index-navbar__title">个人档案</Text>
          </View>
        </View>
        <View className="profile-cold-start">
          <View className="profile-cold-start__illustration" />
          <Text className="profile-cold-start__title">创建孩子的第一份档案</Text>
          <Text className="profile-cold-start__subtitle">
            完善的档案能帮助 AI 更精准地匹配与您孩子情况相似的真实干预案例
          </Text>
          <Button className="profile-cold-start__btn" onClick={goCreate}>
            📝 创建第一个档案
          </Button>
        </View>
      </View>
    );
  }

  // 加载中
  if (isLoading && profiles.length === 0) {
    return (
      <View className="profile-index-page">
        <View className="profile-index-navbar">
          <View className="profile-index-navbar__brand">
            <Text className="profile-index-navbar__icon">🔥</Text>
            <Text className="profile-index-navbar__title">个人档案</Text>
          </View>
        </View>
        <View className="profile-index-loading">
          <View className="profile-index-loading__skeleton" />
          <Text className="profile-index-loading__text">加载中...</Text>
        </View>
      </View>
    );
  }

  // 正常态
  return (
    <View className="profile-index-page">
      {/* 导航栏 */}
      <View className="profile-index-navbar">
        <View className="profile-index-navbar__brand">
          <Text className="profile-index-navbar__icon">🔥</Text>
          <Text className="profile-index-navbar__title">个人档案</Text>
        </View>
        {selectedProfile && (
          <Button className="profile-index-navbar__edit" onClick={goEdit}>
            编辑
          </Button>
        )}
      </View>

      {/* 横向档案切换条 */}
      <View className="profile-switcher">
        <View className="profile-switcher__scroll">
          {profiles.map((p, idx) => (
            <View
              key={p.profile_id}
              className={`profile-switcher__item ${idx === selectedIdx ? 'profile-switcher__item--active' : ''}`}
              onClick={() => setSelectedIdx(idx)}
            >
              <View className="profile-switcher__avatar-wrap">
                <View className="profile-switcher__avatar">
                  <Text className="profile-switcher__avatar-icon">👤</Text>
                </View>
                {idx === selectedIdx && <View className="profile-switcher__indicator" />}
              </View>
              <Text className="profile-switcher__name">{p.nickname || '未命名'}</Text>
            </View>
          ))}

          {profiles.length < 5 && (
            <View className="profile-switcher__item profile-switcher__item--add" onClick={goCreate}>
              <View className="profile-switcher__avatar-wrap">
                <View className="profile-switcher__avatar profile-switcher__avatar--add">
                  <Text className="profile-switcher__add-icon">+</Text>
                </View>
              </View>
              <Text className="profile-switcher__name">添加</Text>
            </View>
          )}
        </View>
      </View>

      {/* 档案信息卡片 */}
      {selectedDetail && (
        <View className="profile-info-card">
          <View className="profile-info-card__header">
            <View className="profile-info-card__avatar">
              <Text className="profile-info-card__avatar-icon">👤</Text>
            </View>
            <View className="profile-info-card__meta">
              <Text className="profile-info-card__name">
                {selectedDetail.nickname || '未命名'}
              </Text>
              <Text className="profile-info-card__age">
                {selectedDetail.age_range}
              </Text>
            </View>
          </View>

          <View className="profile-info-card__tags">
            <View className="profile-info-card__tag profile-info-card__tag--default">
              <Text className="profile-info-card__tag-icon">🎂</Text>
              <Text>{selectedDetail.birth_date}</Text>
            </View>
            <View className="profile-info-card__tag profile-info-card__tag--primary">
              <Text className="profile-info-card__tag-icon">🏷️</Text>
              <Text>{selectedDetail.diagnosis_type}</Text>
            </View>
            <View className={`profile-info-card__tag ${selectedDetail.primary_behavior?.includes('自伤') || selectedDetail.primary_behavior?.includes('攻击') ? 'profile-info-card__tag--danger' : 'profile-info-card__tag--default'}`}>
              <Text className="profile-info-card__tag-icon">⚡</Text>
              <Text>{selectedDetail.primary_behavior}</Text>
            </View>
          </View>
        </View>
      )}

      {/* 时间线标题区 */}
      <View className="profile-timeline-header">
        <Text className="profile-timeline-header__title">
          <Text className="profile-timeline-header__icon">📋</Text>
          事件记录（共 {events.length} 条）
        </Text>
        <Button
          className="profile-timeline-header__add"
          onClick={() => setShowQuickRecord(true)}
        >
          +
        </Button>
      </View>

      <EventTimeline
        events={events}
        onRecordClick={() => setShowQuickRecord(true)}
      />

      <QuickRecordSheet
        visible={showQuickRecord}
        form={quickRecord.form}
        isSubmitting={quickRecord.isSubmitting}
        onClose={() => setShowQuickRecord(false)}
        onFieldChange={quickRecord.setField}
        onSubmit={handleQuickRecordSubmit}
      />
    </View>
  );
}
