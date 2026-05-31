import { useEffect } from 'react';
import { View, Text, Button, Textarea, Input } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { useNarrativeSubmit } from '../../../logics/cases';
import './narrative-submit.scss';

// ============================================================================
// 组件：叙事提交页（纯渲染层）
//
// 所有业务逻辑在 useNarrativeSubmit Hook 中。
// 本组件只负责 JSX 渲染和事件绑定。
// ============================================================================

export default function NarrativeSubmit() {
  const {
    title, setTitle, sourceType, setSourceType, narrative, setNarrative,
    submitting, extracting, tipsExpanded, setTipsExpanded,
    titleCount, bodyCount, canSubmit,
    handleSaveDraft, handleSubmit,
    sourceOptions, writingTips, bodyPlaceholder,
  } = useNarrativeSubmit();

  useEffect(() => {
    if (extracting) {
      Taro.setNavigationBarTitle({ title: 'AI 正在提取' });
    }
  }, [extracting]);

  if (extracting) {
    return (
      <View className="ns-page">
        <View className="ns-loading">
          <View className="ns-loading__spinner" />
          <Text className="ns-loading__text">正在分析叙事，提取干预卡片...</Text>
          <Text className="ns-loading__hint">预计需要 10-30 秒</Text>
        </View>
      </View>
    );
  }

  return (
    <View className="ns-page">
      {/* Main Content */}
      <View className="ns-form">
        {/* Case Title */}
        <View className="ns-section">
          <View className="ns-section__header">
            <Text className="ns-section__label">
              叙事标题 <Text className="ns-section__required">*</Text>
            </Text>
            <Text className={`ns-section__counter ${titleCount > 100 ? 'ns-section__counter--error' : ''}`}>
              {titleCount}/100
            </Text>
          </View>
          <Input
            className="ns-input"
            value={title}
            onInput={(e) => setTitle(e.detail.value)}
            placeholder="请输入案例标题，如：ASD 商场感官过载干预案例"
            maxlength={100}
          />
        </View>

        {/* Source Type */}
        <View className="ns-section">
          <Text className="ns-section__label">来源类型</Text>
          <View className="ns-source-row">
            {sourceOptions.map((t) => (
              <Button
                key={t}
                className={`ns-source-btn ${sourceType === t ? 'ns-source-btn--active' : ''}`}
                onClick={() => setSourceType(t)}
              >
                {t}
              </Button>
            ))}
          </View>
        </View>

        {/* Writing Tips */}
        <View className="ns-tips">
          <View className="ns-tips__header" onClick={() => setTipsExpanded(!tipsExpanded)}>
            <View className="ns-tips__title">
              <Text className="ns-tips__icon">💡</Text>
              <Text className="ns-tips__label">写作提示</Text>
            </View>
            <Text className={`ns-tips__chevron ${tipsExpanded ? 'ns-tips__chevron--expanded' : ''}`}>▼</Text>
          </View>
          {tipsExpanded && (
            <View className="ns-tips__content">
              {writingTips.map((tip, idx) => (
                <View key={idx} className="ns-tips__item">
                  <Text className="ns-tips__bullet">✓</Text>
                  <Text className="ns-tips__text">{tip}</Text>
                </View>
              ))}
            </View>
          )}
        </View>

        {/* Narrative Body */}
        <View className="ns-section ns-section--grow">
          <View className="ns-section__header">
            <Text className="ns-section__label">
              叙事正文 <Text className="ns-section__required">*</Text>
            </Text>
          </View>
          <View className="ns-textarea-wrap">
            <Textarea
              className="ns-textarea"
              value={narrative}
              onInput={(e) => setNarrative(e.detail.value)}
              placeholder={bodyPlaceholder}
              maxlength={5000}
            />
            <View className="ns-textarea__counter">
              <Text className={`ns-textarea__counter-text ${bodyCount > 5000 ? 'ns-textarea__counter-text--error' : ''}`}>
                {bodyCount}/5000
              </Text>
            </View>
          </View>
        </View>
      </View>

      {/* Bottom Action Bar */}
      <View className="ns-footer">
        <View className="ns-footer__inner">
          <Button className="ns-footer__draft" onClick={handleSaveDraft}>保存草稿</Button>
          <Button
            className={`ns-footer__submit ${canSubmit ? '' : 'ns-footer__submit--disabled'}`}
            onClick={handleSubmit}
            disabled={!canSubmit || submitting}
          >
            {submitting ? '提交中...' : '提取卡片'}
          </Button>
        </View>
      </View>
    </View>
  );
}
