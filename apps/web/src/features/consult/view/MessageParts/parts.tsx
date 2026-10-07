/**
 * 模块: features/consult/view/MessageParts/parts
 * 职责: 消息 part 的渲染注册表与跨 part 上下文——data-* 注册名到组件的唯一映射点
 * 数据来源:
 *   - apps/web/src/app/assistantUi.smoke.test.tsx: MUST — 实测结论：`components.data.by_name` 的键
 *     是消息 part 类型去掉 `data-` 前缀后的名字（库内执行 type.substring(5)）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 4.2 节（组件清单）、第 5、6 节
 *   - docs/design/pages/对话页.md: MUST — 契约修订 1～8（各渲染器的规格）
 * 边界:
 *   - 依赖: 各 part 组件、viewModel 的 useQuestionBatch、domain/parts
 *   - 被依赖: view 的对话工作面
 * 禁止行为:
 *   - 禁止在注册表里写业务判定（判定归 domain；这里只做「part → 组件」的接线）
 *   - 禁止把 reasoning 文本接进正文渲染器（只挂在 ReasoningDisclosure 上）
 *   - 禁止 part 渲染器直接订阅 runStore：运行态由对话工作面经上下文下发（否则渲染器
 *     无法用 fixture 驱动，也与「接线点唯一」冲突）
 */

import { createContext, useContext, type ReactNode } from 'react';

import type { ActionCardEvent, CitationRecord, QuestionItem } from '../../../../shared/types/sse';
import { PART_NAME, type ToolCallView } from '../../domain/parts';
import { useQuestionBatch } from '../../viewModel/useQuestionBatch';
import { ActionCard } from './ActionCard';
import { CitationPart } from './CitationPart';
import { QuestionCard } from './QuestionCard';
import { ReasoningDisclosure } from './ReasoningDisclosure';
import { ToolIndicator } from './ToolIndicator';

/**
 * 对话消息流里跨 part 需要的信息（由对话工作面提供）。
 *
 * 为什么经上下文而不是字面 props：part 渲染器由库的 `MessagePrimitive.Parts` 在库自己
 * 管理的树里实例化，没有可传 props 的挂载点；上下文是在该树里下发数据的唯一通道。
 * 取值仍然是「工作面持有、渲染器只读」，渲染器不订阅任何全局 store。
 */
export interface ConsultThreadContextValue {
  /** 提问卡整组提交后追加使用者消息。 */
  submitAnswers(displayText: string): void;
  /** 当前最新的行动卡 id；用于把旧卡标为失效（同会话内更晚的卡为准）。 */
  newestActionCardId: string | null;
  /** 对话是否仍在流式输出（思考行的行内文案据此切换）。 */
  reasoningStreaming: boolean;
  /** 本轮是否启用了应急技能（思考行据此收为一行）。 */
  reasoningEmergency: boolean;
}

const ConsultThreadContext = createContext<ConsultThreadContextValue | null>(null);

/** 对话消息流的上下文 provider。 */
export function ConsultThreadProvider({
  value,
  children,
}: {
  value: ConsultThreadContextValue;
  children: ReactNode;
}) {
  return <ConsultThreadContext.Provider value={value}>{children}</ConsultThreadContext.Provider>;
}

/**
 * 取对话消息流的上下文。
 *
 * 前置: 组件树里存在 ConsultThreadProvider（对话工作面提供）
 * 异常: 缺失时抛出——默默给一份默认值会让「提交回答没有发送」这类缺陷无声无息
 *
 * @throws Error 组件树里没有 ConsultThreadProvider
 */
export function useConsultThread(): ConsultThreadContextValue {
  const value = useContext(ConsultThreadContext);
  if (value === null) {
    throw new Error('消息 part 必须在 ConsultThreadProvider 内渲染');
  }
  return value;
}

/** 正文渲染：空行分段，与 .msg-doc 的段间距约定一致。 */
function TextPart({ text }: { text: string }) {
  const paragraphs = text.split(/\n{2,}/).filter((paragraph) => paragraph.trim() !== '');
  if (paragraphs.length === 0) return null;
  return (
    <>
      {paragraphs.map((paragraph) => (
        <p key={paragraph}>{paragraph}</p>
      ))}
    </>
  );
}

