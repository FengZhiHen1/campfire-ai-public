import { View, Text, Button, Input, Picker } from '@tarojs/components';
import { BEHAVIOR_OPTIONS, SEVERITY_OPTIONS, SETTING_OPTIONS } from '../../../logics/profiles/constants';
import type { QuickRecordFormData } from '../../../logics/profiles/hooks/useQuickRecord';

interface QuickRecordSheetProps {
  visible: boolean;
  form: QuickRecordFormData;
  isSubmitting: boolean;
  onClose: () => void;
  onFieldChange: <K extends keyof QuickRecordFormData>(field: K, value: QuickRecordFormData[K]) => void;
  onSubmit: () => void;
}

function selectorValue(options: readonly string[], index: number): string {
  return options[index];
}

export default function QuickRecordSheet({
  visible,
  form,
  isSubmitting,
  onClose,
  onFieldChange,
  onSubmit,
}: QuickRecordSheetProps) {
  if (!visible) return null;

  return (
    <>
      <View className="profile-sheet-overlay" onClick={onClose} />
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
            range={[...BEHAVIOR_OPTIONS]}
            value={BEHAVIOR_OPTIONS.indexOf(form.behaviorType)}
            onChange={(e) => onFieldChange('behaviorType', selectorValue(BEHAVIOR_OPTIONS, e.detail.value as number))}
          >
            <View className={`profile-quick-sheet__picker ${!form.behaviorType ? 'profile-quick-sheet__picker--placeholder' : ''}`}>
              <Text>{form.behaviorType || '请选择行为类型'}</Text>
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
            range={[...SEVERITY_OPTIONS]}
            value={SEVERITY_OPTIONS.indexOf(form.severity)}
            onChange={(e) => onFieldChange('severity', selectorValue(SEVERITY_OPTIONS, e.detail.value as number))}
          >
            <View className={`profile-quick-sheet__picker ${!form.severity ? 'profile-quick-sheet__picker--placeholder' : ''}`}>
              <Text>{form.severity || '请选择严重程度'}</Text>
              <Text className="profile-quick-sheet__picker-arrow">▼</Text>
            </View>
          </Picker>
        </View>

        {/* 发生场景（可选） */}
        <View className="profile-quick-sheet__field">
          <Text className="profile-quick-sheet__label">发生场景（可选）</Text>
          <Picker
            mode="selector"
            range={[...SETTING_OPTIONS]}
            value={SETTING_OPTIONS.indexOf(form.setting)}
            onChange={(e) => onFieldChange('setting', selectorValue(SETTING_OPTIONS, e.detail.value as number))}
          >
            <View className={`profile-quick-sheet__picker ${!form.setting ? 'profile-quick-sheet__picker--placeholder' : ''}`}>
              <Text>{form.setting || '请选择场景'}</Text>
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
            value={form.trigger}
            onInput={(e) => onFieldChange('trigger', e.detail.value)}
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
            value={form.manifest}
            onInput={(e) => onFieldChange('manifest', e.detail.value)}
          />
        </View>

        {/* 干预措施（可选） */}
        <View className="profile-quick-sheet__field">
          <Text className="profile-quick-sheet__label">尝试的干预措施（可选）</Text>
          <Input
            className="profile-quick-sheet__input"
            type="text"
            placeholder="如：带离现场，使用降噪耳机…"
            value={form.intervention}
            onInput={(e) => onFieldChange('intervention', e.detail.value)}
          />
        </View>

        {/* 干预结果（可选） */}
        <View className="profile-quick-sheet__field">
          <Text className="profile-quick-sheet__label">干预结果（可选）</Text>
          <Input
            className="profile-quick-sheet__input"
            type="text"
            placeholder="如：情绪逐渐平复…"
            value={form.result}
            onInput={(e) => onFieldChange('result', e.detail.value)}
          />
        </View>

        <Button
          className="profile-quick-sheet__submit"
          onClick={onSubmit}
          disabled={isSubmitting}
        >
          {isSubmitting ? '保存中…' : '保存记录'}
        </Button>
      </View>
    </>
  );
}
