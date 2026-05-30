import { View, Text } from '@tarojs/components';
import type { EventListItem } from '../../../logics/profiles/types';

interface EventListSectionProps {
  events: EventListItem[];
  isLoading: boolean;
  expanded: boolean;
  onToggle: () => void;
  onDeleteEvent: (eventId: string) => void;
}

function getCardSeverityClass(level: string): string {
  if (level.includes('高') || level.includes('严重')) return 'profile-event-list__card--warning';
  if (level.includes('中')) return 'profile-event-list__card--default';
  return 'profile-event-list__card--success';
}

function getNodeSeverityClass(level: string): string {
  if (level.includes('高') || level.includes('严重')) return 'profile-event-list__node-dot--warning';
  return '';
}

export default function EventListSection({
  events,
  isLoading,
  expanded,
  onToggle,
  onDeleteEvent,
}: EventListSectionProps) {
  return (
    <View className="profile-event-section">
      <View className="profile-event-section__header">
        <View className="profile-event-section__title">
          <Text className="profile-event-section__title-icon">📋</Text>
          <Text>事件记录</Text>
          <Text className="profile-event-section__title-count">（共 {events.length} 条）</Text>
        </View>
        <Text
          className="profile-event-section__toggle"
          onClick={onToggle}
        >
          {expanded ? '折叠 ▲' : '展开 ▼'}
        </Text>
      </View>

      {isLoading && (
        <Text className="profile-event-list__loading">加载中…</Text>
      )}

      {expanded && !isLoading && (
        <View className="profile-event-timeline">
          <View className="profile-event-list">
            {events.length === 0 && (
              <Text className="profile-event-list__empty">暂无事件记录</Text>
            )}
            {events.map((event) => (
              <View key={event.event_id} className="profile-event-list__item">
                <View className="profile-event-list__node">
                  <View className={`profile-event-list__node-dot ${getNodeSeverityClass(event.severity_level)}`} />
                </View>
                <View className={`profile-event-list__card ${getCardSeverityClass(event.severity_level)}`}>
                  <View className="profile-event-list__summary-header">
                    <View style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <Text className="profile-event-list__time">
                        {new Date(event.event_time).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                      </Text>
                      <View className="profile-event-list__badges">
                        {event.has_professional_note && (
                          <Text className="profile-event-list__eval">已评估</Text>
                        )}
                        <Text className="profile-event-list__severity">{event.severity_level}</Text>
                      </View>
                    </View>
                    <View className="profile-event-list__actions">
                      <Text
                        className="profile-event-list__actions-btn"
                        onClick={() => onDeleteEvent(event.event_id)}
                      >
                        🗑
                      </Text>
                    </View>
                  </View>
                  <View className="profile-event-list__tag">
                    <Text>{event.behavior_type}</Text>
                  </View>
                  {event.description && (
                    <Text className="profile-event-list__desc" numberOfLines={2}>
                      {event.description}
                    </Text>
                  )}
                </View>
              </View>
            ))}
          </View>
        </View>
      )}
    </View>
  );
}
