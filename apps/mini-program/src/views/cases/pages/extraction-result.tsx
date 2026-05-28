import { useState, useEffect } from 'react';
import { View, Text, Button, Textarea, Input, ScrollView } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { httpClient } from '../../../logics/shared/services/httpClient';
import './extraction-result.scss';

interface CardData {
  card_id: string;
  title: string;
  scenario: string;
  behavior_type: string;
  age_range: number[];
  severity: string;
  scene: string;
  ebp_labels: string[];
  family_category: string;
  immediate_action: string;
  comforting_phrase: string;
  observation_metrics: string;
  medical_criteria: string;
  evidence_level: string;
  caution_notes: string;
  contraindications: string;
  is_template: boolean;
  inferred_fields?: Record<string, string>;
}

const BEHAVIOR_TYPES = ['自伤', '攻击', '刻板', '逃跑', '情绪崩溃', '其他'];
const SEVERITY_LEVELS = ['轻', '中', '重'];
const SCENES = ['家庭', '学校', '公共场合', '机构', '不限'];
const CATEGORIES = ['环境调整', '沟通替代', '行为塑造', '危机安全', '社交引导', '自我管理'];

export default function ExtractionResult() {
  const [cards, setCards] = useState<CardData[]>([]);
  const [activeTab, setActiveTab] = useState(0);
  const [editing, setEditing] = useState<CardData | null>(null);
  const [loading, setLoading] = useState(true);

  const narrativeId = Taro.getCurrentInstance().router?.params?.narrativeId || '';

  useEffect(() => {
    if (!narrativeId) return;
    httpClient.request<{ cards: CardData[] }>({
      url: `/api/v1/narratives/${narrativeId}`,
      method: 'GET',
    }).then((res) => {
      setCards(res.data.cards || []);
      if (res.data.cards?.length > 0) {
        setEditing({ ...res.data.cards[0] });
      }
    }).catch(() => {
      Taro.showToast({ title: '加载失败', icon: 'none' });
    }).finally(() => setLoading(false));
  }, [narrativeId]);

  const switchTab = (idx: number) => {
    setActiveTab(idx);
    setEditing(cards[idx] ? { ...cards[idx] } : null);
  };

  const updateField = (field: string, value: unknown) => {
    if (!editing) return;
    setEditing({ ...editing, [field]: value });
  };

  const saveCard = async () => {
    if (!editing) return;
    try {
      await httpClient.request({
        url: `/api/v1/cards/${editing.card_id}`,
        method: 'PUT',
        data: editing,
        header: { 'Content-Type': 'application/json' },
      });
      const updated = cards.map((c) => c.card_id === editing.card_id ? editing : c);
      setCards(updated);
      Taro.showToast({ title: '已保存', icon: 'success' });
    } catch {
      Taro.showToast({ title: '保存失败', icon: 'none' });
    }
  };

  const submitAll = async () => {
    try {
      for (const card of cards) {
        await httpClient.request({
          url: `/api/v1/cards/${card.card_id}/submit`,
          method: 'POST',
          header: { 'Content-Type': 'application/json' },
        });
      }
      Taro.showToast({ title: '全部卡片已提交审核' });
      Taro.navigateBack();
    } catch {
      Taro.showToast({ title: '提交失败', icon: 'none' });
    }
  };

  if (loading) {
    return <View className="er-page"><Text>加载中...</Text></View>;
  }

  if (cards.length === 0) {
    return (
      <View className="er-page">
        <View className="er-navbar">
          <Button className="er-navbar__back" onClick={() => Taro.navigateBack()}>←</Button>
          <Text className="er-navbar__title">提取结果</Text>
        </View>
        <View className="er-empty">AI 未能识别到干预场景，请检查叙事内容后重试</View>
      </View>
    );
  }

  return (
    <View className="er-page">
      <View className="er-navbar">
        <Button className="er-navbar__back" onClick={() => Taro.navigateBack()}>←</Button>
        <Text className="er-navbar__title">提取结果 ({cards.length} 张卡片)</Text>
      </View>

      {/* Tab 栏 */}
      <ScrollView className="er-tabs" scrollX>
        {cards.map((card, idx) => (
          <Button
            key={card.card_id}
            className={`er-tabs__btn ${idx === activeTab ? 'er-tabs__btn--active' : ''}`}
            onClick={() => switchTab(idx)}
          >
            卡片 {idx + 1}
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
              <Input className="er-field__input" value={editing.title}
                onInput={(e) => updateField('title', e.detail.value)} />
            </View>
            <View className="er-field">
              <Text className="er-field__label">适用场景</Text>
              <Textarea className="er-field__textarea" value={editing.scenario}
                onInput={(e) => updateField('scenario', e.detail.value)} />
            </View>
          </View>

          {/* 分类 */}
          <View className="er-group">
            <Text className="er-group__title">分类标签</Text>
            <View className="er-field">
              <Text className="er-field__label">行为类型</Text>
              <View className="er-picker-row">
                {BEHAVIOR_TYPES.map((t) => (
                  <Button key={t}
                    className={`er-picker-btn ${editing.behavior_type === t ? 'er-picker-btn--active' : ''}`}
                    onClick={() => updateField('behavior_type', t)}>{t}</Button>
                ))}
              </View>
            </View>
            <View className="er-field">
              <Text className="er-field__label">严重程度</Text>
              <View className="er-picker-row">
                {SEVERITY_LEVELS.map((t) => (
                  <Button key={t}
                    className={`er-picker-btn ${editing.severity === t ? 'er-picker-btn--active' : ''}`}
                    onClick={() => updateField('severity', t)}>{t}</Button>
                ))}
              </View>
            </View>
            <View className="er-field">
              <Text className="er-field__label">场景</Text>
              <View className="er-picker-row">
                {SCENES.map((t) => (
                  <Button key={t}
                    className={`er-picker-btn ${editing.scene === t ? 'er-picker-btn--active' : ''}`}
                    onClick={() => updateField('scene', t)}>{t}</Button>
                ))}
              </View>
            </View>
            <View className="er-field">
              <Text className="er-field__label">家属端大类</Text>
              <View className="er-picker-row">
                {CATEGORIES.map((t) => (
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
            {[
              { key: 'immediate_action', label: '即时安全干预动作' },
              { key: 'comforting_phrase', label: '情绪安抚话术' },
              { key: 'observation_metrics', label: '后续观察指标' },
              { key: 'medical_criteria', label: '就医判断标准' },
            ].map(({ key, label }) => (
              <View key={key} className={`er-field ${editing.inferred_fields?.[key] ? 'er-field--inferred' : ''}`}>
                <Text className="er-field__label">
                  {label}
                  {editing.inferred_fields?.[key] && (
                    <Text className="er-field__inferred-badge">推断</Text>
                  )}
                </Text>
                {editing.inferred_fields?.[key] && (
                  <Text className="er-field__inferred-hint">{editing.inferred_fields[key]}</Text>
                )}
                <Textarea className="er-field__textarea er-field__textarea--tall"
                  value={(editing as Record<string, string>)[key] || ''}
                  onInput={(e) => updateField(key, e.detail.value)} />
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
              <Textarea className="er-field__textarea" value={editing.caution_notes}
                onInput={(e) => updateField('caution_notes', e.detail.value)} />
            </View>
            <View className="er-field">
              <Text className="er-field__label">不适用人群/场景</Text>
              <Textarea className="er-field__textarea" value={editing.contraindications}
                onInput={(e) => updateField('contraindications', e.detail.value)} />
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
        <Button className="er-footer__save-btn" onClick={saveCard}>保存当前卡片</Button>
        <Button className="er-footer__submit-btn" onClick={submitAll}>提交全部审核</Button>
      </View>
    </View>
  );
}
