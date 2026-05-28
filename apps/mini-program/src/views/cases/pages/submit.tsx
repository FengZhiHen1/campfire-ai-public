import { useState } from 'react';
import { View, Text, Button, Input, Textarea, Picker } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { createCase, submitCase } from '../../../logics/cases/services/caseApi';
import './submit.scss';

const behaviorTypes = ['自伤', '攻击', '刻板', '逃跑', '情绪崩溃', '其他'];
const severityLevels = ['轻度', '中度', '重度'];
const scenes = ['家庭', '学校', '公共场合', '机构', '不限'];
const evidenceLevels = ['NCAEP循证实践', '机构经验总结', '个案观察记录'];

const quartetConfig = [
  {
    key: 'immediate_action' as const,
    title: '即时干预动作',
    accent: 'action',
    color: 'action',
    hint: '描述采取的具体干预措施、执行者、持续时间',
  },
  {
    key: 'comforting_phrase' as const,
    title: '安抚话术',
    accent: 'behavior',
    color: 'behavior',
    hint: '描述孩子的具体行为、持续时间、严重程度',
  },
  {
    key: 'observation_metrics' as const,
    title: '观察指标',
    accent: 'result',
    color: 'result',
    hint: '描述干预后的效果、后续观察建议',
  },
  {
    key: 'medical_criteria' as const,
    title: '就医判断标准',
    accent: 'result',
    color: 'result',
    hint: '描述是否需要就医及判断依据',
  },
];

