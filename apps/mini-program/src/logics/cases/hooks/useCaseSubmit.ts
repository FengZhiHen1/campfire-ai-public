/**
 * CASE-09 案例管理逻辑 — 案例提交页 Hook。
 *
 * 封装 CasesSubmit 页面的全部业务逻辑：表单状态、字段校验、
 * API 调用（createCase + submitCase）。View 层仅负责 JSX 渲染。
 *
 * 调用路径：views/cases/pages/submit → useCaseSubmit → caseApi
 */

import { useState, useCallback } from 'react';
import Taro from '@tarojs/taro';
import { createCase, submitCase } from '../services/caseApi';
import {
  BEHAVIOR_TYPE_OPTIONS,
  SEVERITY_OPTIONS,
  SCENE_OPTIONS,
  EVIDENCE_LEVEL_OPTIONS,
} from '../types/constants';
import type { CaseCreateRequest } from '@campfire/ts-shared';

// ============================================================================
// 类型定义
// ============================================================================

interface QuartetFieldConfig {
  key: 'immediate_action' | 'comforting_phrase' | 'observation_metrics' | 'medical_criteria';
  title: string;
  accent: string;
  color: string;
  hint: string;
}

/** useCaseSubmit 的返回值 */
export interface UseCaseSubmitReturn {
  title: string;
  setTitle: (v: string) => void;
  behaviorTypeIdx: number;
  setBehaviorTypeIdx: (v: number) => void;
  severityIdx: number;
  setSeverityIdx: (v: number) => void;
  sceneIdx: number;
  setSceneIdx: (v: number) => void;
  evidenceLevelIdx: number;
  setEvidenceLevelIdx: (v: number) => void;
  quartetValues: Record<string, string>;
  quartetSetter: (key: string, value: string) => void;
  handleSubmit: () => Promise<void>;
  behaviorTypeOptions: readonly string[];
  severityOptions: readonly string[];
  sceneOptions: readonly string[];
  evidenceLevelOptions: readonly string[];
  quartetConfig: readonly QuartetFieldConfig[];
}

// ============================================================================
// 常量
// ============================================================================

const QUARTET_CONFIG: readonly QuartetFieldConfig[] = [
  {
    key: 'immediate_action',
    title: '即时干预动作',
    accent: 'action',
    color: 'action',
    hint: '描述采取的具体干预措施、执行者、持续时间',
  },
  {
    key: 'comforting_phrase',
    title: '安抚话术',
    accent: 'behavior',
    color: 'behavior',
    hint: '描述孩子的具体行为、持续时间、严重程度',
  },
  {
    key: 'observation_metrics',
    title: '观察指标',
    accent: 'result',
    color: 'result',
    hint: '描述干预后的效果、后续观察建议',
  },
  {
    key: 'medical_criteria',
    title: '就医判断标准',
    accent: 'result',
    color: 'result',
    hint: '描述是否需要就医及判断依据',
  },
];

// ============================================================================
// Hook
// ============================================================================

export function useCaseSubmit(): UseCaseSubmitReturn {
  const [title, setTitle] = useState('');
  const [behaviorTypeIdx, setBehaviorTypeIdx] = useState(0);
  const [severityIdx, setSeverityIdx] = useState(0);
  const [sceneIdx, setSceneIdx] = useState(0);
  const [evidenceLevelIdx, setEvidenceLevelIdx] = useState(0);
  const [immediateAction, setImmediateAction] = useState('');
  const [comfortingPhrase, setComfortingPhrase] = useState('');
  const [observationMetrics, setObservationMetrics] = useState('');
  const [medicalCriteria, setMedicalCriteria] = useState('');

  const quartetValues: Record<string, string> = {
    immediate_action: immediateAction,
    comforting_phrase: comfortingPhrase,
    observation_metrics: observationMetrics,
    medical_criteria: medicalCriteria,
  };

  const quartetSetters: Record<string, (v: string) => void> = {
    immediate_action: setImmediateAction,
    comforting_phrase: setComfortingPhrase,
    observation_metrics: setObservationMetrics,
    medical_criteria: setMedicalCriteria,
  };

  const quartetSetter = useCallback((key: string, value: string) => {
    quartetSetters[key]?.(value);
  }, []);

  const handleSubmit = useCallback(async () => {
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
        behavior_type: BEHAVIOR_TYPE_OPTIONS[behaviorTypeIdx],
        severity: SEVERITY_OPTIONS[severityIdx],
        scene: SCENE_OPTIONS[sceneIdx],
        evidence_level: EVIDENCE_LEVEL_OPTIONS[evidenceLevelIdx],
        immediate_action: immediateAction,
        comforting_phrase: comfortingPhrase,
        observation_metrics: observationMetrics,
        medical_criteria: medicalCriteria,
      } as unknown as CaseCreateRequest);
      await submitCase(draft.case_id);
      Taro.showToast({ title: '案例已提交审核' });
      Taro.showModal({
        title: '提交成功',
        content: '案例已提交审核，审核通过后将出现在公共案例库中。',
        showCancel: false,
        confirmText: '知道了',
      });
      Taro.navigateBack();
    } catch {
      Taro.showToast({ title: '提交失败', icon: 'none' });
    }
  }, [title, behaviorTypeIdx, severityIdx, sceneIdx, evidenceLevelIdx, immediateAction, comfortingPhrase, observationMetrics, medicalCriteria]);

  return {
    title,
    setTitle,
    behaviorTypeIdx,
    setBehaviorTypeIdx,
    severityIdx,
    setSeverityIdx,
    sceneIdx,
    setSceneIdx,
    evidenceLevelIdx,
    setEvidenceLevelIdx,
    quartetValues,
    quartetSetter,
    handleSubmit,
    behaviorTypeOptions: BEHAVIOR_TYPE_OPTIONS,
    severityOptions: SEVERITY_OPTIONS,
    sceneOptions: SCENE_OPTIONS,
    evidenceLevelOptions: EVIDENCE_LEVEL_OPTIONS,
    quartetConfig: QUARTET_CONFIG,
  };
}
