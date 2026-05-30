import { View, Text } from '@tarojs/components';
import type { EventListItem } from '../../../logics/profiles/types';

interface EventListSectionProps {
  events: EventListItem[];
  isLoading: boolean;
  expanded: boolean;
  onToggle: () => void;
  onDeleteEvent: (eventId: string) => void;
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
        <Text className="profile-event-section__title">
          📋 事件记录（共 {events.length} 条）
        </Text>
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
        <View className="profile-event-list">
          {events.length === 0 && (
            <Text className="profile-event-list__empty">暂无事件记录</Text>
          )}
          {events.map((event) => (
            <View key={event.event_id} className="profile-event-list__item">
              <View className="profile-event-list__summary">
                <View className="profile-event-list__summary-header">
                  <Text className="profile-event-list__time">
                    {new Date(event.event_time).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </Text>
                  <View className="profile-event-list__badges">
                    {event.has_professional_note && (
                      <Text className="profile-event-list__eval">已评估</Text>
                    )}
                    <Text className="profile-event-list__severity">{event.severity_level}</Text>
                  </View>
                  <View className="profile-event-list__actions">
                    <Text onClick={() => onDeleteEvent(event.event_id)}>🗑</Text>
                  </View>
                </View>
                <View className="profile-event-list__tag">
                  <Text>{event.behavior_type}</Text>
                </View>
              </View>
            </View>
          ))}
        </View>
      )}
    </View>
  );
}
