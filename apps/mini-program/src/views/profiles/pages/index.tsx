import { useState, useEffect, useCallback } from 'react';
import { View, Text, Button, Input, Picker } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { useProfile } from '../../../logics/profiles/hooks/useProfile';
import { listEvents, createEvent } from '../../../logics/profiles/services/eventApi';
import type { ProfileListItem, ProfileResponse, EventListItem, EventCreate } from '../../../logics/profiles/types';
import './index.scss';

// ============================================================================
// 常量
// ============================================================================

const BEHAVIOR_OPTIONS = ['刻板行为', '情绪崩溃', '自伤行为', '攻击行为', '社交退缩', '多动'];
const SEVERITY_OPTIONS = ['轻', '中', '重'];
const SETTING_OPTIONS = ['家庭', '学校', '公共场合', '机构'];

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

/** 根据行为类型获取 accent 颜色（对齐后端 ProfileBehaviorType 枚举） */
function getEventAccent(behaviorType: string): 'error' | 'secondary' | 'tertiary' {
  const highRisk = ['自伤行为', '攻击行为'];
  const mediumRisk = ['情绪崩溃'];
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
  const [events, setEvents] = useState<EventListItem[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [showQuickRecord, setShowQuickRecord] = useState(false);

  // 快速记录表单（A 方案：扩展为完整事件字段，部分可选）
  const [quickEventTime, setQuickEventTime] = useState('');
  const [quickBehaviorType, setQuickBehaviorType] = useState('');
  const [quickSeverity, setQuickSeverity] = useState('');
  const [quickSetting, setQuickSetting] = useState('');
  const [quickTrigger, setQuickTrigger] = useState('');
  const [quickManifest, setQuickManifest] = useState('');
  const [quickIntervention, setQuickIntervention] = useState('');
  const [quickResult, setQuickResult] = useState('');
  const [quickSubmitting, setQuickSubmitting] = useState(false);

  // --------------------------------------------------------------------------
  // 加载选中档案详情
  // --------------------------------------------------------------------------
  const selectedProfile = profiles[selectedIdx] ?? null;

  useEffect(() => {
    if (selectedProfile) {
      getProfile(selectedProfile.profile_id).then((detail) => {
        setSelectedDetail(detail);
      }).catch(() => {
        setSelectedDetail(null);
      });

      // 加载真实事件列表
      setEventsLoading(true);
      listEvents(selectedProfile.profile_id)
        .then((data) => {
          setEvents(data);
        })
        .catch(() => {
          setEvents([]);
        })
        .finally(() => {
          setEventsLoading(false);
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

  const handleQuickRecord = async () => {
    if (!selectedProfile) return;
    if (!quickTrigger.trim() || !quickManifest.trim() || !quickBehaviorType || !quickSeverity) {
      Taro.showToast({ title: '请填写必填项', icon: 'none' });
      return;
    }

    setQuickSubmitting(true);
    try {
      const payload: EventCreate = {
        event_time: quickEventTime || new Date().toISOString(),
        behavior_type: quickBehaviorType,
        severity_level: quickSeverity,
        setting: quickSetting || null,
        trigger_description: quickTrigger.trim(),
        manifestation: quickManifest.trim(),
        // 可选字段：用户未填时传占位值，待后端放宽约束后可移除
        intervention_tried: quickIntervention.trim() || '（未记录）',
        intervention_result: quickResult.trim() || '（未记录）',
        tags: null,
      };

      await createEvent(selectedProfile.profile_id, payload);
      Taro.showToast({ title: '记录已保存', icon: 'success' });

      // 刷新事件列表
      const refreshed = await listEvents(selectedProfile.profile_id);
      setEvents(refreshed);

      // 重置表单
      setQuickEventTime('');
      setQuickBehaviorType('');
      setQuickSeverity('');
      setQuickSetting('');
      setQuickTrigger('');
      setQuickManifest('');
      setQuickIntervention('');
      setQuickResult('');
      setShowQuickRecord(false);
    } catch {
      Taro.showToast({ title: '保存失败，请重试', icon: 'none' });
    } finally {
      setQuickSubmitting(false);
    }
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
                        {event.has_professional_note && (
                          <Text className="profile-event-card__eval">
                            已评估
                          </Text>
                        )}
                        <Text className="profile-event-card__severity">
                          {event.severity_level}
                        </Text>
                      </View>
                    </View>

                    <View className="profile-event-card__tag">
                      <Text>{event.behavior_type}</Text>
                    </View>
                  </View>
                </View>
              );
            })}
          </>
        )}
      </View>

      {/* 快速录入 Bottom Sheet（A 方案：扩展为完整事件字段） */}
      {showQuickRecord && (
        <>
          <View className="profile-sheet-overlay" onClick={() => setShowQuickRecord(false)} />
          <View className="profile-quick-sheet">
            <View className="profile-quick-sheet__handle" />
            <Text className="profile-quick-sheet__title">记录行为事件</Text>
            <Text className="profile-quick-sheet__subtitle">
              完整记录有助于 AI 更精准地匹配干预案例
            </Text>

            {/* 行为类型 */}
            <View className="profile-quick-sheet__field">
              <Text className="profile-quick-sheet__label">
                <Text className="profile-quick-sheet__required">*</Text>
                行为类型
              </Text>
              <Picker
                mode="selector"
                range={BEHAVIOR_OPTIONS}
                value={BEHAVIOR_OPTIONS.indexOf(quickBehaviorType)}
                onChange={(e) => setQuickBehaviorType(BEHAVIOR_OPTIONS[e.detail.value])}
              >
                <View className={`profile-quick-sheet__picker ${!quickBehaviorType ? 'profile-quick-sheet__picker--placeholder' : ''}`}>
                  <Text>{quickBehaviorType || '请选择行为类型'}</Text>
                  <Text className="profile-quick-sheet__picker-arrow">▼</Text>
                </View>
              </Picker>
            </View>

            {/* 严重程度 */}
            <View className="profile-quick-sheet__field">
              <Text className="profile-quick-sheet__label">
                <Text className="profile-quick-sheet__required">*</Text>
                严重程度
              </Text>
              <Picker
                mode="selector"
                range={SEVERITY_OPTIONS}
                value={SEVERITY_OPTIONS.indexOf(quickSeverity)}
                onChange={(e) => setQuickSeverity(SEVERITY_OPTIONS[e.detail.value])}
              >
                <View className={`profile-quick-sheet__picker ${!quickSeverity ? 'profile-quick-sheet__picker--placeholder' : ''}`}>
                  <Text>{quickSeverity || '请选择严重程度'}</Text>
                  <Text className="profile-quick-sheet__picker-arrow">▼</Text>
                </View>
              </Picker>
            </View>

            {/* 发生场景（可选） */}
            <View className="profile-quick-sheet__field">
              <Text className="profile-quick-sheet__label">发生场景（可选）</Text>
              <Picker
                mode="selector"
                range={SETTING_OPTIONS}
                value={SETTING_OPTIONS.indexOf(quickSetting)}
                onChange={(e) => setQuickSetting(SETTING_OPTIONS[e.detail.value])}
              >
                <View className={`profile-quick-sheet__picker ${!quickSetting ? 'profile-quick-sheet__picker--placeholder' : ''}`}>
                  <Text>{quickSetting || '请选择场景'}</Text>
                  <Text className="profile-quick-sheet__picker-arrow">▼</Text>
                </View>
              </Picker>
            </View>

            {/* 触发因素 */}
            <View className="profile-quick-sheet__field">
              <Text className="profile-quick-sheet__label">
                <Text className="profile-quick-sheet__required">*</Text>
                触发因素
              </Text>
              <Input
                className="profile-quick-sheet__input"
                type="text"
                placeholder="如：在超市遇到噪音刺激…"
                value={quickTrigger}
                onInput={(e) => setQuickTrigger(e.detail.value)}
              />
            </View>

            {/* 具体表现 */}
            <View className="profile-quick-sheet__field">
              <Text className="profile-quick-sheet__label">
                <Text className="profile-quick-sheet__required">*</Text>
                具体表现
              </Text>
              <Input
                className="profile-quick-sheet__input"
                type="text"
                placeholder="如：突然捂耳蹲下，持续约3分钟…"
                value={quickManifest}
                onInput={(e) => setQuickManifest(e.detail.value)}
              />
            </View>

            {/* 干预措施（可选） */}
            <View className="profile-quick-sheet__field">
              <Text className="profile-quick-sheet__label">尝试的干预措施（可选）</Text>
              <Input
                className="profile-quick-sheet__input"
                type="text"
                placeholder="如：带离现场，使用降噪耳机…"
                value={quickIntervention}
                onInput={(e) => setQuickIntervention(e.detail.value)}
              />
            </View>

            {/* 干预结果（可选） */}
            <View className="profile-quick-sheet__field">
              <Text className="profile-quick-sheet__label">干预结果（可选）</Text>
              <Input
                className="profile-quick-sheet__input"
                type="text"
                placeholder="如：情绪逐渐平复…"
                value={quickResult}
                onInput={(e) => setQuickResult(e.detail.value)}
              />
            </View>

            <Button
              className="profile-quick-sheet__submit"
              onClick={handleQuickRecord}
              disabled={quickSubmitting}
            >
              {quickSubmitting ? '保存中…' : '保存记录'}
            </Button>
          </View>
        </>
      )}
    </View>
  );
}
