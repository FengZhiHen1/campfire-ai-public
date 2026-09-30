/**
 * 模块: features/consult/viewModel/partAccumulator
 * 职责: 把 SSE 事件流折成 assistant-ui 的 assistant content part 序列（纯累积，无副作用）
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 3 节映射表、第 5 节（citation 跟消息走）、第 6.2/6.3 节
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 7 节（消息 part 形状）
 *   - apps/web/src/app/assistantUi.smoke.test.tsx: MUST — 实测：adapter yield 的 part 用 DataMessagePart 形状
 * 边界:
 *   - 依赖: domain/parts（注册名与视图类型）
 *   - 被依赖: viewModel/chatAdapter
 * 禁止行为:
 *   - 禁止在此发请求或读 store（它只做形状累积，事件回流归适配器）
 *   - 禁止把 reasoning 文本混进正文 part（思考段必须是独立的 reasoning part）
 *   - 禁止解析正文猜结构（卡片与提问只认事件载荷）
 *
 * 为什么单独成模块：事件→part 的映射是这一层最容易出错的部分（交错、聚合、状态位），
 * 独立出来后可以按事件序列直接测，而不必每次都跑整个适配器。
 */

import type { CitationRecord } from '../../../shared/types/sse';
import type { ActionCardEvent, QuestionEvent, ToolCallFinishedEvent, ToolCallStartedEvent } from '../../../shared/types/sse';
import { PART_NAME, type CitationsView, type ToolCallView } from '../domain/parts';

/** 消息 content 的视图 part（assistant-ui 的 assistant part 子集）。 */
export type ViewPart =
  | { type: 'text'; text: string }
  | { type: 'reasoning'; text: string }
  | { type: 'data'; name: string; data: unknown };

/** part 累积器：每一步之后用 snapshot() 取当前全量内容（assistant-ui 的 yield 约定）。 */
export interface PartAccumulator {
  addText(delta: string): void;
  addReasoning(delta: string): void;
  startToolCall(event: ToolCallStartedEvent): void;
  finishToolCall(event: ToolCallFinishedEvent): void;
  addCitation(citation: CitationRecord): void;
  addQuestion(event: QuestionEvent): void;
  addActionCard(event: ActionCardEvent): void;
  /** 当前全量 part 的快照（浅拷贝数组；part 对象本身不可变）。 */
  snapshot(): ViewPart[];
}

/** 取工具调用 part 的下标（按 call_id 且仍在跑的那条）。 */
function runningToolIndex(parts: readonly ViewPart[], callId: string): number {
  return parts.findIndex(
    (part) =>
      part.type === 'data' &&
      part.name === PART_NAME.toolCall &&
      (part.data as ToolCallView).callId === callId &&
      (part.data as ToolCallView).state === 'running',
  );
}

/** 定位依据区 part：返回下标与已有条目。 */
function locateCitations(parts: readonly ViewPart[]): { index: number; items: CitationRecord[] } {
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const part = parts[index];
    if (part !== undefined && part.type === 'data' && part.name === PART_NAME.citations) {
      return { index, items: (part.data as CitationsView).items };
    }
  }
  return { index: -1, items: [] };
}

/**
 * 建一个 part 累积器。
 *
 * 前置: 无
 * 后置: 返回可逐事件写入的累积器；文本/思考按「连续段」合并，卡片与工具会打断文本段
 * 异常: 无
 */
export function createPartAccumulator(): PartAccumulator {
  const parts: ViewPart[] = [];
  let textIndex: number | null = null;
  let reasoningIndex: number | null = null;

  /** 卡片/工具/引用到达：后续文本另起一段（技术设计 6.2 节「卡片之后还可继续输出」）。 */
  const breakTextRun = (): void => {
    textIndex = null;
    reasoningIndex = null;
  };

  return {
    addText(delta) {
      const index = textIndex;
      const previous = index === null ? undefined : parts[index];
      if (index !== null && previous !== undefined && previous.type === 'text') {
        parts[index] = { type: 'text', text: `${previous.text}${delta}` };
        return;
      }
      parts.push({ type: 'text', text: delta });
      textIndex = parts.length - 1;
    },

    addReasoning(delta) {
      // 每次思考段是独立的 reasoning part（技术设计 6.3 节：与工具调用交替多轮）。
      const index = reasoningIndex;
      const previous = index === null ? undefined : parts[index];
      if (index !== null && previous !== undefined && previous.type === 'reasoning') {
        parts[index] = { type: 'reasoning', text: `${previous.text}${delta}` };
        return;
      }
      parts.push({ type: 'reasoning', text: delta });
      reasoningIndex = parts.length - 1;
    },

    startToolCall(event) {
      const running: ToolCallView = {
        toolName: event.tool_name,
        callId: event.call_id,
        state: 'running',
        ok: null,
        summary: null,
      };
      parts.push({ type: 'data', name: PART_NAME.toolCall, data: running });
      breakTextRun();
    },

    finishToolCall(event) {
      const finished: ToolCallView = {
        toolName: event.tool_name,
        callId: event.call_id,
        state: 'finished',
        ok: event.ok,
        summary: event.summary,
      };
      const index = runningToolIndex(parts, event.call_id);
      if (index === -1) parts.push({ type: 'data', name: PART_NAME.toolCall, data: finished });
      else parts[index] = { type: 'data', name: PART_NAME.toolCall, data: finished };
      breakTextRun();
    },

    addCitation(citation) {
      // 聚合成一块并始终挂在消息尾：契约的 .citation-block 是「依据 N 条」的单块折叠区，
      // 逐条 push 会得到 N 个折叠头，且位置会停在第一次引用到达处。
      const located = locateCitations(parts);
      if (located.index !== -1) parts.splice(located.index, 1);
      parts.push({
        type: 'data',
        name: PART_NAME.citations,
        data: { items: [...located.items, citation] } satisfies CitationsView,
      });
      breakTextRun();
    },

    addQuestion(event) {
      parts.push({
        type: 'data',
        name: PART_NAME.question,
        data: { batch_id: event.batch_id, items: event.items },
      });
      breakTextRun();
    },

    addActionCard(event) {
      parts.push({
        type: 'data',
        name: PART_NAME.actionCard,
        data: {
          card_id: event.card_id,
          title: event.title,
          sections: event.sections,
          states: event.states,
          annotations: event.annotations,
        },
      });
      breakTextRun();
    },

    snapshot: () => [...parts],
  };
}
