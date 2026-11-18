/**
 * 模块: features/consult/viewModel/useChatWorkspace
 * 职责: 对话工作面的视图流程控制器——把原先散在 ChatWorkspace 里的运行呈现控制、
 *       跳过引导、草稿提交与重试、以及消息流派生判定收拢一处，View 只负责渲染。
 * 数据来源:
 *   - docs/design/pages/对话页.md: MUST — 布局结构、状态覆盖表、输入区互斥、跳过引导入口
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 3 节（状态条/发送禁用）、
 *     第 6 节（引导跳过端点）、第 7 节（失败语义与重试）
 * 边界:
 *   - 依赖: viewModel 的 useConsultRuntime 与 runStore、application 用例、domain
 *   - 被依赖: view 的 ChatWorkspace
 * 禁止行为:
 *   - 禁止在这里渲染任何 DOM（本层只出数据与操作）
 *   - 禁止改变既有语义：行为、导出与关键字面（aria 名、类名、文案）保持逐字一致，
 *     迁移只是把「取值与判定」从 View 搬到 ViewModel
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import type { ThreadMessage } from '@assistant-ui/react';

import { SkipOnboardingUseCase } from '../application/usecases';
import type { ConsultPort } from '../application/ports';
import { failureViewFor } from '../domain/errors';
import { skillLabel, EMERGENCY_SKILL_ID } from '../domain/skills';
import { PROGRESS_TEXT } from '../domain/types';
import { useConsultRuntime, type ConsultWorkspaceController } from './useConsultRuntime';
import { useRunStore, type ConsultRunState } from './runStore';

/**
 * 页头技能标签的折叠阈值（自几个起整体折叠为「技能 N 个」）。
 *
 * 取 4 的依据是 390 宽页头的实测（对话页设计布局结构第 1 条的阈值表）：
 * 3 个中文标签合计 199.45px，标题仍余 64.39px（宽度够用）；第 4 个起标题宽归零
 * （合计 265.94px，scrollWidth 56 > clientWidth 0）；第 5 个起标签越过页头右边界，
 * 文档级横向溢出（合计 332.42px，documentElement.scrollWidth 390 涨到 464）。
 *
 * 为什么按数量而不是按宽度实测：判据要与测试环境一致。实测 jsdom 不做布局
 * （clientWidth / scrollWidth / getBoundingClientRect 全为 0），且不实现 ResizeObserver
 * ——按宽度判的阈值在单测里恒不触发，那条逻辑就没有任何测试能覆盖它。
 * 因此把「宽度不足」近似为「标签数达到实测的第一个宽度不足点」，并在浏览器探针里
 * 复核真实溢出数字（见交付证据）。
 */
export const SKILL_TAG_COLLAPSE_THRESHOLD = 4;

/** 取消息流里最后一张行动卡的 id（重复评估后旧卡据此标失效）。 */
export function newestActionCardId(messages: readonly ThreadMessage[]): string | null {
  let newest: string | null = null;
  for (const message of messages) {
    if (message.role !== 'assistant') continue;
    for (const part of message.content) {
      if (part.type === 'data' && part.name === 'action-card') {
        const data = part.data as { card_id?: unknown };
        if (typeof data.card_id === 'string') newest = data.card_id;
      }
    }
  }
  return newest;
}

/**
 * 消息流里是否已经出现过「完成引导」的工具调用。
 *
 * 判定用 tool part 的 `toolName`（契约第 7 节落库的字段），不看界面文案：
 * 界面文案会随设计稿改，工具名是协议事实。**只看 `finished` 且 `ok !== false`**——
 * 未结束或失败的那次不算收束（失败仍应让使用者能跳过）。
 */
export function guideFinished(messages: readonly ThreadMessage[]): boolean {
  for (const message of messages) {
    for (const part of message.content) {
      if (part.type !== 'data' || part.name !== 'tool-call') continue;
      const view = part.data as { toolName?: unknown; state?: unknown; ok?: unknown };
      if (view.toolName === 'finish_onboarding' && view.state === 'finished' && view.ok !== false) return true;
    }
  }
  return false;
}

/** 取最后一条使用者消息的 id（重试的起点）。 */
export function lastUserIdOf(messages: readonly ThreadMessage[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message !== undefined && message.role === 'user') return message.id;
  }
  return null;
}

