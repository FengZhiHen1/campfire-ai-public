/**
 * 模块: features/consult/viewModel/useEmergencyForm
 * 职责: 应急表单的分步流控制器——一屏一题、作答/跳过推进、退出确认、随时提交与失败保留
 * 数据来源:
 *   - docs/design/pages/应急表单页.md: MUST — 布局结构（一屏一题、进度条、常驻提交）、
 *     状态覆盖表、「功能语义审查修订」（跳过后推进下一题、已填写内容退出时确认丢弃、
 *     提交中停止改题与改答案）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 6 节（八项全可跳过、提交即跳页）
 *   - docs/需求/功能需求与验收.md: MUST — RQ-EMG-01（跳过 = 未排除，不得默认为正常）
 * 边界:
 *   - 依赖: domain/emergency（题面与草稿规则）、application 用例、domain/errors
 *   - 被依赖: view 的应急表单页
 * 禁止行为:
 *   - 禁止把未作答项当成正常值（domain/emergency 的 toEmergencyItems 负责，不在此重复）
 *   - 禁止提交失败时清空已填内容（页面设计状态覆盖表「提交失败」行）
 *   - 禁止用进度百分比数字（页面设计布局结构第 2 条：位置感足够）
 *   - 禁止在本层导航：退出确认只回答「要不要确认」，跳转由视图按返回值执行
 */

import { useCallback, useMemo, useRef, useState } from 'react';

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

/**
 * 一道题在现场采集里的状态。
 *
 * 三种状态互斥：`answered` 是给出了取值或文本；`skipped` 是显式跳过；`unanswered` 是还没碰。
 * 后两种在提交载荷里都写成 `skipped: true`（未作答 = 未排除，domain/emergency 负责），
 * 但界面上必须分开表达——「跳过的题」是本轮的显式决定，不能读成「还没看」。
 */
export type EmergencyStepStatus = 'answered' | 'skipped' | 'unanswered';

/** 一道题及其现场状态（顺序与 EMERGENCY_QUESTIONS 一致）。 */
export interface EmergencyStepState {
  key: string;
  status: EmergencyStepStatus;
}

/**
 * 请求退出的判定结果。
 *
 * `leave` = 没有已处理内容，调用方可以直接导航；`confirm` = 已填内容会丢，必须先确认。
 * 判定留在控制器、导航留在视图：把「要不要确认」这条规则与路由解耦后，它可以被单测。
 */
export type EmergencyExitDecision = 'leave' | 'confirm';

/** 应急表单控制器。 */
export interface EmergencyFormController {
  questions: readonly EmergencyQuestion[];
  index: number;
  total: number;
  current: EmergencyQuestion;
  /** 当前题的草稿。 */
  answer: EmergencyAnswerDraft;
  /** 八题的现场状态；进度、已处理数与「已跳过」标注都由它派生。 */
  steps: readonly EmergencyStepState[];
  /** 当前题的状态。 */
  currentStatus: EmergencyStepStatus;
  /** 已作答题数（不含跳过）。 */
  answered: number;
  /** 已跳过题数（按未排除处理）。 */
  skipped: number;
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
  /** 退出确认单是否打开（打开期间视图渲染确认单）。 */
  exitConfirmOpen: boolean;
  toggle(value: string): void;
  choose(value: string): void;
  setNote(text: string): void;
  /** 跳过当前题；非末题同时推进到下一题（页面设计「跳过后推进下一题」）。 */
  skip(): void;
  next(): void;
  previous(): void;
  /** 请求退出：有已处理内容时打开确认单并返回 confirm，否则返回 leave。 */
  requestExit(): EmergencyExitDecision;
  /** 关闭退出确认单，留在原处继续填写。 */
  cancelExit(): void;
  /** 确认丢弃已填内容；导航由调用方完成（本层不持有路由）。 */
  confirmDiscard(): void;
  /** 提交（不需要答完）；成功后经 onStarted 回调跳转对话页。 */
  submit(): Promise<void>;
}

