import { useState } from 'react';
import { View, Text, Button, Input, Textarea } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { createCase } from '../../../logics/cases/services/caseApi';

export default function CasesSubmit() {
  const [title, setTitle] = useState('');
  const [scene, setScene] = useState('');
  const [immediateAction, setImmediateAction] = useState('');
  const [comfortingPhrase, setComfortingPhrase] = useState('');
  const [observationMetrics, setObservationMetrics] = useState('');

  const handleSubmit = async () => {
    if (!title.trim() || !scene.trim()) {
      Taro.showToast({ title: '标题和场景为必填', icon: 'none' });
      return;
    }
    try {
      await createCase({
        title,
        scene,
        immediate_action: immediateAction,
        comforting_phrase: comfortingPhrase,
        observation_metrics: observationMetrics,
      } as any);
      Taro.showToast({ title: '提交成功' });
      setTitle('');
      setScene('');
      setImmediateAction('');
      setComfortingPhrase('');
      setObservationMetrics('');
    } catch {
      Taro.showToast({ title: '提交失败', icon: 'none' });
    }
  };

  return (
    <View>
      <Text>提交案例</Text>
      <Text>标题</Text>
      <Input value={title} onInput={(e) => setTitle(e.detail.value)} placeholder="案例标题" />
      <Text>场景描述</Text>
      <Textarea
        value={scene}
        onInput={(e) => setScene(e.detail.value)}
        placeholder="描述当时的情境..."
        maxlength={2000}
      />
      <Text>即时干预动作</Text>
      <Textarea
        value={immediateAction}
        onInput={(e) => setImmediateAction(e.detail.value)}
        placeholder="你当时做了什么..."
        maxlength={2000}
      />
      <Text>安抚话术</Text>
      <Textarea
        value={comfortingPhrase}
        onInput={(e) => setComfortingPhrase(e.detail.value)}
        placeholder="说了什么安抚的话..."
        maxlength={2000}
      />
      <Text>观察指标</Text>
      <Textarea
        value={observationMetrics}
        onInput={(e) => setObservationMetrics(e.detail.value)}
        placeholder="后续观察了哪些方面..."
        maxlength={2000}
      />
      <Button onClick={handleSubmit}>提交案例</Button>
    </View>
  );
}
