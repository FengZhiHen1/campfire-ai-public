/**
 * 模块: features/consult/viewModel/useConsultRuntime
 * 职责: 对话工作面的运行时装配——adapter 接线、发送/停止/整组回答、运行状态与首字降级
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 2 节（LocalRuntime 选型）、
 *     第 3 节（run_started 后输入框保留但不可发送）、第 7 节（应急首字 >10 秒降级）
 *   - docs/design/pages/对话页.md: MUST — 输入区互斥（待作答时收起 Composer/SkillPicker）
 * 边界:
 *   - 依赖: viewModel 的 store 与 chatAdapter、domain、application/ports、infrastructure/diagnostics
 *   - 被依赖: view 的对话工作面组件
 * 禁止行为:
 *   - 禁止用 `disabled` 当并发闸门（闸门收进动作函数体，FE-12）
 *   - 禁止在运行中允许再次发送（技术设计第 3 节 run_started 行）
 *   - 禁止把 reasoning 文本导出为正文（它只作为 part 留在消息里）
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  useLocalRuntime,
  type AssistantRuntime,
  type ThreadMessage,
  type ThreadMessageLike,
  type ThreadRuntimeState,
} from '@assistant-ui/react';

import { logDiagnostic } from '../../../infrastructure/diagnostics';
import type { ConsultPort } from '../application/ports';
import { failureViewFor } from '../domain/errors';
import { EMERGENCY_SKILL_ID } from '../domain/skills';
import { EMERGENCY_FIRST_TOKEN_BUDGET_MS } from '../domain/types';
import { createConsultChatAdapter } from './chatAdapter';
import { useRunStore } from './runStore';

/** 对话工作面的控制器（view 只依赖这里暴露的数据与操作）。 */
export interface ConsultWorkspaceController {
  runtime: AssistantRuntime;
  /** 运行态的只读快照（isRunning / messages，供输入区与卡片失效态使用）。 */
  thread: ThreadRuntimeState;
  /** 发送一段文本；运行中或空文本不发送。 */
  send(text: string): void;
  /** 停止当前运行（保留已渲染内容并标注中断）。 */
  stop(): void;
  /** 发送整组回答（回答载荷已由提问卡写入 store）。 */
  sendAnswers(displayText: string): void;
}

/** 消息流里是否已有助手正文（首字降级提示与「正在分析」文案的收尾判定）。 */
export function hasAssistantText(messages: readonly ThreadMessage[]): boolean {
  for (const message of messages) {
    if (message.role !== 'assistant') continue;
    if (message.content.some((part) => part.type === 'text' && part.text.trim() !== '')) return true;
  }
  return false;
}

/**
 * 装配对话工作面。
 *
 * @param options.sessionId 当前对话 id
 * @param options.initialMessages 水合得到的初始消息（组件按 sessionId 重新挂载，水合完成后才建运行时）
 * @param options.consult 咨询端口
 */
export function useConsultRuntime(options: {
  sessionId: string;
  initialMessages: readonly ThreadMessageLike[];
  consult: ConsultPort;
}): ConsultWorkspaceController {
  const { sessionId, initialMessages, consult } = options;

  const adapter = useMemo(
    () =>
      createConsultChatAdapter({
        consult,
        sessionId,
        // 状态经 store 单例读写：adapter 是 runtime 长期持有的对象，
        // 直接闭包捕获 store 快照会让它读到过期值。
        peekPendingSkill: () => useRunStore.getState().peekPendingSkill(),
        clearPendingSkill: () => useRunStore.getState().clearPendingSkill(),
        peekPendingAnswers: () => useRunStore.getState().peekPendingAnswers(),
        clearPendingAnswers: () => useRunStore.getState().clearPendingAnswers(),
        onEvent: (event) => useRunStore.getState().applyRunEvent(event),
        onConnection: (connection) => useRunStore.getState().setConnection(connection),
        onFailure: (error) => useRunStore.getState().setFailure(failureViewFor(error)),
        onDiagnostic: (message) => logDiagnostic('chatAdapter', message),
      }),
    [consult, sessionId],
  );

  const runtime = useLocalRuntime(adapter, { initialMessages });
  const [thread, setThread] = useState<ThreadRuntimeState>(() => runtime.thread.getState());

  // 订阅 runtime 的状态：只有外部系统（runtime）的回调才写 React 状态。
  // 初值由 useState 的惰性初始化给出，因此这里不需要（也不应该）同步 setState 一次。
  useEffect(() => runtime.thread.subscribe(() => setThread(runtime.thread.getState())), [runtime]);

  // 运行中不允许再次发送：闸门读 ref（同步可读），由动作函数体把关（FE-12）。
  // ref 在 effect 里跟随状态更新（渲染期写 ref 会破坏纯渲染假设）。
  const runningRef = useRef(thread.isRunning);
  useEffect(() => {
    runningRef.current = thread.isRunning;
  }, [thread.isRunning]);
  const inFlight = useRef(false);

  const send = (text: string): void => {
    if (inFlight.current || runningRef.current) return;
    const content = text.trim();
    if (content === '') return;
    inFlight.current = true;
    useRunStore.getState().setConnection('subscribing');
    try {
      runtime.thread.append(content);
    } finally {
      inFlight.current = false;
    }
  };

  const sendAnswers = (displayText: string): void => {
    if (inFlight.current || runningRef.current) return;
    if (displayText.trim() === '') return;
    inFlight.current = true;
    useRunStore.getState().setConnection('subscribing');
    try {
      runtime.thread.append(displayText);
    } finally {
      inFlight.current = false;
    }
  };

  const stop = (): void => {
    if (!runningRef.current) return;
    runtime.thread.cancelRun();
    // 取消不发终态事件（契约第 4.3 节）：前端自行把已渲染内容标为中断，
    // 不等一个永远不会到达的 run_finished（不变量 1：失败不得伪装成完整回答）。
    useRunStore.getState().markInterrupted();
  };

  // 应急首字超预算：只在应急技能运行且还没有正文时提示降级（RQ-EMG-03）。
  const hasText = hasAssistantText(thread.messages);
  const hasTextRef = useRef(hasText);
  useEffect(() => {
    hasTextRef.current = hasText;
  }, [hasText]);
  const runStartedAt = useRunStore((state) => state.runStartedAt);
  const activeSkills = useRunStore((state) => state.activeSkills);

  useEffect(() => {
    if (runStartedAt === null || !activeSkills.includes(EMERGENCY_SKILL_ID)) return;
    const timer = setTimeout(() => {
      if (!hasTextRef.current) useRunStore.getState().setSlowRun(true);
    }, EMERGENCY_FIRST_TOKEN_BUDGET_MS);
    return () => clearTimeout(timer);
  }, [runStartedAt, activeSkills]);

  const slowRun = useRunStore((state) => state.slowRun);
  useEffect(() => {
    if (hasText && slowRun) useRunStore.getState().setSlowRun(false);
  }, [hasText, slowRun]);

  return { runtime, thread, send, stop, sendAnswers };
}
