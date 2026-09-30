/**
 * 模块: features/consult/viewModel/useEmergencyForm
 * 职责: 应急表单的分步流控制器——一屏一题、作答/跳过、随时提交与失败保留
 * 数据来源:
 *   - docs/design/pages/应急表单页.md: MUST — 布局结构（一屏一题、进度条、常驻提交）、状态覆盖表
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 6 节（八项全可跳过、提交即跳页）
 * 边界:
 *   - 依赖: domain/emergency（题面与草稿规则）、application 用例、domain/errors
 *   - 被依赖: view 的应急表单页
 * 禁止行为:
 *   - 禁止把未作答项当成正常值（domain/emergency 的 toEmergencyItems 负责，不在此重复）
 *   - 禁止提交失败时清空已填内容（页面设计状态覆盖表「提交失败」行）
 *   - 禁止用进度百分比数字（页面设计布局结构第 2 条：位置感足够）
 */

import { useCallback, useRef, useState } from 'react';

import type { ConsultPort } from '../application/ports';
import { EmergencyStartUseCase } from '../application/usecases';
import {
  createEmergencyDraft,
  EMERGENCY_QUESTIONS,
  emergencyAnswerFor,
  isHandled,
  selectOption,
  setNote,
  skipQuestion,
  toEmergencyItems,
  toggleOption,
  type EmergencyAnswerDraft,
  type EmergencyDraft,
  type EmergencyQuestion,
} from '../domain/emergency';
import { CONSULT_FAILURE_VIEWS, failureViewFor, type ConsultFailureView } from '../domain/errors';

/** 前进方向：用于题间的方向性滑动（240ms）。 */
export type StepDirection = 'forward' | 'back';

/** 应急表单控制器。 */
export interface EmergencyFormController {
  questions: readonly EmergencyQuestion[];
  index: number;
  total: number;
  current: EmergencyQuestion;
  /** 当前题的草稿。 */
  answer: EmergencyAnswerDraft;
  /** 已处理题数（作答或跳过）。 */
  handled: number;
  /** 进度条填充比例（0..1）；只用于位置感，不显示百分比数字。 */
  progressRatio: number;
  direction: StepDirection;
  isFirst: boolean;
  isLast: boolean;
  submitting: boolean;
  /** 提交失败原因；null = 无（提交失败不清空已填内容）。 */
  failure: ConsultFailureView | null;
  toggle(value: string): void;
  choose(value: string): void;
  setNote(text: string): void;
  skip(): void;
  next(): void;
  previous(): void;
  /** 提交（不需要答完）；成功后经 onStarted 回调跳转对话页。 */
  submit(): Promise<void>;
}

/**
 * 应急表单控制器。
 *
 * @param consult 咨询端口
 * @param onStarted 提交成功后的跳转回调（会话 id 与运行 id）
 * @throws Error 应急题面为空（八项结构缺失，属装配错误而不是运行期失败）
 */
export function useEmergencyForm(
  consult: ConsultPort,
  onStarted: (sessionId: string, runId: string) => void,
): EmergencyFormController {
  const [draft, setDraft] = useState<EmergencyDraft>(() => createEmergencyDraft());
  const [index, setIndex] = useState(0);
  const [direction, setDirection] = useState<StepDirection>('forward');
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState<ConsultFailureView | null>(null);
  // 并发闸门（FE-12）：提交按钮的 disabled 之外还有键盘与程序化路径。
  const inFlight = useRef(false);

  const total = EMERGENCY_QUESTIONS.length;
  const current = EMERGENCY_QUESTIONS[index] ?? EMERGENCY_QUESTIONS[0];
  if (current === undefined) throw new Error('应急采集题面为空');

  const updateCurrent = useCallback((next: EmergencyDraft) => setDraft(next), []);

  const toggle = useCallback(
    (value: string) => {
      updateCurrent(toggleOption(draft, current.key, value));
    },
    [current.key, draft, updateCurrent],
  );

  const choose = useCallback(
    (value: string) => {
      updateCurrent(selectOption(draft, current.key, value));
    },
    [current.key, draft, updateCurrent],
  );

  const writeNote = useCallback(
    (text: string) => {
      updateCurrent(setNote(draft, current.key, text));
    },
    [current.key, draft, updateCurrent],
  );

  const skip = useCallback(() => {
    updateCurrent(skipQuestion(draft, current.key));
  }, [current.key, draft, updateCurrent]);

  const next = useCallback(() => {
    setDirection('forward');
    setIndex((value) => Math.min(value + 1, total - 1));
  }, [total]);

  const previous = useCallback(() => {
    setDirection('back');
    setIndex((value) => Math.max(value - 1, 0));
  }, []);

  const submit = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setSubmitting(true);
    setFailure(null);
    try {
      // 离线预防：不发起注定失败的请求（页面设计状态覆盖表「网络离线预防」行）。
      if (typeof navigator !== 'undefined' && navigator.onLine === false) {
        setFailure(CONSULT_FAILURE_VIEWS.network);
        return;
      }
      const response = await new EmergencyStartUseCase(consult).execute({ items: toEmergencyItems(draft) });
      onStarted(response.session_id, response.run_id);
    } catch (error) {
      // 失败留在原处：已填内容不动（页面设计状态覆盖表「提交失败」行）。
      setFailure(failureViewFor(error));
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  }, [consult, draft, onStarted]);

  return {
    questions: EMERGENCY_QUESTIONS,
    index,
    total,
    current,
    answer: emergencyAnswerFor(draft, current.key),
    handled: EMERGENCY_QUESTIONS.filter((question) => isHandled(draft, question.key)).length,
    progressRatio: (index + 1) / total,
    direction,
    isFirst: index === 0,
    isLast: index >= total - 1,
    submitting,
    failure,
    toggle,
    choose,
    setNote: writeNote,
    skip,
    next,
    previous,
    submit,
  };
}
