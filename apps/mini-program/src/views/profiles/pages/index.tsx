import { useState, useEffect, useCallback } from 'react';
import { View, Text, Button, Input } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { useProfile } from '../../../logics/profiles/hooks/useProfile';
import type { ProfileListItem, ProfileResponse } from '../../../logics/profiles/types';
import './index.scss';

// ============================================================================
// Mock 数据与常量
// ============================================================================

interface MockEvent {
  event_id: string;
  event_time: string;
  behavior_type: string;
  summary: string;
  has_evaluation: boolean;
  is_complete: boolean;
}

/** 生成 Mock 事件数据 */
function generateMockEvents(profileId: string): MockEvent[] {
  const types = ['情绪爆发', '自伤行为', '攻击行为', '拒绝服药', '逃跑/走失'];
  const summaries = [
    '在超市因噪音突然捂耳蹲下',
    '咬手背至泛红，持续约3分钟',
    '用力推搡同伴，被制止后哭泣',
    '不肯吞服医生新开的助眠药',
    '在公园独自跑向马路方向',
  ];
  const now = new Date();
  return Array.from({ length: 5 }).map((_, i) => {
    const t = new Date(now.getTime() - i * 86400000 * (i + 1));
    return {
      event_id: `${profileId}-event-${i}`,
      event_time: t.toISOString(),
      behavior_type: types[i % types.length],
      summary: summaries[i % summaries.length],
      has_evaluation: i === 1,
      is_complete: i !== 0,
    };
  });
}

/** 格式化时间戳 */
function formatEventTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  const dayDiff = Math.floor(diff / 86400000);
  const timeStr = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;

  if (dayDiff === 0) return `今天 ${timeStr}`;
  if (dayDiff === 1) return `昨天 ${timeStr}`;
  return `${d.getMonth() + 1}月${d.getDate()}日 ${timeStr}`;
}

/** 根据行为类型获取 accent 颜色 */
function getEventAccent(behaviorType: string): 'error' | 'secondary' | 'tertiary' {
  const highRisk = ['自伤行为', '攻击行为', '逃跑/走失'];
  const mediumRisk = ['情绪爆发', '拒绝服药'];
  if (highRisk.includes(behaviorType)) return 'error';
  if (mediumRisk.includes(behaviorType)) return 'secondary';
  return 'tertiary';
}

// ============================================================================
// 组件
// ============================================================================

