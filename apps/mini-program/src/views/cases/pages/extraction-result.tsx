import { View, Text, Button, Textarea, Input, ScrollView } from '@tarojs/components';
import { useExtractionResult } from '../../../logics/cases';
import './extraction-result.scss';

// ============================================================================
// 组件：提取结果页（纯渲染层）
//
// 所有业务逻辑在 useExtractionResult Hook 中。
// 本组件只负责 JSX 渲染和事件绑定。
// ============================================================================

export default function ExtractionResult() {
  const {
    cards, activeTab, editing, loading, isSaving, isSubmittingAll,
    setActiveTab, updateField, saveCard, submitAll,
    behaviorTypeOptions, severityOptions, sceneOptions, categoryOptions,
  } = useExtractionResult();

  if (loading) {
    return (
      <View className='er-page'>
        <View className='er-loading'>
          <View className='er-loading__skeleton' />
          <Text className='er-loading__text'>AI 正在分析叙事内容...</Text>
          <Text className='er-loading__hint'>预计需要 10–30 秒</Text>
        </View>
      </View>
    );
  }

  if (cards.length === 0) {
    return (
      <View className="er-page">
        <View className="er-navbar">
          <Text className="er-navbar__title">提取结果</Text>
        </View>
        <View className="er-empty">AI 未能识别到干预场景，请检查叙事内容后重试</View>
      </View>
    );
  }

  return (
    <View className="er-page">
      <View className="er-navbar">
        <Text className="er-navbar__title">提取结果 ({cards.length} 张卡片)</Text>
      </View>

      {/* Tab 栏 */}
      <ScrollView className="er-tabs" scrollX>
        {cards.map((card, idx) => (
          <Button
            key={card.card_id}
            className={`er-tabs__btn ${idx === activeTab ? 'er-tabs__btn--active' : ''}`}
            onClick={() => setActiveTab(idx)}
          >
            {card.title || `卡片 ${idx + 1}`}
          </Button>
        ))}
      </ScrollView>

      {/* 编辑表单 */}
      {editing && (
        <ScrollView className="er-form" scrollY>
          {/* 标题 */}
          <View className="er-group">
            <Text className="er-group__title">基础信息</Text>
            <View className="er-field">
              <Text className="er-field__label">卡片标题</Text>
              <Input className="er-field__input" value={editing.title} onInput={(e) => updateField('title', e.detail.value)} />
            </View>
            <View className="er-field">
              <Text className="er-field__label">适用场景</Text>
              <Textarea className="er-field__textarea" value={editing.scenario} onInput={(e) => updateField('scenario', e.detail.value)} />
            </View>
          </View>

          {/* 分类 */}
          <View className="er-group">
            <Text className="er-group__title">分类标签</Text>
            <View className="er-field">
              <Text className="er-field__label">行为类型</Text>
              <View className="er-picker-row">
                {behaviorTypeOptions.map((t) => (
                  <Button key={t}
                    className={`er-picker-btn ${editing.behavior_type === t ? 'er-picker-btn--active' : ''}`}
                    onClick={() => updateField('behavior_type', t)}>{t}</Button>
                ))}
              </View>
            </View>
            <View className="er-field">
              <Text className="er-field__label">严重程度</Text>
              <View className="er-picker-row">
                {severityOptions.map((t) => (
                  <Button key={t}
                    className={`er-picker-btn ${editing.severity === t ? 'er-picker-btn--active' : ''}`}
                    onClick={() => updateField('severity', t)}>{t}</Button>
                ))}
              </View>
            </View>
            <View className="er-field">
              <Text className="er-field__label">场景</Text>
              <View className="er-picker-row">
                {sceneOptions.map((t) => (
                  <Button key={t}
                    className={`er-picker-btn ${editing.scene === t ? 'er-picker-btn--active' : ''}`}
                    onClick={() => updateField('scene', t)}>{t}</Button>
                ))}
              </View>
            </View>
            <View className="er-field">
              <Text className="er-field__label">家属端大类</Text>
              <View className="er-picker-row">
                {categoryOptions.map((t) => (
                  <Button key={t}
                    className={`er-picker-btn ${editing.family_category === t ? 'er-picker-btn--active' : ''}`}
                    onClick={() => updateField('family_category', t)}>{t}</Button>
                ))}
              </View>
            </View>
          </View>

          {/* 四段式 */}
          <View className="er-group">
            <Text className="er-group__title">四段式内容</Text>
            <Text className="er-group__subtitle">请确认 AI 提取的四段式内容是否准确</Text>
            {[
              { key: 'immediate_action', label: '即时安全干预动作', accent: 'immediate' },
              { key: 'comforting_phrase', label: '情绪安抚话术', accent: 'comforting' },
              { key: 'observation_metrics', label: '后续观察指标', accent: 'observation' },
              { key: 'medical_criteria', label: '就医判断标准', accent: 'medical' },
            ].map(({ key, label, accent }) => (
              <View key={key} className="er-quartet-card">
                <View className={`er-quartet-card__accent er-quartet-card__accent--${accent}`} />
                <View className="er-quartet-card__body">
                  <Text className={`er-quartet-card__title er-quartet-card__title--${accent}`}>
                    {label}
                    {editing.inferred_fields?.[key] && (
                      <Text className="er-field__inferred-badge">推断</Text>
                    )}
                  </Text>
                  {editing.inferred_fields?.[key] && (
                    <Text className="er-field__inferred-hint">{editing.inferred_fields[key]}</Text>
                  )}
                  <Textarea className="er-quartet-card__textarea"
                    value={(editing as unknown as Record<string, string>)[key] || ''}
                    onInput={(e) => updateField(key, e.detail.value)} />
                </View>
              </View>
            ))}
          </View>

          {/* 质量标注 */}
          <View className="er-group">
            <Text className="er-group__title">质量标注</Text>
            <View className="er-field">
              <Text className="er-field__label">循证等级</Text>
              <Text className="er-field__value">{editing.evidence_level}</Text>
            </View>
            <View className="er-field">
              <Text className="er-field__label">禁忌与注意</Text>
              <Textarea className="er-field__textarea" value={editing.caution_notes} onInput={(e) => updateField('caution_notes', e.detail.value)} />
            </View>
            <View className="er-field">
              <Text className="er-field__label">不适用人群/场景</Text>
              <Textarea className="er-field__textarea" value={editing.contraindications} onInput={(e) => updateField('contraindications', e.detail.value)} />
            </View>
          </View>

          {/* 推断字段说明 */}
          {editing.inferred_fields && Object.keys(editing.inferred_fields).length > 0 && (
            <View className="er-inferred-panel">
              <Text className="er-inferred-panel__title">AI 推断说明</Text>
              {Object.entries(editing.inferred_fields).map(([key, reason]) => (
                <View key={key} className="er-inferred-panel__item">
                  <Text className="er-inferred-panel__field">{key}</Text>
                  <Text className="er-inferred-panel__reason">{reason}</Text>
                </View>
              ))}
            </View>
          )}
        </ScrollView>
      )}

      {/* 底部操作 */}
      <View className="er-footer">
        <Button className="er-footer__save-btn" loading={isSaving} disabled={isSaving || isSubmittingAll} onClick={saveCard}>
          {isSaving ? '保存中...' : '保存当前卡片'}
        </Button>
        <Button className="er-footer__submit-btn" loading={isSubmittingAll} disabled={isSaving || isSubmittingAll} onClick={submitAll}>
          {isSubmittingAll ? '提交中...' : '提交全部审核'}
        </Button>
      </View>
    </View>
  );
}
