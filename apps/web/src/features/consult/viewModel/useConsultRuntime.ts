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
  /** 发送一段文本；运行中或空文本不发送。@returns 是否真的起了一轮（false 时草稿要留着） */
  send(text: string): boolean;
  /** 停止当前运行（保留已渲染内容并标注中断）。 */
  stop(): void;
  /** 发送整组回答（载荷已由提问卡写入 store）。@returns 是否真的起了一轮；false 时卡片须保持可作答 */
  sendAnswers(displayText: string): boolean;
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
 * @param options.onNeedsResync 订阅不可续传时请求上层重新水合（由对话页交给会话装配的 retry）
 */
export function useConsultRuntime(options: {
  sessionId: string;
  initialMessages: readonly ThreadMessageLike[];
  consult: ConsultPort;
  onNeedsResync?: () => void;
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
        peekPendingSubmission: () => useRunStore.getState().peekPendingSubmission(),
        clearPendingSubmission: () => useRunStore.getState().clearPendingSubmission(),
        onEvent: (event) => useRunStore.getState().applyRunEvent(event),
        onConnection: (connection) => useRunStore.getState().setConnection(connection),
        onFailure: (error) => useRunStore.getState().setFailure(failureViewFor(error)),
        ...(options.onNeedsResync === undefined ? {} : { onNeedsResync: options.onNeedsResync }),
        peekAttachedRunId: () => useRunStore.getState().peekAttachedRun(sessionId),
        consumeAttachIntent: () => useRunStore.getState().consumeAttachIntent(),
        clearAttachedRun: () => useRunStore.getState().clearPendingAttachedRun(),
        onDiagnostic: (message) => logDiagnostic('chatAdapter', message),
      }),
    [consult, sessionId, options.onNeedsResync],
  );

  const runtime = useLocalRuntime(adapter, { initialMessages });
  const [thread, setThread] = useState<ThreadRuntimeState>(() => runtime.thread.getState());

  // 应急入口交接：运行已在服务端启动，本页**没有新的使用者消息可 append**，因此用 startRun
  // 对既有运行直接起一轮，让 adapter 认领 run_id 并订阅（HTTP/SSE 契约第 5 节）。
  //
  // 必须在 effect 内**同步**调用（不能排到定时器/微任务）：assistant-ui 的 runtime.thread 只在
  // React 的工作循环内解析成真实线程，出了这个上下文会拿到「空线程占位符」并对任何操作抛错
  // （`empty-thread-core`）。幂等闸门收在 store 的 beginAttachRun。
  useEffect(() => {
    if (!useRunStore.getState().beginAttachRun(sessionId)) {
      if (useRunStore.getState().peekAttachedRun(sessionId) !== null) {
        logDiagnostic('attachRun', '本次装配未取得起运行资格（交接仍在，说明已由另一次装配认领）');
      }
      return;
    }
    // 认领的运行发生在已有历史之后：父消息取当前最后一条，新回答接在它后面。
    const messages = runtime.thread.getState().messages;
    const last = messages.length === 0 ? undefined : messages[messages.length - 1];
    logDiagnostic('attachRun', `认领既有运行，父消息 ${last === undefined ? '（无，接到会话开头）' : last.id}`);
    runtime.thread.startRun({ parentId: last === undefined ? null : last.id });
    // 卸载时归还资格：StrictMode 的模拟卸载会取消刚起的运行，资格不还就会把下一次装配挡住。
    return () => useRunStore.getState().releaseAttachRun();
  }, [runtime, sessionId]);

  // 订阅 runtime 的状态：只有外部系统（runtime）的回调才写 React 状态。
  // 初值由 useState 的惰性初始化给出，因此这里不需要（也不应该）同步 setState 一次。
  useEffect(() => runtime.thread.subscribe(() => setThread(runtime.thread.getState())), [runtime]);

  // 运行中不允许再次发送：闸门读 ref（同步可读），由动作函数体把关（FE-12）。
  // ref 在 effect 里跟随状态更新（渲染期写 ref 会破坏纯渲染假设）。
  const runningRef = useRef(thread.isRunning);
  useEffect(() => {
    runningRef.current = thread.isRunning;
  }, [thread.isRunning]);
  /**
   * 同步发送闸门。`runningRef` 要等 runtime 状态回调 → effect 才更新，同一帧的第二次点击
   * 会漏过去（第二次 append 会 abort 第一条运行并再落一条使用者消息）；此 ref 在动作里同步置位，
   * 运行结束（isRunning 回到 false）才放开。
   */
  const pendingSend = useRef(false);
  useEffect(() => {
    if (!thread.isRunning) pendingSend.current = false;
  }, [thread.isRunning]);

  /**
   * 发送没起成时收回乐观写入的连接态：`append` 可同步抛错（如 runtime 仍是空线程占位符）。
   * 只回 idle、不弹错误卡——这一轮没有消息可重试；抛错留一条诊断，不静默。
   */
  const rollbackSend = (error: unknown): false => {
    pendingSend.current = false;
    useRunStore.getState().setConnection('idle');
    logDiagnostic('chatSend', error instanceof Error ? error.message : String(error));
    return false;
  };

  const send = (text: string): boolean => {
    if (pendingSend.current || runningRef.current) return false;
    const content = text.trim();
    if (content === '') return false;
    pendingSend.current = true;
    // 普通输入不继承整组回答的提交件：它只在受理后才被适配器清掉，失败时会留到下一次发送，
    // 届时新输入会被旧答案顶掉。两条通道各自只带自己的载荷。
    useRunStore.getState().clearPendingSubmission();
    useRunStore.getState().setConnection('subscribing');
    try {
      runtime.thread.append(content);
      return true;
    } catch (error) {
      return rollbackSend(error);
    }
  };

  const sendAnswers = (displayText: string): boolean => {
    if (pendingSend.current || runningRef.current) return false;
    if (displayText.trim() === '') return false;
    pendingSend.current = true;
    useRunStore.getState().setConnection('subscribing');
    try {
      runtime.thread.append(displayText);
      return true;
    } catch (error) {
      // 提交件由提问卡的调用方撤回（它才知道这次提交属于哪一组），这里不猜。
      return rollbackSend(error);
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
