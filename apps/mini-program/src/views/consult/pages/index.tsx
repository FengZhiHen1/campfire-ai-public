import { useState, useEffect } from 'react';
import { View, Text, Button, Textarea, ScrollView } from '@tarojs/components';
import { useConsult } from '../../../logics/consult';
import type { BehaviorTypeCategory, EmotionLevel } from '../../../logics/consult';
import { useProfileStore } from '../../../logics/profiles/store/profileStore';
import { useProfile } from '../../../logics/profiles/hooks/useProfile';
import './index.scss';

const BEHAVIOR_OPTIONS: { value: BehaviorTypeCategory; label: string; icon: string; desc: string }[] = [
  { value: 'SELF_INJURY', label: '自伤行为', icon: '🩹', desc: '咬手、撞头、抓挠自己等' },
  { value: 'AGGRESSION', label: '攻击行为', icon: '👊', desc: '打人、摔东西、破坏物品等' },
  { value: 'ELOPEMENT', label: '出走/逃跑', icon: '🏃', desc: '试图离开安全区域、走失等' },
  { value: 'MEDICATION', label: '用药相关', icon: '💊', desc: '拒绝服药、误服、过量等' },
  { value: 'EMOTIONAL_MELTDOWN', label: '情绪崩溃', icon: '💢', desc: '大哭、尖叫、无法安抚等' },
  { value: 'STEREOTYPY', label: '刻板行为', icon: '🔄', desc: '重复动作、摇晃、排列物品等' },
  { value: 'OTHER', label: '其他', icon: '❓', desc: '以上都不是，请在下方描述' },
];

const EMOTION_OPTIONS: { value: EmotionLevel; label: string }[] = [
  { value: '轻', label: '轻度' },
  { value: '中', label: '中度' },
  { value: '重', label: '重度' },
];

const CRISIS_LABEL_MAP: Record<string, { text: string; className: string }> = {
  mild: { text: '轻度', className: 'mild' },
  moderate: { text: '中度', className: 'moderate' },
  severe: { text: '重度', className: 'severe' },
};

const SECTION_COLOR_MAP: Record<string, string> = {
  '即时安全干预动作': 'tertiary',
  '情绪安抚话术': 'primary',
  '后续观察指标': 'secondary',
  '就医判断标准': 'error',
};

const SECTION_ICON_MAP: Record<string, string> = {
  '即时安全干预动作': '🛡️',
  '情绪安抚话术': '💬',
  '后续观察指标': '👁️',
  '就医判断标准': '🏥',
};

