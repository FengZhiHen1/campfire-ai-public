import { useState, useEffect } from 'react';
import { View, Text, Button, Textarea } from '@tarojs/components';
import { useConsult } from '../../../logics/consult/hooks/useConsult';
import { listProfiles } from '../../../logics/profiles/services/profileApi';
import type { BehaviorTypeCategory, EmotionLevel } from '../../../logics/consult/types';
import type { ProfileListItem } from '@campfire/ts-shared';
import './index.scss';

const BEHAVIOR_OPTIONS: { value: BehaviorTypeCategory; label: string }[] = [
  { value: 'SELF_INJURY', label: '自伤行为' },
  { value: 'AGGRESSION', label: '攻击行为' },
  { value: 'ELOPEMENT', label: '出走/逃跑' },
  { value: 'MEDICATION', label: '用药相关' },
  { value: 'EMOTIONAL_MELTDOWN', label: '情绪崩溃' },
  { value: 'STEREOTYPY', label: '刻板行为' },
  { value: 'OTHER', label: '其他' },
];

const EMOTION_OPTIONS: { value: EmotionLevel; label: string }[] = [
  { value: '轻', label: '轻度' },
  { value: '中', label: '中度' },
  { value: '重', label: '重度' },
];

const CRISIS_LABEL_MAP: Record<string, { text: string; className: string }> = {
  mild: { text: '风险较低', className: 'mild' },
  moderate: { text: '需关注', className: 'moderate' },
  severe: { text: '高风险', className: 'severe' },
};

