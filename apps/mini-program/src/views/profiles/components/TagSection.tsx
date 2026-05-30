import { View, Text } from '@tarojs/components';
import { PRESET_TAGS, SENSORY_FEATURE_TAGS, TRIGGER_TAGS } from '../../../logics/profiles/constants';

interface TagSectionProps {
  isEdit: boolean;
  selectedTags: string[];
  onToggleTag: (tag: string) => void;
}

export default function TagSection({
  isEdit,
  selectedTags,
  onToggleTag,
}: TagSectionProps) {
  return (
    <View className={`profile-tag-section ${!isEdit ? 'profile-tag-section--disabled' : ''}`}>
      <Text className="profile-tag-section__title">标签体系</Text>
      <Text className="profile-tag-section__subtitle">帮助孩子获得更精准的案例匹配</Text>

      {!isEdit && (
        <Text className="profile-tag-section__hint">创建档案后可添加标签和事件记录</Text>
      )}

      {isEdit && (
        <>
          {/* 感官特征 */}
          <Text className="profile-tag-section__sub-title">感官特征</Text>
          <View className="profile-tag-grid">
            {SENSORY_FEATURE_TAGS.map((tag) => (
              <View
                key={tag}
                className={`profile-tag-grid__item ${selectedTags.includes(tag) ? 'profile-tag-grid__item--active' : ''}`}
                onClick={() => onToggleTag(tag)}
              >
                <Text>{tag}</Text>
                {selectedTags.includes(tag) && <Text className="profile-tag-grid__check">✓</Text>}
              </View>
            ))}
          </View>

          {/* 触发因素 */}
          <Text className="profile-tag-section__sub-title">触发因素</Text>
          <View className="profile-tag-grid">
            {TRIGGER_TAGS.map((tag) => (
              <View
                key={tag}
                className={`profile-tag-grid__item ${selectedTags.includes(tag) ? 'profile-tag-grid__item--active' : ''}`}
                onClick={() => onToggleTag(tag)}
              >
                <Text>{tag}</Text>
                {selectedTags.includes(tag) && <Text className="profile-tag-grid__check">✓</Text>}
              </View>
            ))}
          </View>
        </>
      )}
    </View>
  );
}
