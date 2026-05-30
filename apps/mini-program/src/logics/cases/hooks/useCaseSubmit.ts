/**
 * CASE-09 案例管理逻辑 — 案例提交页 Hook。
 *
 * 封装 CasesSubmit 页面的全部业务逻辑：表单状态、字段校验、
 * API 调用（createCase + submitCase）。View 层仅负责 JSX 渲染。
 *
 * 调用路径：views/cases/pages/submit → useCaseSubmit → caseApi
 *           views/ → useCaseSubmit → useCaseStore (Zustand, 自动保存草稿)
 */

import { useState, useCallback } from 'react';
import Taro from '@tarojs/taro';
import { createCase, submitCase } from '../services/caseApi';
import { useCaseStore } from '../store/caseStore';
import {
  BEHAVIOR_TYPE_OPTIONS,
  BEHAVIOR_TYPE_VALUES,
  SEVERITY_OPTIONS,
  SEVERITY_VALUES,
  SCENE_OPTIONS,
  SCENE_VALUES,
  EVIDENCE_LEVEL_OPTIONS,
  EVIDENCE_LEVEL_VALUES,
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
  isSubmitting: boolean;
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
// 辅助函数
// ============================================================================

function indexOfSafe(arr: readonly string[], val: string): number {
  const idx = arr.indexOf(val);
  return idx >= 0 ? idx : 0;
}

// ============================================================================
// Hook
// ============================================================================

export function useCaseSubmit(): UseCaseSubmitReturn {
  const fields = useCaseStore((s) => s.fields);
  const setField = useCaseStore((s) => s.setField);
  const resetForm = useCaseStore((s) => s.resetForm);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // 从草稿恢复索引
  const [behaviorTypeIdx, setBehaviorTypeIdxRaw] = useState<number>(() =>
    indexOfSafe(BEHAVIOR_TYPE_VALUES, fields.behavior_type),
  );
  const [severityIdx, setSeverityIdxRaw] = useState<number>(() =>
    indexOfSafe(SEVERITY_VALUES, fields.severity),
  );
  const [sceneIdx, setSceneIdxRaw] = useState<number>(() =>
    indexOfSafe(SCENE_VALUES, fields.scene),
  );
  const [evidenceLevelIdx, setEvidenceLevelIdxRaw] = useState<number>(() =>
    indexOfSafe(EVIDENCE_LEVEL_VALUES, fields.evidence_level),
  );

  const setBehaviorTypeIdx = useCallback((idx: number) => {
    setBehaviorTypeIdxRaw(idx);
    setField('behavior_type', BEHAVIOR_TYPE_VALUES[idx]);
  }, [setField]);

  const setSeverityIdx = useCallback((idx: number) => {
    setSeverityIdxRaw(idx);
    setField('severity', SEVERITY_VALUES[idx]);
  }, [setField]);

  const setSceneIdx = useCallback((idx: number) => {
    setSceneIdxRaw(idx);
    setField('scene', SCENE_VALUES[idx]);
  }, [setField]);

  const setEvidenceLevelIdx = useCallback((idx: number) => {
    setEvidenceLevelIdxRaw(idx);
    setField('evidence_level', EVIDENCE_LEVEL_VALUES[idx]);
  }, [setField]);

  const setTitle = useCallback((v: string) => {
    setField('title', v);
  }, [setField]);

  const quartetValues: Record<string, string> = {
    immediate_action: fields.immediate_action,
    comforting_phrase: fields.comforting_phrase,
    observation_metrics: fields.observation_metrics,
    medical_criteria: fields.medical_criteria,
  };

  const quartetSetter = useCallback((key: string, value: string) => {
    if (key === 'immediate_action' || key === 'comforting_phrase'
      || key === 'observation_metrics' || key === 'medical_criteria') {
      setField(key, value);
    }
  }, [setField]);

  const handleSubmit = useCallback(async () => {
    if (!fields.title.trim()) {
      Taro.showToast({ title: '标题为必填', icon: 'none' });
      return;
    }
    if (!fields.immediate_action.trim() || !fields.comforting_phrase.trim()
      || !fields.observation_metrics.trim() || !fields.medical_criteria.trim()) {
      Taro.showToast({ title: '四段式字段均为必填', icon: 'none' });
      return;
    }
    setIsSubmitting(true);
    try {
      const request: CaseCreateRequest = {
        title: fields.title,
        behavior_type: BEHAVIOR_TYPE_VALUES[behaviorTypeIdx] as CaseCreateRequest['behavior_type'],
        severity: SEVERITY_VALUES[severityIdx] as CaseCreateRequest['severity'],
        scene: SCENE_VALUES[sceneIdx] as CaseCreateRequest['scene'],
        evidence_level: EVIDENCE_LEVEL_VALUES[evidenceLevelIdx] as CaseCreateRequest['evidence_level'],
        immediate_action: fields.immediate_action,
        comforting_phrase: fields.comforting_phrase,
        observation_metrics: fields.observation_metrics,
        medical_criteria: fields.medical_criteria,
      };
      const draft = await createCase(request);
      await submitCase(draft.case_id);
      resetForm();
      Taro.showToast({ title: '案例已提交审核' });
      Taro.showModal({
        title: '提交成功',
        content: '案例已提交审核，审核通过后将出现在公共案例库中。',
        showCancel: false,
        confirmText: '知道了',
      });
      Taro.navigateBack();
    } catch (err: unknown) {
      const msg: string = err instanceof Error ? err.message : '提交失败';
      Taro.showToast({ title: msg, icon: 'none' });
    } finally {
      setIsSubmitting(false);
    }
  }, [fields, behaviorTypeIdx, severityIdx, sceneIdx, evidenceLevelIdx, resetForm]);

  return {
    title: fields.title,
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
    isSubmitting,
    handleSubmit,
    behaviorTypeOptions: BEHAVIOR_TYPE_OPTIONS,
    severityOptions: SEVERITY_OPTIONS,
    sceneOptions: SCENE_OPTIONS,
    evidenceLevelOptions: EVIDENCE_LEVEL_OPTIONS,
    quartetConfig: QUARTET_CONFIG,
  };
}