/** 取某题的现场状态：显式跳过优先于「已作答」，「未作答」是两者的补集。 */
function stepStatusOf(draft: EmergencyDraft, key: string): EmergencyStepStatus {
  const answer = emergencyAnswerFor(draft, key);
  if (answer.skipped) return 'skipped';
  return isHandled(draft, key) ? 'answered' : 'unanswered';
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
  const [exitConfirmOpen, setExitConfirmOpen] = useState(false);
  // 并发闸门（FE-12）：提交按钮的 disabled 之外还有键盘与程序化路径。
  // 同一把闸门也负责「提交中停止改题」：载荷在按下按钮时已经确定，此时仍允许改答案
  // 会让界面答案与已提交内容不一致（页面设计「功能语义审查修订」）。
  const inFlight = useRef(false);

  const total = EMERGENCY_QUESTIONS.length;
  const current = EMERGENCY_QUESTIONS[index] ?? EMERGENCY_QUESTIONS[0];
  if (current === undefined) throw new Error('应急采集题面为空');

  const steps = useMemo(
    () => EMERGENCY_QUESTIONS.map((question) => ({ key: question.key, status: stepStatusOf(draft, question.key) })),
    [draft],
  );
  const answered = steps.filter((step) => step.status === 'answered').length;
  const skipped = steps.filter((step) => step.status === 'skipped').length;
  const currentStatus = steps[index]?.status ?? 'unanswered';

  const updateCurrent = useCallback((next: EmergencyDraft) => setDraft(next), []);

  const toggle = useCallback(
    (value: string) => {
      if (inFlight.current) return;
      updateCurrent(toggleOption(draft, current.key, value));
    },
    [current.key, draft, updateCurrent],
  );

  const choose = useCallback(
    (value: string) => {
      if (inFlight.current) return;
      updateCurrent(selectOption(draft, current.key, value));
    },
    [current.key, draft, updateCurrent],
  );

  const writeNote = useCallback(
    (text: string) => {
      if (inFlight.current) return;
      updateCurrent(setNote(draft, current.key, text));
    },
    [current.key, draft, updateCurrent],
  );

  const advance = useCallback(() => {
    setDirection('forward');
    setIndex((value) => Math.min(value + 1, total - 1));
  }, [total]);

  const next = useCallback(() => {
    if (inFlight.current) return;
    advance();
  }, [advance]);

  const previous = useCallback(() => {
    if (inFlight.current) return;
    setDirection('back');
    setIndex((value) => Math.max(value - 1, 0));
  }, []);

  // 跳过既写状态又推进：这一步此前由视图把 skip() 与 next() 拼在一起，
  // 拼法一改就会静默漂移（页面设计要求「跳过后推进下一题」）。
  const skip = useCallback(() => {
    if (inFlight.current) return;
    updateCurrent(skipQuestion(draft, current.key));
    advance();
  }, [advance, current.key, draft, updateCurrent]);

  const requestExit = useCallback((): EmergencyExitDecision => {
    // 有已处理内容（作答或跳过）才需要确认：什么都没填时确认单只是多一次点击。
    const hasInput = steps.some((step) => step.status !== 'unanswered');
    if (!hasInput) return 'leave';
    setExitConfirmOpen(true);
    return 'confirm';
  }, [steps]);

  const cancelExit = useCallback(() => setExitConfirmOpen(false), []);
  const confirmDiscard = useCallback(() => setExitConfirmOpen(false), []);

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
    steps,
    currentStatus,
    answered,
    skipped,
    handled: answered + skipped,
    progressRatio: (index + 1) / total,
    direction,
    isFirst: index === 0,
    isLast: index >= total - 1,
    submitting,
    failure,
    exitConfirmOpen,
    toggle,
    choose,
    setNote: writeNote,
    skip,
    next,
    previous,
    requestExit,
    cancelExit,
    confirmDiscard,
    submit,
  };
}
