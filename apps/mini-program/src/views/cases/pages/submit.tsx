import { useState } from 'react';
import { View, Text, Button, Input, Textarea, Picker } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { createCase } from '../../../logics/cases/services/caseApi';

const behaviorTypes = ['自伤', '攻击', '刻板', '逃跑', '情绪崩溃', '其他'];
const severityLevels = ['轻度', '中度', '重度'];
const scenes = ['家庭', '学校', '公共场合', '机构', '不限'];
const evidenceLevels = ['NCAEP循证实践', '机构经验总结', '个案观察记录'];

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
      await createCase({
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
      Taro.showToast({ title: '提交成功' });
      setTitle('');
      setImmediateAction('');
      setComfortingPhrase('');
      setObservationMetrics('');
      setMedicalCriteria('');
    } catch {
      Taro.showToast({ title: '提交失败', icon: 'none' });
    }
  };

  return (
    <View>
      <Text>提交案例</Text>

      <Text>标题</Text>
      <Input value={title} onInput={(e) => setTitle(e.detail.value)} placeholder="案例标题" />

      <Text>行为类型</Text>
      <Picker mode="selector" range={behaviorTypes} value={behaviorTypeIdx} onChange={(e) => setBehaviorTypeIdx(Number(e.detail.value))}>
        <View>{behaviorTypes[behaviorTypeIdx]}</View>
      </Picker>

      <Text>严重程度</Text>
      <Picker mode="selector" range={severityLevels} value={severityIdx} onChange={(e) => setSeverityIdx(Number(e.detail.value))}>
        <View>{severityLevels[severityIdx]}</View>
      </Picker>

      <Text>场景</Text>
      <Picker mode="selector" range={scenes} value={sceneIdx} onChange={(e) => setSceneIdx(Number(e.detail.value))}>
        <View>{scenes[sceneIdx]}</View>
      </Picker>

      <Text>循证等级</Text>
      <Picker mode="selector" range={evidenceLevels} value={evidenceLevelIdx} onChange={(e) => setEvidenceLevelIdx(Number(e.detail.value))}>
        <View>{evidenceLevels[evidenceLevelIdx]}</View>
      </Picker>

      <Text>即时干预动作</Text>
      <Textarea
        value={immediateAction}
        onInput={(e) => setImmediateAction(e.detail.value)}
        placeholder="描述即时安全干预动作..."
        maxlength={2000}
      />

      <Text>安抚话术</Text>
      <Textarea
        value={comfortingPhrase}
        onInput={(e) => setComfortingPhrase(e.detail.value)}
        placeholder="描述情绪安抚话术..."
        maxlength={2000}
      />

      <Text>观察指标</Text>
      <Textarea
        value={observationMetrics}
        onInput={(e) => setObservationMetrics(e.detail.value)}
        placeholder="描述后续观察指标..."
        maxlength={2000}
      />

      <Text>就医判断标准</Text>
      <Textarea
        value={medicalCriteria}
        onInput={(e) => setMedicalCriteria(e.detail.value)}
        placeholder="描述就医判断标准..."
        maxlength={2000}
      />

      <Button onClick={handleSubmit}>提交案例</Button>
    </View>
  );
}