export default function ProfileIndex() {
  // --------------------------------------------------------------------------
  // 数据层
  // --------------------------------------------------------------------------
  const { profiles, isLoading, error, fetchProfiles, getProfile } = useProfile();

  useEffect(() => {
    fetchProfiles();
  }, [fetchProfiles]);

  // --------------------------------------------------------------------------
  // 本地状态
  // --------------------------------------------------------------------------
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [selectedDetail, setSelectedDetail] = useState<ProfileResponse | null>(null);
  const [events, setEvents] = useState<MockEvent[]>([]);
  const [showQuickRecord, setShowQuickRecord] = useState(false);
  const [quickTrigger, setQuickTrigger] = useState('');
  const [quickManifest, setQuickManifest] = useState('');

  // --------------------------------------------------------------------------
  // 加载选中档案详情
  // --------------------------------------------------------------------------
  const selectedProfile = profiles[selectedIdx] ?? null;

  useEffect(() => {
    if (selectedProfile) {
      getProfile(selectedProfile.profile_id).then((detail) => {
        setSelectedDetail(detail);
        // Mock 事件数据
        setEvents(generateMockEvents(selectedProfile.profile_id));
      }).catch(() => {
        setSelectedDetail(null);
        setEvents([]);
      });
    } else {
      setSelectedDetail(null);
      setEvents([]);
    }
  }, [selectedProfile, getProfile]);

  // --------------------------------------------------------------------------
  // 事件处理
  // --------------------------------------------------------------------------
  const goEdit = useCallback(() => {
    if (!selectedProfile) return;
    Taro.navigateTo({
      url: `/views/profiles/pages/edit?mode=edit&profileId=${selectedProfile.profile_id}`,
    });
  }, [selectedProfile]);

  const goCreate = useCallback(() => {
    Taro.navigateTo({
      url: '/views/profiles/pages/edit?mode=create',
    });
  }, []);

  const handleQuickRecord = () => {
    if (!quickTrigger.trim()) return;
    const newEvent: MockEvent = {
      event_id: `temp-${Date.now()}`,
      event_time: new Date().toISOString(),
      behavior_type: '待分类',
      summary: quickTrigger,
      has_evaluation: false,
      is_complete: false,
    };
    setEvents((prev) => [newEvent, ...prev]);
    setQuickTrigger('');
    setQuickManifest('');
    setShowQuickRecord(false);
    Taro.showToast({
      title: '记录已保存，建议补充干预措施',
      icon: 'none',
      duration: 3000,
    });
  };

  // --------------------------------------------------------------------------
  // 冷启动态
  // --------------------------------------------------------------------------
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

  // --------------------------------------------------------------------------
  // 加载中
  // --------------------------------------------------------------------------
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

  // --------------------------------------------------------------------------
  // 正常态
  // --------------------------------------------------------------------------
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

          {/* 新建档案卡片 */}
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

      {/* 事件时间线 */}
      <View className="profile-timeline">
        {events.length === 0 ? (
          <View className="profile-timeline-empty">
            <View className="profile-timeline-empty__dot" />
            <Text className="profile-timeline-empty__text">暂无事件记录</Text>
            <Text className="profile-timeline-empty__hint">
              点击右上角 + 记录孩子的第一次行为事件
            </Text>
            <Button
              className="profile-timeline-empty__btn"
              onClick={() => setShowQuickRecord(true)}
            >
              + 记录事件
            </Button>
          </View>
        ) : (
          <>
            {/* 轴线 */}
            <View className="profile-timeline__axis" />

            {events.map((event, idx) => {
              const accent = getEventAccent(event.behavior_type);
              return (
                <View key={event.event_id} className="profile-timeline__row">
                  {/* 节点 */}
                  <View className={`profile-timeline__dot ${idx === 0 ? 'profile-timeline__dot--latest' : ''}`} />

                  {/* 事件卡片 */}
                  <View className={`profile-event-card profile-event-card--${accent}`}>
                    <View className="profile-event-card__header">
                      <Text className="profile-event-card__time">
                        {formatEventTime(event.event_time)}
                      </Text>
                      <View className="profile-event-card__badges">
                        {event.has_evaluation && (
                          <Text className="profile-event-card__eval">
                            已评估
                          </Text>
                        )}
                        {!event.is_complete && (
                          <Text className="profile-event-card__incomplete">
                            待补全
                          </Text>
                        )}
                      </View>
                    </View>

                    <View className="profile-event-card__tag">
                      <Text>{event.behavior_type}</Text>
                    </View>

                    <Text className="profile-event-card__summary">
                      {event.summary}
                    </Text>
                  </View>
                </View>
              );
            })}
          </>
        )}
      </View>

      {/* 快速录入 Bottom Sheet */}
      {showQuickRecord && (
        <>
          <View className="profile-sheet-overlay" onClick={() => setShowQuickRecord(false)} />
          <View className="profile-quick-sheet">
            <View className="profile-quick-sheet__handle" />
            <Text className="profile-quick-sheet__title">快速记录事件</Text>
            <Text className="profile-quick-sheet__subtitle">
              先记录关键信息，稍后可在档案中补全
            </Text>

            <View className="profile-quick-sheet__field">
              <Text className="profile-quick-sheet__label">
                <Text className="profile-quick-sheet__required">*</Text>
                发生了什么？（触发因素）
              </Text>
              <Input
                className="profile-quick-sheet__input"
                type="text"
                placeholder="如：在超市遇到噪音刺激…"
                value={quickTrigger}
                onInput={(e) => setQuickTrigger(e.detail.value)}
              />
            </View>

            <View className="profile-quick-sheet__field">
              <Text className="profile-quick-sheet__label">
                <Text className="profile-quick-sheet__required">*</Text>
                孩子的表现？（具体行为）
              </Text>
              <Input
                className="profile-quick-sheet__input"
                type="text"
                placeholder="如：突然捂耳蹲下，持续约3分钟…"
                value={quickManifest}
                onInput={(e) => setQuickManifest(e.detail.value)}
              />
            </View>

            <Button
              className="profile-quick-sheet__submit"
              onClick={handleQuickRecord}
            >
              保存记录
            </Button>
          </View>
        </>
      )}
    </View>
  );
}
