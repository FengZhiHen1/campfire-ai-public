/**
 * 模块: features/consult/viewModel/history.test
 * 职责: 历史水合的回归守卫——六种 part 的映射、依据聚合、未知 part 留痕
 * 数据来源:
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 3.3、7 节（水合响应与 part 表）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 4.4 节（水合失败不显示空对话）
 * 边界:
 *   - 依赖: viewModel/history、test/fixtures
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言未知 part 被静默丢弃（必须进 diagnostics）
 */

import { describe, expect, it } from 'vitest';

import { hydrateHistory } from './history';
import type { MessagePart } from '../../../shared/types/sse';
import {
  actionCardEvent,
  citation,
  hydratedAssistant,
  hydratedUser,
  historyResponse,
  QUESTION_ITEMS,
} from '../test/fixtures';

describe('hydrateHistory — 六种 part 的映射', () => {
  it('text / reasoning / tool_call / citation / question / action_card 全部映射到视图 part', () => {
    const actionCard = actionCardEvent();
    const parts: MessagePart[] = [
      { type: 'text', text: '历史回答' },
      { type: 'reasoning', delta: '当时的思考' },
      { type: 'tool_call', tool_name: 'search_knowledge', ok: true, summary: '找到 2 条' },
      { type: 'citation', citation: citation() },
      { type: 'question', batch_id: 'b1', items: [...QUESTION_ITEMS] },
      {
        type: 'action_card',
        card_id: actionCard.card_id,
        title: actionCard.title,
        sections: [...actionCard.sections],
        states: [...actionCard.states],
        annotations: [...actionCard.annotations],
      },
    ];

    const hydrated = hydrateHistory(historyResponse([hydratedAssistant('m1', parts)]));

    expect(hydrated.diagnostics).toEqual([]);
    expect(hydrated.messages).toHaveLength(1);
    const content = hydrated.messages[0]?.content;
    if (!Array.isArray(content)) throw new Error('助手消息的 content 应是 part 数组');

    expect(content.map((part) => (part.type === 'data' ? `data:${part.name}` : part.type))).toEqual([
      'text',
      'reasoning',
      'data:tool-call',
      'data:question-record',
      'data:action-card',
      'data:citations',
    ]);
    expect(content[1]).toMatchObject({ type: 'reasoning', text: '当时的思考' });
    // 依据区在消息尾聚合（历史里逐条的 citation 合成一块「依据 N 条」）。
    expect(content.at(-1)).toMatchObject({ type: 'data', name: 'citations' });
  });

  it('使用者消息只保留文本；契约外的 part 进诊断', () => {
    const hydrated = hydrateHistory(
      historyResponse([
        hydratedUser('u1', '历史提问'),
        hydratedAssistant('m1', [{ type: '不认识的 part', payload: 1 } as unknown as MessagePart]),
      ]),
    );

    expect(hydrated.messages.map((message) => message.role)).toEqual(['user']);
    expect(hydrated.diagnostics).toHaveLength(2);
    expect(hydrated.diagnostics.join('\n')).toContain('不认识的 part');
    expect(hydrated.diagnostics.join('\n')).toContain('没有可渲染的内容');
  });

  it('空响应返回空数组（服务端确实没有消息，不是失败）', () => {
    const hydrated = hydrateHistory(historyResponse([]));
    expect(hydrated.messages).toEqual([]);
    expect(hydrated.diagnostics).toEqual([]);
  });

  it('多条引用在消息尾合并为一块（而不是每条一个折叠头）', () => {
    const hydrated = hydrateHistory(
      historyResponse([
        hydratedAssistant('m1', [
          { type: 'citation', citation: citation('c1', '第一条') },
          { type: 'citation', citation: citation('c2', '第二条') },
        ]),
      ]),
    );
    const content = hydrated.messages[0]?.content;
    if (!Array.isArray(content)) throw new Error('应是 part 数组');
    expect(content).toHaveLength(1);
    expect(content[0]).toMatchObject({ type: 'data', name: 'citations' });
  });
});