export default function ConsultIndex() {
  const {
    sessionState,
    behaviorTypeSelection,
    behaviorDescription,
    planSections,
    accumulatedText,
    isInputValid,
    isConsultActive,
    emotionLevel,
    referencedCases: refCases,
    crisisLevel,
    startConsult,
    setBehaviorTypes,
    setBehaviorDescription,
    setEmotionLevel,
    submitConsult,
    cancelSelection,
    retrySubmit,
    goBackToIdle,
    retryStream,
    startNewConsult,
    goToTicket,
    getErrorMessage,
    errorCode,
    selectedProfileId,
    setSelectedProfile,
  } = useConsult();

  const [inputText, setInputText] = useState(behaviorDescription);
  const [profiles, setProfiles] = useState<ProfileListItem[]>([]);

  useEffect(() => {
    listProfiles()
      .then((data) => setProfiles(data as ProfileListItem[]))
      .catch(() => {});
  }, []);

  const toggleType = (type: BehaviorTypeCategory) => {
    const selection = behaviorTypeSelection ?? [];
    const next = selection.includes(type)
      ? selection.filter((t) => t !== type)
      : [...selection, type];
    setBehaviorTypes(next);
  };

  const handleInputChange = (val: string) => {
    setInputText(val);
    setBehaviorDescription(val);
  };

  // ----- idle: 入口 -----
  if (sessionState === 'idle') {
    return (
      <View className="consult-page consult-idle">
        <View className="consult-idle__hero">
          <Text className="consult-idle__hero-icon">🔥</Text>
        </View>
        <Text className="consult-idle__title">应急咨询</Text>
        <Text className="consult-idle__subtitle">
          描述孩子当前的行为表现，获取应急干预建议
        </Text>
        <Button className="consult-idle__start-btn" onClick={startConsult}>
          开始咨询
        </Button>
      </View>
    );
  }

  // ----- selecting_behavior: 输入表单 -----
  if (sessionState === 'selecting_behavior') {
    return (
      <View className="consult-page consult-selecting">
        {/* 档案选择 */}
        {profiles.length > 0 && (
          <View className="consult-selecting__profile-section">
            <Text className="consult-selecting__label">关联档案（可选）</Text>
            <View className="consult-selecting__profile-list">
              <Button
                className={`consult-selecting__profile-btn ${!selectedProfileId ? 'consult-selecting__profile-btn--active' : ''}`}
                onClick={() => setSelectedProfile(undefined)}
              >
                不关联
              </Button>
              {profiles.map((p) => (
                <Button
                  key={p.profile_id}
                  className={`consult-selecting__profile-btn ${selectedProfileId === p.profile_id ? 'consult-selecting__profile-btn--active' : ''}`}
                  onClick={() => setSelectedProfile(p.profile_id)}
                >
                  {p.nickname || '未命名'}
                </Button>
              ))}
            </View>
          </View>
        )}

        <Text className="consult-selecting__label">选择行为类型（可多选）</Text>
        <View className="consult-selecting__grid">
          {BEHAVIOR_OPTIONS.map((opt) => {
            const selected = (behaviorTypeSelection ?? []).includes(opt.value);
            return (
              <Button
                key={opt.value}
                className={`consult-selecting__option ${selected ? 'consult-selecting__option--selected' : ''}`}
                onClick={() => toggleType(opt.value)}
              >
                {selected && (
                  <View className="consult-selecting__check">✓</View>
                )}
                <Text className="consult-selecting__option-text">{opt.label}</Text>
              </Button>
            );
          })}
        </View>

        <Text className="consult-selecting__label">情绪等级</Text>
        <View className="consult-selecting__emotion-row">
          {EMOTION_OPTIONS.map((opt) => {
            const active = emotionLevel === opt.value;
            return (
              <Button
                key={opt.value}
                className={`consult-selecting__emotion-btn ${active ? 'consult-selecting__emotion-btn--active' : ''}`}
                onClick={() => setEmotionLevel(opt.value)}
              >
                {opt.label}
              </Button>
            );
          })}
        </View>

        <Text className="consult-selecting__label">描述当前行为表现</Text>
        <Textarea
          className="consult-selecting__textarea"
          value={inputText}
          onInput={(e) => handleInputChange(e.detail.value)}
          placeholder="例如：孩子在商场突然捂住耳朵蹲下尖叫..."
          maxlength={2000}
        />

        <View className="consult-selecting__actions">
          <Button
            className="consult-selecting__submit-btn"
            onClick={submitConsult}
            disabled={!isInputValid}
          >
            获取应急建议
          </Button>
          <Button className="consult-selecting__cancel-btn" onClick={cancelSelection}>
            取消
          </Button>
        </View>
      </View>
    );
  }

  // ----- submitting: 提交中 -----
  if (sessionState === 'submitting') {
    return (
      <View className="consult-page consult-submitting">
        <View className="consult-submitting__skeleton" />
        <Text className="consult-submitting__text">正在分析并生成建议...</Text>
      </View>
    );
  }

  // ----- streaming / completed: 结果展示 -----
  if (sessionState === 'streaming' || sessionState === 'completed') {
    const crisisInfo = crisisLevel ? CRISIS_LABEL_MAP[crisisLevel] : null;

    return (
      <View className="consult-page consult-streaming">
        {sessionState === 'streaming' && (
          <Text className="consult-streaming__status">正在生成建议...</Text>
        )}

        {/* 危机等级标识 */}
        {crisisInfo && (
          <View className={`consult-streaming__crisis-badge consult-streaming__crisis-badge--${crisisInfo.className}`}>
            <Text className="consult-streaming__crisis-text">{crisisInfo.text}</Text>
          </View>
        )}

        {/* 实时文本展示 */}
        {accumulatedText && (
          <View className="consult-streaming__ai-bubble">
            <Text className="consult-streaming__ai-text">
              {accumulatedText}
              {sessionState === 'streaming' && (
                <Text className="consult-streaming__cursor" />
              )}
            </Text>
          </View>
        )}

        {/* 结构化段落展示 */}
        {planSections.length > 0 && (
          <View className="consult-streaming__plan-card">
            {planSections.map((section) => {
              const barMap: Record<string, string> = {
                '即时安全干预': 'tertiary',
                '情绪安抚话术': 'primary',
                '后续观察指标': 'secondary',
                '就医判断标准': 'error',
              };
              const colorKey = barMap[section.title] || 'secondary';
              return (
                <View key={section.title} className="consult-streaming__plan-section">
                  <View className="consult-streaming__plan-header">
                    <View className={`consult-streaming__plan-bar consult-streaming__plan-bar--${colorKey}`} />
                    <Text className={`consult-streaming__plan-title consult-streaming__plan-title--${colorKey}`}>
                      {section.title}
                    </Text>
                  </View>
                  {section.contents.length === 0 ? (
                    <Text className="consult-streaming__plan-line">（等待内容...）</Text>
                  ) : (
                    section.contents.map((line, idx) => (
                      <Text key={idx} className="consult-streaming__plan-line">• {line}</Text>
                    ))
                  )}
                </View>
              );
            })}
          </View>
        )}

        {/* 参考案例溯源 */}
        {refCases.length > 0 && (
          <View className="consult-streaming__refs">
            <Text className="consult-streaming__refs-title">参考案例</Text>
            {refCases.map((rc) => (
              <View key={rc.slice_id} className="consult-streaming__ref-card">
                <Text className="consult-streaming__ref-card-title">{rc.case_title}</Text>
                <Text className="consult-streaming__ref-card-text">{rc.slice_text}</Text>
              </View>
            ))}
          </View>
        )}

        {sessionState === 'completed' && (
          <View className="consult-streaming__done">
            <Text className="consult-streaming__done-text">生成完毕</Text>
            <Button className="consult-streaming__new-btn" onClick={startNewConsult}>
              新的咨询
            </Button>
          </View>
        )}
      </View>
    );
  }

  // ----- ticket_guide: 工单引导 -----
  if (sessionState === 'ticket_guide') {
    return (
      <View className="consult-page consult-ticket-guide">
        <View className="consult-ticket-guide__icon">🆘</View>
        <Text className="consult-ticket-guide__title">建议联系专家</Text>
        <Text className="consult-ticket-guide__desc">
          AI 对当前情况的置信度较低，建议通过人工咨询获取更准确的建议。
        </Text>
        <View className="consult-ticket-guide__actions">
          <Button className="consult-ticket-guide__expert-btn" onClick={goToTicket}>
            联系专家
          </Button>
          <Button className="consult-ticket-guide__new-btn" onClick={startNewConsult}>
            开始新咨询
          </Button>
        </View>
      </View>
    );
  }

  // ----- submit_failed / stream_failed: 错误重试 -----
  if (sessionState === 'submit_failed' || sessionState === 'stream_failed') {
    return (
      <View className="consult-page consult-error">
        <View className="consult-error__icon">⚠️</View>
        <Text className="consult-error__title">出错了</Text>
        <Text className="consult-error__message">
          {errorCode ? getErrorMessage(errorCode) : '未知错误'}
        </Text>
        <View className="consult-error__actions">
          {sessionState === 'submit_failed' && (
            <Button className="consult-error__retry-btn" onClick={retrySubmit}>
              重试提交
            </Button>
          )}
          {sessionState === 'stream_failed' && (
            <Button className="consult-error__retry-btn" onClick={retryStream}>
              重新生成
            </Button>
          )}
          <Button className="consult-error__back-btn" onClick={goBackToIdle}>
            返回首页
          </Button>
        </View>
      </View>
    );
  }

  // fallback
  return (
    <View className="consult-page consult-error">
      <View className="consult-error__icon">❓</View>
      <Text className="consult-error__title">未知状态</Text>
      <Text className="consult-error__message">{sessionState}</Text>
      <Button className="consult-error__back-btn" onClick={goBackToIdle}>
        返回首页
      </Button>
    </View>
  );
}
