import { useState } from 'react';
import { View, Text, Button, Textarea, Input } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { httpClient } from '../../../logics/shared/services/httpClient';
import './narrative-submit.scss';

export default function NarrativeSubmit() {
  const [title, setTitle] = useState('');
  const [sourceType, setSourceType] = useState('专家撰写');
  const [narrative, setNarrative] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [extracting, setExtracting] = useState(false);

  const canSubmit = title.trim() && narrative.trim();

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
      // 提交成功后自动触发 LLM 提取
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
      const res = await httpClient.request<{ card_count: number }>({
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
      <View className="narrative-submit-page">
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
    <View className="narrative-submit-page">
      <View className="ns-navbar">
        <Button className="ns-navbar__back" onClick={() => Taro.navigateBack()}>←</Button>
        <Text className="ns-navbar__title">录入案例叙事</Text>
      </View>

      <View className="ns-form">
        <View className="ns-field">
          <Text className="ns-field__label">叙事标题</Text>
          <Input
            className="ns-field__input"
            value={title}
            onInput={(e) => setTitle(e.detail.value)}
            placeholder="如：ASD 商场感官过载干预案例"
            maxlength={100}
          />
        </View>

        <View className="ns-field">
          <Text className="ns-field__label">来源类型</Text>
          <View className="ns-field__source-row">
            {['专家撰写', '机构脱敏', '工单沉淀'].map((t) => (
              <Button
                key={t}
                className={`ns-field__source-btn ${sourceType === t ? 'ns-field__source-btn--active' : ''}`}
                onClick={() => setSourceType(t)}
              >
                {t}
              </Button>
            ))}
          </View>
        </View>

        <View className="ns-field">
          <Text className="ns-field__label">自然语言叙事</Text>
          <Text className="ns-field__hint">
            以自然段落描述完整的干预故事。AI 将自动识别场景并提取结构化卡片。
          </Text>
          <Textarea
            className="ns-field__textarea"
            value={narrative}
            onInput={(e) => setNarrative(e.detail.value)}
            placeholder={`示例：\n7 岁 ASD 男孩在商场因吹风机声音突然捂住耳朵蹲下，拒绝移动。妈妈尝试拉他起身无效。老师到场后，先关闭附近吹风机电源，提供降噪耳机和挤压玩具，3 分钟后患者平复，随后带离至安静角落。`}
            maxlength={5000}
          />
        </View>

        <View className="ns-actions">
          <Button
            className={`ns-actions__btn ${canSubmit ? '' : 'ns-actions__btn--disabled'}`}
            onClick={handleSubmit}
            disabled={!canSubmit || submitting}
          >
            {submitting ? '提交中...' : '提交并提取卡片'}
          </Button>
        </View>
      </View>
    </View>
  );
}
