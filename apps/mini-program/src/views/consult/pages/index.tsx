import { useState } from 'react';
import { View, Text, Button, Textarea } from '@tarojs/components';
import { useConsult } from '../../../logics/consult/hooks/useConsult';
import type { BehaviorTypeCategory } from '../../../logics/consult/types';

const BEHAVIOR_OPTIONS: { value: BehaviorTypeCategory; label: string }[] = [
  { value: 'SELF_INJURY', label: '自伤行为' },
  { value: 'AGGRESSION', label: '攻击行为' },
  { value: 'ELOPEMENT', label: '出走/逃跑' },
  { value: 'MEDICATION', label: '用药相关' },
  { value: 'EMOTIONAL_MELTDOWN', label: '情绪崩溃' },
  { value: 'STEREOTYPY', label: '刻板行为' },
  { value: 'OTHER', label: '其他' },
];

export default function ConsultIndex() {
  const {
    sessionState,
    behaviorTypeSelection,
    behaviorDescription,
    planSections,
    accumulatedText,
    isInputValid,
    isConsultActive,
    startConsult,
    setBehaviorTypes,
    setBehaviorDescription,
    submitConsult,
    cancelSelection,
    retrySubmit,
    goBackToIdle,
    retryStream,
    startNewConsult,
    getErrorMessage,
    errorCode,
  } = useConsult();

  const [inputText, setInputText] = useState(behaviorDescription);

  const toggleType = (type: BehaviorTypeCategory) => {
    const next = behaviorTypeSelection.includes(type)
      ? behaviorTypeSelection.filter((t) => t !== type)
      : [...behaviorTypeSelection, type];
    setBehaviorTypes(next);
  };

  const handleInputChange = (val: string) => {
    setInputText(val);
    setBehaviorDescription(val);
  };

  // ----- idle: 入口 -----
  if (sessionState === 'idle') {
    return (
      <View>
        <Text>应急咨询</Text>
        <Text>描述孩子当前的行为表现，获取应急干预建议</Text>
        <Button onClick={startConsult}>开始咨询</Button>
      </View>
    );
  }

  // ----- selecting_behavior: 输入表单 -----
  if (sessionState === 'selecting_behavior') {
    return (
      <View>
        <Text>选择行为类型（可多选）</Text>
        {BEHAVIOR_OPTIONS.map((opt) => (
          <Button
            key={opt.value}
            onClick={() => toggleType(opt.value)}
          >
            {behaviorTypeSelection.includes(opt.value) ? '[✓]' : '[ ]'} {opt.label}
          </Button>
        ))}

        <Text>描述当前行为表现</Text>
        <Textarea
          value={inputText}
          onInput={(e) => handleInputChange(e.detail.value)}
          placeholder="例如：孩子在商场突然捂住耳朵蹲下尖叫..."
          maxlength={2000}
        />

        <Button onClick={submitConsult} disabled={!isInputValid}>
          获取应急建议
        </Button>
        <Button onClick={cancelSelection}>取消</Button>
      </View>
    );
  }

  // ----- submitting: 提交中 -----
  if (sessionState === 'submitting') {
    return (
      <View>
        <Text>正在分析并生成建议...</Text>
      </View>
    );
  }

  // ----- streaming / completed: 结果展示 -----
  if (sessionState === 'streaming' || sessionState === 'completed') {
    return (
      <View>
        {sessionState === 'streaming' && <Text>正在生成建议...</Text>}

        {/* 实时文本展示 */}
        <Text>{accumulatedText}</Text>

        {/* 结构化段落展示 */}
        {planSections.map((section) => (
          <View key={section.title}>
            <Text>--- {section.title} ---</Text>
            {section.contents.length === 0 ? (
              <Text>（等待内容...）</Text>
            ) : (
              section.contents.map((line, idx) => (
                <Text key={idx}>• {line}</Text>
              ))
            )}
          </View>
        ))}

        {sessionState === 'completed' && (
          <View>
            <Text>--- 生成完毕 ---</Text>
            <Button onClick={startNewConsult}>新的咨询</Button>
          </View>
        )}
      </View>
    );
  }

  // ----- submit_failed / stream_failed: 错误重试 -----
  if (sessionState === 'submit_failed' || sessionState === 'stream_failed') {
    return (
      <View>
        <Text>出错了</Text>
        <Text>{errorCode ? getErrorMessage(errorCode) : '未知错误'}</Text>
        {sessionState === 'submit_failed' && (
          <Button onClick={retrySubmit}>重试提交</Button>
        )}
        {sessionState === 'stream_failed' && (
          <Button onClick={retryStream}>重新生成</Button>
        )}
        <Button onClick={goBackToIdle}>返回首页</Button>
      </View>
    );
  }

  // fallback
  return (
    <View>
      <Text>未知状态: {sessionState}</Text>
      <Button onClick={goBackToIdle}>返回首页</Button>
    </View>
  );
}
