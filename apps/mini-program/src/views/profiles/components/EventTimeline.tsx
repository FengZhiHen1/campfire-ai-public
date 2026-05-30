import { View, Text, Button } from '@tarojs/components';
import { formatRelativeTime } from '../../../logics/shared/utils/timeFormat';
import type { EventListItem } from '../../../logics/profiles/types';

const HIGH_RISK_BEHAVIORS = ['自伤行为', '攻击行为'];
const MEDIUM_RISK_BEHAVIORS = ['情绪崩溃'];

type EventAccent = 'error' | 'secondary' | 'tertiary';

function getEventAccent(behaviorType: string): EventAccent {
  if (HIGH_RISK_BEHAVIORS.includes(behaviorType)) return 'error';
  if (MEDIUM_RISK_BEHAVIORS.includes(behaviorType)) return 'secondary';
  return 'tertiary';
}

interface EventTimelineProps {
  events: EventListItem[];
  onRecordClick: () => void;
}

export default function EventTimeline({ events, onRecordClick }: EventTimelineProps) {
  if (events.length === 0) {
    return (
      <View className="profile-timeline">
        <View className="profile-timeline-empty">
          <View className="profile-timeline-empty__dot" />
          <Text className="profile-timeline-empty__text">暂无事件记录</Text>
          <Text className="profile-timeline-empty__hint">
            点击右上角 + 记录孩子的第一次行为事件
          </Text>
          <Button
            className="profile-timeline-empty__btn"
            onClick={onRecordClick}
          >
            + 记录事件
          </Button>
        </View>
      </View>
    );
  }

  return (
    <View className="profile-timeline">
      <View className="profile-timeline__axis" />
      {events.map((event, idx) => {
        const accent = getEventAccent(event.behavior_type);
        return (
          <View key={event.event_id} className="profile-timeline__row">
            <View className={`profile-timeline__dot ${idx === 0 ? 'profile-timeline__dot--latest' : ''}`} />
            <View className={`profile-event-card profile-event-card--${accent}`}>
              <View className="profile-event-card__header">
                <Text className="profile-event-card__time">
                  {formatRelativeTime(event.event_time)}
                </Text>
                <View className="profile-event-card__badges">
                  {event.has_professional_note && (
                    <Text className="profile-event-card__eval">已评估</Text>
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
    </View>
  );
}
