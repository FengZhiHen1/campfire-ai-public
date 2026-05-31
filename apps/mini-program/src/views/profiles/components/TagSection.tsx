import { View, Text, Button, Input } from '@tarojs/components';
import { SENSORY_FEATURE_TAGS, TRIGGER_TAGS, CUSTOM_TAG_MAX_LENGTH } from '../../../logics/profiles/constants';

interface TagSectionProps {
  selectedTags: string[];
  customTags: string[];
  customTagInput: string;
  onToggleTag: (tag: string) => void;
  onCustomTagInputChange: (value: string) => void;
  onAddCustomTag: () => void;
  onRemoveCustomTag: (tag: string) => void;
}

export default function TagSection({
  selectedTags,
  customTags,
  customTagInput,
  onToggleTag,
  onCustomTagInputChange,
  onAddCustomTag,
  onRemoveCustomTag,
}: TagSectionProps) {
  return (
    <View className="profile-tag-section">
      <View className="profile-tag-section__title">
        <Text className="profile-tag-section__title-icon">🏷️</Text>
        <Text>标签体系</Text>
      </View>
      <Text className="profile-tag-section__subtitle">帮助孩子获得更精准的案例匹配</Text>

      <View className="profile-edit-card">
        {/* 感官特征 */}
        <View>
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
        </View>

        {/* 触发因素 */}
        <View>
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
        </View>

        {/* 自定义标签 */}
        <View>
          <Text className="profile-tag-section__sub-title">自定义标签</Text>
          <View className="profile-custom-tag">
            <Input
              className="profile-custom-tag__input"
              value={customTagInput}
              onInput={(e) => onCustomTagInputChange(e.detail.value)}
              placeholder="输入自定义标签（最多10个字）"
              maxlength={CUSTOM_TAG_MAX_LENGTH}
            />
            <Button className="profile-custom-tag__add" onClick={onAddCustomTag}>
              +
            </Button>
          </View>
          <Text className="profile-custom-tag__count">{customTagInput.length}/{CUSTOM_TAG_MAX_LENGTH}</Text>

          {/* 已添加自定义标签 */}
          {customTags.length > 0 && (
            <View className="profile-custom-tag__list">
              {customTags.map((tag) => (
                <View key={tag} className="profile-custom-tag__pill">
                  <Text>{tag}</Text>
                  <Text className="profile-custom-tag__remove" onClick={() => onRemoveCustomTag(tag)}>✕</Text>
                </View>
              ))}
            </View>
          )}
        </View>
      </View>
    </View>
  );
}