/** 对话工作面的视图控制器（View 只依赖这里暴露的数据与操作）。 */
export interface ChatWorkspaceController {
  /** 运行时控制器（runtime/thread/发送/停止/整组回答）。 */
  runtime: ConsultWorkspaceController;
  /** 运行态只读快照（isRunning / messages）。 */
  thread: ConsultWorkspaceController['thread'];
  /** 消息流跨 part 上下文（思考行开关、最新行动卡 id、整组回答提交）。 */
  threadContext: {
    submitAnswers(displayText: string): boolean;
    newestActionCardId: string | null;
    reasoningStreaming: boolean;
    reasoningEmergency: boolean;
  };
  /** 页头技能标签（已折叠为「技能 N 个」或逐个串联）。 */
  skillTags: readonly string[];
  /** 页头「跳过引导」入口是否显示。 */
  showSkipGuide: boolean;
  /** 跳过进行中。 */
  skipping: boolean;
  /** 跳过失败原因；null = 无。 */
  skipFailed: string | null;
  /** 点击跳过引导。 */
  skipGuide(): void;
  /** 输入器草稿。 */
  draft: string;
  setDraft(value: string): void;
  /** 提交草稿（空文本或运行中不发送；被受理才清空）。 */
  submitDraft(): void;
  /** 重试最后一轮（失败后可重试）。 */
  retryLastRun(): void;
  /** 是否处于待作答（收起输入器与技能选择器）。 */
  answering: boolean;
  /** 状态条文案；null = 不显示。 */
  statusText: string | null;
  /** 失败呈现；null = 无。 */
  failure: ConsultRunState['failure'];
  /** 候选（不进消息流，只供轻提示）。 */
  candidates: ConsultRunState['candidates'];
  /** 是否显示运行状态呼吸点。 */
  showProgressDot: boolean;
  /** 运行是否中断过。 */
  interrupted: boolean;
  /** 当前待用技能选择（传给 SkillPicker）。 */
  pendingSkill: string | null;
  /** 技能目录（传给 SkillPicker）。 */
  skills: ConsultRunState['skills'];
  /** 选择技能（只作用于下一条消息）。 */
  selectSkill(skillId: string | null): void;
}

/** 对话工作面控制器入参。 */
export interface UseChatWorkspaceOptions {
  initialDraft?: string;
  sessionId: string;
  initialMessages: Parameters<typeof useConsultRuntime>[0]['initialMessages'];
  onNeedsResync?: () => void;
  guidePending?: boolean;
  onGuideSettled?: () => void;
  consult: ConsultPort;
}

/**
 * 装配对话工作面的视图控制器。
 *
 * 前置: 历史水合已完成（loading/error 由 ChatPage 处置）
 * 后置: 输出消息流、状态条、技能标签、跳过引导、草稿与重试等全部视图所需数据与操作
 * 异常: 无
 */
