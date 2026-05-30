import { useState } from 'react';
import { View, Text, Button, Input, Textarea } from '@tarojs/components';
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

export default function QuickRecordSheet({
  visible,
  form,
  isSubmitting,
  onClose,
  onFieldChange,
  onSubmit,
}: QuickRecordSheetProps) {
  const [interventionExpanded, setInterventionExpanded] = useState(false);

  if (!visible) return null;

  const isValid =
    !!form.behaviorType &&
    !!form.severity &&
    form.trigger.trim().length > 0 &&
    form.manifest.trim().length > 0;

  return (
    <>
      <View className="profile-sheet-overlay" onClick={onClose} />
      <View className="profile-quick-sheet">
        {/* ===== Header ===== */}
        <View className="profile-quick-sheet__header">
          <View className="profile-quick-sheet__handle" />
          <View className="profile-quick-sheet__header-row">
            <View className="profile-quick-sheet__header-text">
              <Text className="profile-quick-sheet__title">记录行为事件</Text>
              <Text className="profile-quick-sheet__subtitle">
                完整记录有助于AI精准匹配案例
              </Text>
            </View>
            <View className="profile-quick-sheet__close" onClick={onClose}>
              <Text className="profile-quick-sheet__close-icon">✕</Text>
            </View>
          </View>
        </View>

        {/* ===== Scrollable Content ===== */}
        <View className="profile-quick-sheet__scroll">
          {/* Section 1: 事件分类 */}
          <View className="profile-quick-sheet__section">
            {/* 行为类型 */}
            <View className="profile-quick-sheet__field">
              <Text className="profile-quick-sheet__label">
                行为类型 <Text className="profile-quick-sheet__required">*</Text>
              </Text>
              <View className="profile-quick-sheet__chip-grid">
                {BEHAVIOR_OPTIONS.map((opt) => {
                  const active = form.behaviorType === opt;
                  return (
                    <View
                      key={opt}
                      className={`profile-quick-sheet__chip ${active ? 'profile-quick-sheet__chip--active' : ''}`}
                      onClick={() => onFieldChange('behaviorType', active ? '' : opt)}
                    >
                      {active && (
                        <Text className="profile-quick-sheet__chip-check">✓</Text>
                      )}
                      <Text className="profile-quick-sheet__chip-text">{opt}</Text>
                    </View>
                  );
                })}
              </View>
            </View>

            {/* 严重程度 */}
            <View className="profile-quick-sheet__field">
              <Text className="profile-quick-sheet__label">
                严重程度 <Text className="profile-quick-sheet__required">*</Text>
              </Text>
              <View className="profile-quick-sheet__segment">
                {SEVERITY_OPTIONS.map((opt) => {
                  const active = form.severity === opt;
                  return (
                    <View
                      key={opt}
                      className={`profile-quick-sheet__segment-item ${active ? 'profile-quick-sheet__segment-item--active' : ''}`}
                      onClick={() => onFieldChange('severity', active ? '' : opt)}
                    >
                      <Text className="profile-quick-sheet__segment-text">{opt}</Text>
                    </View>
                  );
                })}
              </View>
            </View>
          </View>

          {/* Section 2: 发生场景 */}
          <View className="profile-quick-sheet__section">
            <View className="profile-quick-sheet__field">
              <Text className="profile-quick-sheet__label">
                发生场景 <Text className="profile-quick-sheet__label-note">（可选）</Text>
              </Text>
              <View className="profile-quick-sheet__chip-row">
                {SETTING_OPTIONS.map((opt) => {
                  const active = form.setting === opt;
                  return (
                    <View
                      key={opt}
                      className={`profile-quick-sheet__chip-row-item ${active ? 'profile-quick-sheet__chip-row-item--active' : ''}`}
                      onClick={() => onFieldChange('setting', active ? '' : opt)}
                    >
                      <Text className="profile-quick-sheet__chip-row-text">{opt}</Text>
                    </View>
                  );
                })}
              </View>
            </View>
          </View>

          {/* Section 3: 事件描述 */}
          <View className="profile-quick-sheet__section">
            <View className="profile-quick-sheet__field">
              <Text className="profile-quick-sheet__label">
                触发因素 <Text className="profile-quick-sheet__required">*</Text>
              </Text>
              <Input
                className="profile-quick-sheet__text-input"
                type="text"
                placeholder="如：在超市遇到噪音刺激…"
                value={form.trigger}
                onInput={(e) => onFieldChange('trigger', e.detail.value)}
              />
            </View>

            <View className="profile-quick-sheet__field">
              <Text className="profile-quick-sheet__label">
                具体表现 <Text className="profile-quick-sheet__required">*</Text>
              </Text>
              <Textarea
                className="profile-quick-sheet__textarea"
                placeholder="如：突然捂耳蹲下，持续约3分钟…"
                value={form.manifest}
                onInput={(e) => onFieldChange('manifest', e.detail.value)}
              />
            </View>
          </View>

          {/* Section 4: 干预记录（可折叠） */}
          <View className="profile-quick-sheet__section">
            <View
              className="profile-quick-sheet__collapse"
              onClick={() => setInterventionExpanded((v) => !v)}
            >
              <Text className="profile-quick-sheet__collapse-label">
                干预记录 <Text className="profile-quick-sheet__label-note">（可选）</Text>
              </Text>
              <Text
                className="profile-quick-sheet__collapse-icon"
                style={{ transform: interventionExpanded ? 'rotate(90deg)' : 'rotate(0deg)' }}
              >
                ▶
              </Text>
            </View>

            {interventionExpanded && (
              <View className="profile-quick-sheet__collapse-body">
                <View className="profile-quick-sheet__field">
                  <Text className="profile-quick-sheet__label">尝试的干预措施</Text>
                  <Input
                    className="profile-quick-sheet__text-input"
                    type="text"
                    placeholder="如：带离现场，使用降噪耳机…"
                    value={form.intervention}
                    onInput={(e) => onFieldChange('intervention', e.detail.value)}
                  />
                </View>
                <View className="profile-quick-sheet__field">
                  <Text className="profile-quick-sheet__label">干预结果</Text>
                  <Input
                    className="profile-quick-sheet__text-input"
                    type="text"
                    placeholder="如：情绪逐渐平复…"
                    value={form.result}
                    onInput={(e) => onFieldChange('result', e.detail.value)}
                  />
                </View>
              </View>
            )}
          </View>
        </View>

        {/* ===== Footer ===== */}
        <View className="profile-quick-sheet__footer">
          <Button
            className={`profile-quick-sheet__submit ${!isValid || isSubmitting ? 'profile-quick-sheet__submit--disabled' : ''}`}
            onClick={onSubmit}
            disabled={!isValid || isSubmitting}
          >
            <Text className="profile-quick-sheet__submit-text">
              {isSubmitting ? '保存中…' : '保存记录'}
            </Text>
          </Button>
        </View>
      </View>
    </>
  );
}
