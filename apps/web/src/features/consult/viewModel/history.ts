/**
 * 模块: features/consult/viewModel/history
 * 职责: 历史水合——后端消息（六种 part）→ assistant-ui 的 ThreadMessageLike
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 4.4 节（刷新后恢复、失败不显示空对话）
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 3.3 节（水合响应形状）、第 7 节（part 表）
 * 边界:
 *   - 依赖: shared/types/{consult,sse}、features/consult/domain/parts
 *   - 被依赖: viewModel 的 useConsultSession 与 view 的对话页
 * 禁止行为:
 *   - 禁止在水合失败时返回空数组冒充「没有消息」（技术设计第 4.4 节）
 *   - 禁止静默丢弃契约外的 part（丢弃必须进 diagnostics，由调用方处置）
 */

import type { ThreadAssistantMessagePart, ThreadMessageLike, ThreadUserMessagePart } from '@assistant-ui/react';

import type { HydratedMessage, ListMessagesResponse } from '../../../shared/types/consult';
import type { CitationRecord, MessagePart } from '../../../shared/types/sse';
import { PART_NAME, type CitationsView } from '../domain/parts';

/** 水合结果：消息数组 + 被丢弃 part 的诊断（不静默）。 */
export interface HydratedHistory {
  messages: ThreadMessageLike[];
  diagnostics: string[];
}

/** 一条 part 的转换结果；citation 单独一类（要在消息尾聚合成一块）。 */
type PartConversion =
  | { kind: 'part'; part: ThreadAssistantMessagePart }
  | { kind: 'citation'; citation: CitationRecord }
  | { kind: 'dropped'; reason: string };

/** 水合过程中的累积器。 */
interface Accumulator {
  parts: ThreadAssistantMessagePart[];
  citations: CitationRecord[];
  diagnostics: string[];
}

/** 把一条线格式 part 转成视图 part。 */
function convertAssistantPart(part: MessagePart, diagnostics: string[]): PartConversion {
  switch (part.type) {
    case 'text':
      return { kind: 'part', part: { type: 'text', text: part.text } };
    case 'reasoning':
      // assistant-ui 的 reasoning part 字段是 text；线格式的字段是 delta（契约第 7 节）。
      return { kind: 'part', part: { type: 'reasoning', text: part.delta } };
    case 'tool_call':
      return {
        kind: 'part',
        part: {
          type: 'data',
          name: PART_NAME.toolCall,
          data: {
            toolName: part.tool_name,
            // 契约第 7 节的 tool_call part 没有 call_id（那是 started/finished 事件的字段），
            // 历史里的一次调用就是一条已完成记录，不编造标识。
            callId: null,
            state: 'finished',
            ok: part.ok,
            summary: part.summary,
          },
        },
      };
    case 'citation':
      return { kind: 'citation', citation: part.citation };
    case 'question':
      // 流出侧（事件）形状：`partAccumulator.addQuestion` 已经把它映射成可作答的活卡，
      // 因此这条分支不该在水合响应里出现。真出现了也要**可作答**吗？——不。
      // 水合的提问一律由服务端带 `answered` 判定（`question-record`）；一条没有判定的
      // `question` 落在历史里意味着服务端产出了契约外的形状。按 fail-closed 处置：
      // 当只读记录，并留诊断（不许前端猜「它没被作答」从而让使用者重复作答）。
      diagnostics.push('水合响应里出现了流出侧的 question part（历史应为 question-record），按只读记录处置');
      return {
        kind: 'part',
        part: {
          type: 'data',
          name: PART_NAME.questionRecord,
          data: { batch_id: part.batch_id, items: part.items, answered: null },
        },
      };
    case 'question-record':
      // ★ 历史提问的**服务端判定**：`answered` 三态由后端给出，这里只做搬运。
      // 前端不得自行推断（契约第 7 节与硬边界：不许让前端猜）。
      return {
        kind: 'part',
        part: {
          type: 'data',
          name: PART_NAME.questionRecord,
          data: { batch_id: part.batch_id, items: part.items, answered: part.answered },
        },
      };
    case 'action_card':
      return {
        kind: 'part',
        part: {
          type: 'data',
          name: PART_NAME.actionCard,
          data: {
            card_id: part.card_id,
            title: part.title,
            sections: part.sections,
            states: part.states,
            annotations: part.annotations,
          },
        },
      };
    default: {
      const unknown: { type: string } = part;
      const reason = `未知的消息 part 类型：${unknown.type}`;
      diagnostics.push(reason);
      return { kind: 'dropped', reason };
    }
  }
}

/** 助手消息：逐 part 转换，依据区在末尾聚合成一块。 */
function toAssistantMessage(message: HydratedMessage, accumulator: Accumulator): ThreadMessageLike {
  for (const part of message.parts) {
    const converted = convertAssistantPart(part, accumulator.diagnostics);
    if (converted.kind === 'citation') {
      accumulator.citations.push(converted.citation);
      continue;
    }
    if (converted.kind === 'part') accumulator.parts.push(converted.part);
  }

  if (accumulator.citations.length > 0) {
    // 依据区挂消息尾（对话页设计契约修订 5：消息尾的「依据 N 条」折叠区）。
    accumulator.parts.push({
      type: 'data',
      name: PART_NAME.citations,
      data: { items: accumulator.citations } satisfies CitationsView,
    });
  }

  return {
    id: message.id,
    role: 'assistant',
    content: accumulator.parts,
  };
}

/** 使用者消息：契约里使用者 part 只有 text（第 7 节），其余类型显式丢弃并留诊断。 */
function toUserMessage(message: HydratedMessage, diagnostics: string[]): ThreadMessageLike {
  const content: ThreadUserMessagePart[] = [];
  for (const part of message.parts) {
    if (part.type === 'text') {
      content.push({ type: 'text', text: part.text });
      continue;
    }
    diagnostics.push(`使用者消息里的 ${part.type} part 不在契约第 7 节的使用者形状内，已忽略`);
  }
  return { id: message.id, role: 'user', content };
}

/**
 * 把水合响应转成 runtime 的初始消息。
 *
 * 前置: response.messages 按真源顺序排列（契约第 3.3 节）
 * 后置: 返回同序的 ThreadMessageLike 数组与丢弃诊断；空数组只可能来自「服务端确实没有消息」
 * 异常: 不抛出——形状问题以 diagnostics 表达，网络/状态码失败由调用方（useConsultSession）处置
 */
export function hydrateHistory(response: ListMessagesResponse): HydratedHistory {
  const diagnostics: string[] = [];
  const messages: ThreadMessageLike[] = [];

  for (const message of response.messages) {
    if (message.role === 'user') {
      messages.push(toUserMessage(message, diagnostics));
      continue;
    }
    const accumulator: Accumulator = { parts: [], citations: [], diagnostics };
    const converted = toAssistantMessage(message, accumulator);
    if (accumulator.parts.length === 0) {
      // 没有任何可渲染内容的助手消息不产生空壳，但丢的是哪条要留痕。
      diagnostics.push(`助手消息 ${message.id} 没有可渲染的内容`);
      continue;
    }
    messages.push(converted);
  }

  return { messages, diagnostics };
}