export default function ConsultIndex() {
  const {
    sessionState,
    behaviorTypeSelection,
    behaviorDescription,
    planSections,
    accumulatedText,
    isInputValid,
    emotionLevel,
    referencedCases: refCases,
    crisisLevel,
    ticketGuide,
    startConsult,
    setBehaviorTypes,
    setBehaviorDescription,
    setEmotionLevel,
    submitConsult,
    cancelSelection,
    retrySubmit,
    goBackToSelecting,
    retryStream,
    startNewConsult,
    goToTicket,
    getErrorMessage,
    errorCode,
    selectedProfileId,
    setSelectedProfile,
  } = useConsult();

  const [inputText, setInputText] = useState(behaviorDescription);

  const profiles = useProfileStore((s) => s.list);
  const listState = useProfileStore((s) => s.listState);
  const { fetchProfiles } = useProfile();

  useEffect(() => {
    if (listState === 'idle' && profiles.length === 0) {
      fetchProfiles();
    }
  }, [listState, profiles.length, fetchProfiles]);

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

  const crisisInfo = crisisLevel ? CRISIS_LABEL_MAP[crisisLevel] : null;

  // ----- idle: 入口 -----
  if (sessionState === 'idle') {
    return (
      <View className="consult-page">
        <View className="consult-idle">
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
      </View>
    );
  }

  // ----- selecting_behavior: 行为选择弹窗 -----
  if (sessionState === 'selecting_behavior') {
    return (
      <View className="consult-page">
        <View className="consult-modal-overlay">
          <View className="consult-modal">
            <Text className="consult-modal__title">请选择当前行为类型</Text>
            <Text className="consult-modal__subtitle">这将帮助我们更准确地匹配案例</Text>

            {/* 档案选择 */}
            {profiles.length > 0 && (
              <>
                <Text className="consult-modal__label">关联档案（可选）</Text>
                <View className="consult-modal__profile-list">
                  <Button
                    className={`consult-modal__profile-btn ${!selectedProfileId ? 'consult-modal__profile-btn--active' : ''}`}
                    onClick={() => setSelectedProfile(undefined)}
                  >
                    不关联
                  </Button>
                  {profiles.map((p) => (
                    <Button
                      key={p.profile_id}
                      className={`consult-modal__profile-btn ${selectedProfileId === p.profile_id ? 'consult-modal__profile-btn--active' : ''}`}
                      onClick={() => setSelectedProfile(p.profile_id)}
                    >
                      {p.nickname || '未命名'}
                    </Button>
                  ))}
                </View>
              </>
            )}

            <View className="consult-modal__grid">
              {BEHAVIOR_OPTIONS.map((opt) => {
                const selected = (behaviorTypeSelection ?? []).includes(opt.value);
                return (
                  <Button
                    key={opt.value}
                    className={`consult-modal__option ${selected ? 'consult-modal__option--selected' : ''}`}
                    onClick={() => toggleType(opt.value)}
                  >
                    {selected && (
                      <View className="consult-modal__check">✓</View>
                    )}
                    <Text className="consult-modal__option-icon">{opt.icon}</Text>
                    <Text className="consult-modal__option-text">{opt.label}</Text>
                    <Text className="consult-modal__option-desc">{opt.desc}</Text>
                  </Button>
                );
              })}
            </View>

            <Text className="consult-modal__label">情绪等级</Text>
            <View className="consult-modal__emotion-row">
              {EMOTION_OPTIONS.map((opt) => {
                const active = emotionLevel === opt.value;
                return (
                  <Button
                    key={opt.value}
                    className={`consult-modal__emotion-btn ${active ? 'consult-modal__emotion-btn--active' : ''}`}
                    onClick={() => setEmotionLevel(opt.value)}
                  >
                    {opt.label}
                  </Button>
                );
              })}
            </View>

            <Text className="consult-modal__label">描述当前行为表现</Text>
            <Textarea
              className="consult-modal__textarea"
              value={inputText}
              onInput={(e) => handleInputChange(e.detail.value)}
              placeholder="例如：孩子在商场突然捂住耳朵蹲下尖叫..."
              maxlength={2000}
            />

            <View className="consult-modal__actions">
              <Button
                className="consult-modal__submit-btn"
                onClick={submitConsult}
                disabled={!isInputValid}
              >
                获取应急建议
              </Button>
              <Button className="consult-modal__skip-btn" onClick={cancelSelection}>
                以上都不是，直接描述
              </Button>
            </View>
          </View>
        </View>
      </View>
    );
  }

  // ----- submitting: 提交中加载骨架屏 -----
  if (sessionState === 'submitting') {
    return (
      <View className="consult-page">
        <View className="consult-navbar">
          <Text className="consult-navbar__title">应急咨询</Text>
        </View>
        <View className="consult-submitting">
          <View className="consult-submitting__skeleton" />
          <View className="consult-submitting__skeleton" />
          <View className="consult-submitting__skeleton" />
          <Text className="consult-submitting__text">正在分析案例库…</Text>
        </View>
      </View>
    );
  }

  // ----- streaming / completed: 结果展示 -----
  if (sessionState === 'streaming' || sessionState === 'completed') {
    return (
      <View className="consult-page">
        {/* 导航栏 */}
        <View className="consult-navbar">
          <Text className="consult-navbar__title">应急咨询</Text>
          {crisisInfo && (
            <View className={`consult-navbar__badge consult-navbar__badge--${crisisInfo.className}`}>
              <Text className="consult-navbar__badge-text">等级：{crisisInfo.text}</Text>
            </View>
          )}
        </View>

        {/* 聊天滚动区 */}
        <ScrollView className="consult-chat" scrollY>
          {/* 用户消息气泡 */}
          {behaviorDescription && (
            <View className="consult-user-bubble">
              <Text className="consult-user-bubble__text">{behaviorDescription}</Text>
            </View>
          )}

          {/* 流式文本气泡（在结构化卡片出现前） */}
          {accumulatedText && planSections.length === 0 && (
            <View className="consult-ai-bubble">
              <Text className="consult-ai-bubble__text">
                {accumulatedText}
                {sessionState === 'streaming' && <Text className="consult-cursor" />}
              </Text>
            </View>
          )}

          {/* 结构化方案卡片 */}
          {planSections.length > 0 && (
            <View className="consult-plan-card">
              <View className="consult-plan-card__header">
                <Text className="consult-plan-card__header-icon">🛡️</Text>
                <Text className="consult-plan-card__header-title">干预建议大纲</Text>
              </View>

              {planSections.map((section) => {
                const colorKey = SECTION_COLOR_MAP[section.title] || 'secondary';
                const icon = SECTION_ICON_MAP[section.title] || '•';
                const isComforting = section.title === '情绪安抚话术';

                return (
                  <View key={section.title} className="consult-plan-section">
                    <View className={`consult-plan-section__accent consult-plan-section__accent--${colorKey}`} />
                    <View className="consult-plan-section__body">
                      <View className="consult-plan-section__header">
                        <Text className="consult-plan-section__icon">{icon}</Text>
                        <Text className={`consult-plan-section__title consult-plan-section__title--${colorKey}`}>
                          {section.title}
                        </Text>
                      </View>
                      <View className="consult-plan-section__content">
                        {isComforting && section.contents.length > 0 ? (
                          <>
                            <Text className="consult-plan-section__quote">"{section.contents[0]}"</Text>
                            {section.contents.slice(1).map((line, idx) => (
                              <Text key={idx} className="consult-plan-section__line">{line}</Text>
                            ))}
                          </>
                        ) : (
                          section.contents.map((line, idx) => (
                            <Text key={idx} className="consult-plan-section__line">• {line}</Text>
                          ))
                        )}
                      </View>
                    </View>
                  </View>
                );
              })}

              {/* 卡片底部信息栏 */}
              <View className="consult-plan-footer">
                <Text className="consult-plan-footer__cases">基于 {refCases.length} 个相似案例</Text>
                {crisisInfo && (
                  <View className={`consult-confidence consult-confidence--${crisisInfo.className}`}>
                    <Text className="consult-confidence__dot">●</Text>
                    <Text className="consult-confidence__text">{crisisInfo.text}</Text>
                  </View>
                )}
              </View>
            </View>
          )}

          {/* 参考案例 */}
          {refCases.length > 0 && (
            <View className="consult-refs">
              <Text className="consult-refs__title">参考案例</Text>
              {refCases.map((rc) => (
                <View
                  key={rc.slice_id}
                  className="consult-ref-card"
                  onClick={() => Taro.navigateTo({ url: `/views/cases/pages/detail?narrativeId=${rc.case_id}` })}
                >
                  <Text className="consult-ref-card__title">{rc.case_title}</Text>
                  <Text className="consult-ref-card__text">{rc.slice_text}</Text>
                </View>
              ))}
            </View>
          )}

          {/* 完成状态 */}
          {sessionState === 'completed' && (
            <View className="consult-done">
              <Text className="consult-done__text">生成完毕</Text>
              <Button className="consult-done__new-btn" onClick={startNewConsult}>
                ✨ 开始新咨询
              </Button>
            </View>
          )}
        </ScrollView>

        {/* 人工兜底条 */}
        {ticketGuide.show && (
          <View className="consult-escalation" onClick={goToTicket}>
            <Text className="consult-escalation__icon">🚨</Text>
            <Text className="consult-escalation__text">立即联系人工专家</Text>
          </View>
        )}

        {/* 免责声明 */}
        <View className="consult-disclaimer">
          <Text className="consult-disclaimer__text">
            基于归档案例的 AI 生成建议，不构成医疗诊断。严重情况请咨询专业医生。
          </Text>
        </View>
      </View>
    );
  }

  // ----- ticket_guide: 工单引导 -----
  if (sessionState === 'ticket_guide') {
    return (
      <View className="consult-page">
        <View className="consult-navbar">
          <Text className="consult-navbar__title">应急咨询</Text>
        </View>
        <View className="consult-ticket-guide">
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
      </View>
    );
  }

  // ----- submit_failed / stream_failed: 错误重试 -----
  if (sessionState === 'submit_failed' || sessionState === 'stream_failed') {
    return (
      <View className="consult-page">
        <View className="consult-navbar">
          <Text className="consult-navbar__title">应急咨询</Text>
        </View>
        <View className="consult-error">
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
            <Button className="consult-error__back-btn" onClick={goBackToSelecting}>
              返回修改
            </Button>
          </View>
        </View>
      </View>
    );
  }

  // fallback
  return (
    <View className="consult-page">
      <View className="consult-navbar">
        <Text className="consult-navbar__title">应急咨询</Text>
      </View>
      <View className="consult-error">
        <View className="consult-error__icon">❓</View>
        <Text className="consult-error__title">未知状态</Text>
        <Text className="consult-error__message">{sessionState}</Text>
        <Button className="consult-error__back-btn" onClick={startNewConsult}>
          返回首页
        </Button>
      </View>
    </View>
  );
}
