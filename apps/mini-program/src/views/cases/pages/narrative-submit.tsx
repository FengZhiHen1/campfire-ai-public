import { useState } from 'react';
import { View, Text, Button, Textarea, Input } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { httpClient } from '../../../logics/shared/services/httpClient';
import './narrative-submit.scss';

const SOURCE_OPTIONS = ['专家撰写', '机构脱敏', '工单沉淀'];

const WRITING_TIPS = [
  '详细描述前因：引发行为的具体环境或事件是什么？',
  '客观记录行为：孩子具体的表现（如：大声尖叫持续5分钟，双手捂耳）。',
  '说明干预步骤及结果：采取了哪些行动，最终效果如何？',
];

const BODY_PLACEHOLDER = `【描述孩子情况】
年龄、诊断倾向、当下的情绪基调...

【行为表现】
具体的动作、声音、持续时间...

【干预动作】
你做了什么？环境做了哪些调整？...

【结果效果】
最终状态如何？有何反思？...`;

export default function NarrativeSubmit() {
  const [title, setTitle] = useState('');
  const [sourceType, setSourceType] = useState('专家撰写');
  const [narrative, setNarrative] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [tipsExpanded, setTipsExpanded] = useState(true);

  const titleCount = title.length;
  const bodyCount = narrative.length;
  const canSubmit = title.trim() && narrative.trim();

  const handleSaveDraft = () => {
    if (!title.trim() && !narrative.trim()) {
      Taro.showToast({ title: '请先输入内容', icon: 'none' });
      return;
    }
    Taro.showToast({ title: '草稿已保存', icon: 'success' });
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const res = await httpClient.request<{ narrative_id: string }>({
        url: '/api/v1/narratives',
        method: 'POST',
        data: { title, narrative, source_type: sourceType },
        header: { 'Content-Type': 'application/json' },
      });
      const narrativeId = res.data.narrative_id;
      setSubmitting(false);
      setExtracting(true);
      await triggerExtraction(narrativeId);
    } catch {
      Taro.showToast({ title: '提交失败', icon: 'none' });
      setSubmitting(false);
    }
  };

  const triggerExtraction = async (narrativeId: string) => {
    try {
      await httpClient.request<{ card_count: number }>({
        url: `/api/v1/narratives/${narrativeId}/extract`,
        method: 'POST',
        header: { 'Content-Type': 'application/json' },
      });
      setExtracting(false);
      Taro.redirectTo({
        url: `/views/cases/pages/extraction-result?narrativeId=${narrativeId}`,
      });
    } catch {
      Taro.showToast({ title: '提取失败，请稍后重试', icon: 'none' });
      setExtracting(false);
      Taro.redirectTo({
        url: `/views/cases/pages/extraction-result?narrativeId=${narrativeId}`,
      });
    }
  };

  if (extracting) {
    return (
      <View className="ns-page">
        <View className="ns-navbar">
          <Text className="ns-navbar__title">AI 正在提取</Text>
        </View>
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
      {/* TopAppBar */}
      <View className="ns-navbar">
        <Button className="ns-navbar__cancel" onClick={() => Taro.navigateBack()}>
          <Text className="ns-navbar__cancel-text">取消</Text>
        </Button>
        <Text className="ns-navbar__title">录入案例叙事</Text>
        <View className="ns-navbar__spacer" />
      </View>

      {/* Main Content */}
      <View className="ns-form">
        {/* Case Title */}
        <View className="ns-section">
          <View className="ns-section__header">
            <Text className="ns-section__label">
              叙事标题 <Text className="ns-section__required">*</Text>
            </Text>
            <Text
              className={`ns-section__counter ${titleCount > 100 ? 'ns-section__counter--error' : ''}`}
            >
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
            {SOURCE_OPTIONS.map((t) => (
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
            <Text
              className={`ns-tips__chevron ${tipsExpanded ? 'ns-tips__chevron--expanded' : ''}`}
            >
              ▼
            </Text>
          </View>
          {tipsExpanded && (
            <View className="ns-tips__content">
              {WRITING_TIPS.map((tip, idx) => (
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
              placeholder={BODY_PLACEHOLDER}
              maxlength={5000}
            />
            <View className="ns-textarea__counter">
              <Text
                className={`ns-textarea__counter-text ${bodyCount > 5000 ? 'ns-textarea__counter-text--error' : ''}`}
              >
                {bodyCount}/5000
              </Text>
            </View>
          </View>
        </View>
      </View>

      {/* Bottom Action Bar */}
      <View className="ns-footer">
        <View className="ns-footer__inner">
          <Button className="ns-footer__draft" onClick={handleSaveDraft}>
            保存草稿
          </Button>
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