export default function CasesSubmit() {
  const [title, setTitle] = useState('');
  const [behaviorTypeIdx, setBehaviorTypeIdx] = useState(0);
  const [severityIdx, setSeverityIdx] = useState(0);
  const [sceneIdx, setSceneIdx] = useState(0);
  const [evidenceLevelIdx, setEvidenceLevelIdx] = useState(0);
  const [immediateAction, setImmediateAction] = useState('');
  const [comfortingPhrase, setComfortingPhrase] = useState('');
  const [observationMetrics, setObservationMetrics] = useState('');
  const [medicalCriteria, setMedicalCriteria] = useState('');

  const values = {
    immediate_action: immediateAction,
    comforting_phrase: comfortingPhrase,
    observation_metrics: observationMetrics,
    medical_criteria: medicalCriteria,
  };

  const setters: Record<string, (v: string) => void> = {
    immediate_action: setImmediateAction,
    comforting_phrase: setComfortingPhrase,
    observation_metrics: setObservationMetrics,
    medical_criteria: setMedicalCriteria,
  };

  const handleSubmit = async () => {
    if (!title.trim()) {
      Taro.showToast({ title: '标题为必填', icon: 'none' });
      return;
    }
    if (!immediateAction.trim() || !comfortingPhrase.trim() || !observationMetrics.trim() || !medicalCriteria.trim()) {
      Taro.showToast({ title: '四段式字段均为必填', icon: 'none' });
      return;
    }
    try {
      const draft = await createCase({
        title,
        behavior_type: behaviorTypes[behaviorTypeIdx],
        severity: severityLevels[severityIdx],
        scene: scenes[sceneIdx],
        evidence_level: evidenceLevels[evidenceLevelIdx],
        immediate_action: immediateAction,
        comforting_phrase: comfortingPhrase,
        observation_metrics: observationMetrics,
        medical_criteria: medicalCriteria,
      } as any);
      await submitCase(draft.case_id);
      Taro.showToast({ title: '提交成功' });
      setTitle('');
      setImmediateAction('');
      setComfortingPhrase('');
      setObservationMetrics('');
      setMedicalCriteria('');
      Taro.navigateBack();
    } catch {
      Taro.showToast({ title: '提交失败', icon: 'none' });
    }
  };

  return (
    <View className="submit-page">
      {/* 顶部导航栏 */}
      <View className="submit-navbar">
        <Button className="submit-navbar__back" onClick={() => Taro.navigateBack()}>
          ←
        </Button>
        <Text className="submit-navbar__title">提交案例</Text>
      </View>

      {/* 封面图占位 */}
      <View className="submit-cover">
        <Text className="submit-cover__icon">📷</Text>
        <Text className="submit-cover__text">点击上传封面图</Text>
        <Text className="submit-cover__hint">建议上传现场环境照，帮助读者理解情境</Text>
      </View>

      {/* 基础信息 */}
      <View className="submit-section-title">
        <Text className="submit-section-title__required">*</Text>
        <Text>基本信息</Text>
      </View>

      <View className="submit-section">
        <View className="submit-field">
          <Text className="submit-field__label submit-field__label--required">案例标题</Text>
          <Input
            className="submit-field__input"
            value={title}
            onInput={(e) => setTitle(e.detail.value)}
            placeholder="请输入案例标题"
          />
        </View>

        <View className="submit-row">
          <View className="submit-field">
            <Text className="submit-field__label submit-field__label--required">行为类型</Text>
            <Picker mode="selector" range={behaviorTypes} value={behaviorTypeIdx} onChange={(e) => setBehaviorTypeIdx(Number(e.detail.value))}>
              <Button className="submit-field__picker">
                <Text className="submit-field__picker-text">{behaviorTypes[behaviorTypeIdx]}</Text>
                <Text className="submit-field__picker-chevron">▼</Text>
              </Button>
            </Picker>
          </View>
          <View className="submit-field">
            <Text className="submit-field__label submit-field__label--required">严重程度</Text>
            <Picker mode="selector" range={severityLevels} value={severityIdx} onChange={(e) => setSeverityIdx(Number(e.detail.value))}>
              <Button className="submit-field__picker">
                <Text className="submit-field__picker-text">{severityLevels[severityIdx]}</Text>
                <Text className="submit-field__picker-chevron">▼</Text>
              </Button>
            </Picker>
          </View>
        </View>

        <View className="submit-row">
          <View className="submit-field">
            <Text className="submit-field__label submit-field__label--required">场景</Text>
            <Picker mode="selector" range={scenes} value={sceneIdx} onChange={(e) => setSceneIdx(Number(e.detail.value))}>
              <Button className="submit-field__picker">
                <Text className="submit-field__picker-text">{scenes[sceneIdx]}</Text>
                <Text className="submit-field__picker-chevron">▼</Text>
              </Button>
            </Picker>
          </View>
          <View className="submit-field">
            <Text className="submit-field__label submit-field__label--required">循证等级</Text>
            <Picker mode="selector" range={evidenceLevels} value={evidenceLevelIdx} onChange={(e) => setEvidenceLevelIdx(Number(e.detail.value))}>
              <Button className="submit-field__picker">
                <Text className="submit-field__picker-text">{evidenceLevels[evidenceLevelIdx]}</Text>
                <Text className="submit-field__picker-chevron">▼</Text>
              </Button>
            </Picker>
          </View>
        </View>
      </View>

      {/* 四段式内容 */}
      <View className="submit-section-title">
        <Text className="submit-section-title__required">*</Text>
        <Text>案例内容</Text>
        <Text className="submit-section-title__hint">请按四段式结构填写</Text>
      </View>

      <View className="submit-quartet">
        {quartetConfig.map((cfg) => (
          <View key={cfg.key} className="submit-card">
            <View className={`submit-card__accent submit-card__accent--${cfg.accent}`} />
            <View className="submit-card__body">
              <Text className={`submit-card__title submit-card__title--${cfg.color}`}>
                <Text className="submit-card__required">*</Text>
                {cfg.title}
              </Text>
              <Text className="submit-card__hint">{cfg.hint}</Text>
              <Textarea
                className="submit-card__textarea"
                value={values[cfg.key]}
                onInput={(e) => setters[cfg.key](e.detail.value)}
                placeholder={cfg.hint}
                maxlength={2000}
              />
            </View>
          </View>
        ))}
      </View>

      {/* 底部操作栏 */}
      <View className="submit-actions">
        <Button className="submit-actions__btn" onClick={handleSubmit}>
          提交案例
        </Button>
      </View>
    </View>
  );
}