/** 思考段渲染：文案与呈现纪律取自由对话工作面下发的运行态（应急收为一行）。 */
function ReasoningPart({ text }: { text: string }) {
  const { reasoningStreaming, reasoningEmergency } = useConsultThread();
  return <ReasoningDisclosure text={text} streaming={reasoningStreaming} emergency={reasoningEmergency} />;
}

/** 依据区渲染（聚合后的多条引用）。 */
function CitationsPart({ data }: { data: { items: CitationRecord[] } }) {
  return <CitationPart items={data.items} />;
}

/** 工具调用行渲染。 */
function ToolCallPart({ data }: { data: ToolCallView }) {
  return <ToolIndicator view={data} />;
}

/** 行动卡渲染：失效判定来自上下文里的最新卡 id。 */
function ActionCardPart({ data }: { data: ActionCardEvent }) {
  const { newestActionCardId } = useConsultThread();
  const expired = newestActionCardId !== null && newestActionCardId !== data.card_id;
  return <ActionCard data={data} expired={expired} />;
}

/** 运行中的提问卡（可作答）。 */
function LiveQuestionPart({ data }: { data: { batch_id: string; items: readonly QuestionItem[] } }) {
  const { submitAnswers } = useConsultThread();
  const controller = useQuestionBatch({
    batchId: data.batch_id,
    items: data.items,
    mode: 'live',
    onSubmit: submitAnswers,
  });
  return <QuestionCard controller={controller} />;
}

/**
 * 历史水合的提问记录。
 *
 * ★ `answered` 是**服务端**的三态判定，这里只搬运、不推断：
 * - `false` ⇒ 控制器折算成可作答（刷新后仍能补答，这正是本包修的那条）；
 * - `true`  ⇒ 只读记录；
 * - `null`/缺省 ⇒ 只读记录（fail-closed）。
 *
 * **刻意不把它设为「当前活跃批次」**（与运行中刚发出的提问不同）：`activeBatchId`
 * 非空会让工作面**整体收起输入区**（`ChatWorkspace` 的 `answering` 闸门）。一条**历史**里
 * 未作答的提问可能在很多轮之前，用它全局堵住输入区会把「可以补答」变成「必须先补答」——
 * 那是本包没被要求、也不可逆的行为改动（一次刷新后使用者只能答那一组题）。
 * 补答仍然可用：卡片自己带提交按钮，提交走与运行中同一条 `submitAnswers`。
 */
function QuestionRecordPart({
  data,
}: {
  data: { batch_id: string; items: readonly QuestionItem[]; answered?: boolean | null };
}) {
  const { submitAnswers } = useConsultThread();
  const controller = useQuestionBatch({
    batchId: data.batch_id,
    items: data.items,
    mode: 'record',
    answered: data.answered,
    onSubmit: submitAnswers,
  });
  return <QuestionCard controller={controller} />;
}

/**
 * 消息 part 渲染配置。
 *
 * 为什么是模块级常量：每次渲染新建组件类型会让 React 卸载重建整棵子树，
 * 消息流里的折叠状态（依据区、思考行）会随之丢失。
 */
export const CONSULT_MESSAGE_COMPONENTS = {
  Text: TextPart,
  Reasoning: ReasoningPart,
  data: {
    by_name: {
      [PART_NAME.citations]: CitationsPart,
      [PART_NAME.toolCall]: ToolCallPart,
      [PART_NAME.question]: LiveQuestionPart,
      [PART_NAME.questionRecord]: QuestionRecordPart,
      [PART_NAME.actionCard]: ActionCardPart,
    },
  },
} as const;

/** 供测试与工作面断言注册表覆盖了契约的五个视图 part。 */
export const CONSULT_PART_NAMES: readonly string[] = [
  PART_NAME.citations,
  PART_NAME.toolCall,
  PART_NAME.question,
  PART_NAME.questionRecord,
  PART_NAME.actionCard,
];