export function useChatWorkspace({
  sessionId,
  initialMessages,
  initialDraft = '',
  consult,
  onNeedsResync,
  guidePending = false,
  onGuideSettled,
}: UseChatWorkspaceOptions): ChatWorkspaceController {
  const runtime = useConsultRuntime({
    sessionId,
    initialMessages,
    consult,
    ...(onNeedsResync === undefined ? {} : { onNeedsResync }),
  });
  const { thread, send, sendAnswers } = runtime;

  // 订阅会话级状态（连接、进度、失败、候选、技能等）。
  // 用选择器逐个订阅，避免任意一次 store 变更都让整个工作面重渲染。
  const connection = useRunStore((state) => state.connection);
  const progressText = useRunStore((state) => state.progressText);
  const failure = useRunStore((state) => state.failure);
  const slowRun = useRunStore((state) => state.slowRun);
  const candidates = useRunStore((state) => state.candidates);
  const interrupted = useRunStore((state) => state.interrupted);
  const activeBatchId = useRunStore((state) => state.activeBatchId);
  const skills = useRunStore((state) => state.skills);
  const pendingSkill = useRunStore((state) => state.pendingSkill);
  const activeSkills = useRunStore((state) => state.activeSkills);

  const [draft, setDraft] = useState(initialDraft);
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    if (initialDraft !== '') void navigate(location.pathname + location.search, { replace: true, state: null });
  }, [initialDraft, location.pathname, location.search, navigate]);

  // 并发闸门（FE-12）：发送按钮的 disabled 之外还有 Enter 键与程序化路径。
  const sending = useRef(false);

  const newestCardId = useMemo(() => newestActionCardId(thread.messages), [thread.messages]);
  /*
    思考行的两个呈现开关在这里取值后经上下文下发（原来由每个思考 part 各自订阅 store）。
    取值语义与原实现逐字一致：subscribing 也算流式（首个 token 到达前已在运行）。
  */
  const reasoningStreaming = connection === 'streaming' || connection === 'subscribing';
  const reasoningEmergency = activeSkills.includes(EMERGENCY_SKILL_ID);
  const threadContext = useMemo(
    () => ({ submitAnswers: sendAnswers, newestActionCardId: newestCardId, reasoningStreaming, reasoningEmergency }),
    [sendAnswers, newestCardId, reasoningStreaming, reasoningEmergency],
  );

  const skillLabels = useMemo(
    () => activeSkills.map((id) => skillLabel(skills, id)).filter((label): label is string => label !== null),
    [activeSkills, skills],
  );
  // 折叠规则：达到阈值整体折叠为「技能 N 个」，否则逐个串联（授权语义否定「+N 徽标」形态）。
  const skillTags = useMemo<readonly string[]>(() => {
    if (skillLabels.length === 0) return [];
    if (skillLabels.length >= SKILL_TAG_COLLAPSE_THRESHOLD) return [`技能 ${String(skillLabels.length)} 个`];
    return skillLabels;
  }, [skillLabels]);

  /**
   * 「跳过引导」入口的状态。
   *
   * 入口只在**引导待注入且尚未收束**时出现：`guidePending` 由对话页给出（建会话响应 / 本次
   * 会话的会话级记忆），`finished` 由消息流里的 `finish_onboarding` 工具行推出。两者任一不成立
   * 就不显示——跳过按钮在引导已完成后还挂着，会让使用者以为有东西没做完。
   */
  const finished = useMemo(() => guideFinished(thread.messages), [thread.messages]);
  const [skipping, setSkipping] = useState(false);
  const [skipFailed, setSkipFailed] = useState<string | null>(null);
  useEffect(() => {
    if (finished) onGuideSettled?.();
  }, [finished, onGuideSettled]);

  const skipGuide = (): void => {
    if (skipping) return;
    setSkipping(true);
    setSkipFailed(null);
    void (async (): Promise<void> => {
      try {
        await new SkipOnboardingUseCase(consult).execute(sessionId);
        onGuideSettled?.();
      } catch (error) {
        // 失败**不得**表现成已跳过：保留入口并说明，让使用者能再试一次。
        setSkipFailed(failureViewFor(error).message);
      } finally {
        setSkipping(false);
      }
    })();
  };

  const submitDraft = (): void => {
    if (sending.current) return;
    const content = draft.trim();
    if (content === '') return;
    sending.current = true;
    try {
      // 没被受理（运行中 / 闸门）时保留草稿：清空等于把使用者刚写的内容丢掉。
      if (send(content)) setDraft('');
    } finally {
      sending.current = false;
    }
  };

  /**
   * 重试：从最后一条使用者消息重跑一次（失败时使用者消息已留在消息流里，
   * 发送失败与运行失败都走这条路）。
   */
  const retryLastRun = (): void => {
    // 重试 = 对同一个父消息再起一轮；运行中再点会把正在跑的那一轮中止（库会先 abort 上一条）。
    if (thread.isRunning) return;
    const lastUser = lastUserIdOf(thread.messages);
    if (lastUser === null) return;
    useRunStore.getState().setFailure(null);
    useRunStore.getState().setConnection('subscribing');
    runtime.runtime.thread.startRun({ parentId: lastUser });
  };

  const answering = activeBatchId !== null;
  const statusText = answering
    ? '请先处理上面的问题'
    : connection === 'reconnecting'
      ? PROGRESS_TEXT.reconnecting
      : slowRun
        ? PROGRESS_TEXT.emergencySlow
        : progressText;

  const selectSkill = (skillId: string | null): void => {
    useRunStore.getState().selectSkill(skillId);
  };

  return {
    runtime,
    thread,
    threadContext,
    skillTags,
    showSkipGuide: guidePending && !finished,
    skipping,
    skipFailed,
    skipGuide,
    draft,
    setDraft,
    submitDraft,
    retryLastRun,
    answering,
    statusText,
    failure,
    candidates,
    showProgressDot: connection === 'reconnecting' || progressText !== null,
    interrupted,
    pendingSkill,
    skills,
    selectSkill,
  };
}
