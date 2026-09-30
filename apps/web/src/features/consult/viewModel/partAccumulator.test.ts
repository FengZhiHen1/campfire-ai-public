/**
 * 模块: features/consult/viewModel/partAccumulator.test
 * 职责: 事件→part 累积的回归守卫——连续段合并、交错打断、聚合与状态位
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 3 节映射、第 5 节（依据区）、第 6.2/6.3 节（交错与多段）
 * 边界:
 *   - 依赖: viewModel/partAccumulator、test/fixtures
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止把 reasoning 断言成正文 part（思考必须是独立的 reasoning part）
 */

import { describe, expect, it } from 'vitest';

import { createPartAccumulator } from './partAccumulator';
import { actionCardEvent, citation, QUESTION_ITEMS } from '../test/fixtures';

/** 取 part 的名字（data part 用注册名）。 */
function names(parts: readonly unknown[]): string[] {
  return parts.map((part) => {
    const typed = part as { type: string; name?: string };
    return typed.type === 'data' ? `data:${String(typed.name)}` : typed.type;
  });
}

describe('createPartAccumulator', () => {
  it('连续文本合并成一个 part，思考与正文分开', () => {
    const accumulator = createPartAccumulator();
    accumulator.addText('他现在的状态');
    accumulator.addText('比平时明显不同。');
    accumulator.addReasoning('先看基线');
    accumulator.addReasoning('再看环境');

    const parts = accumulator.snapshot();
    expect(names(parts)).toEqual(['text', 'reasoning']);
    expect(parts[0]).toMatchObject({ type: 'text', text: '他现在的状态比平时明显不同。' });
    expect(parts[1]).toMatchObject({ type: 'reasoning', text: '先看基线再看环境' });
  });

  it('卡片/工具/引用打断文本段：之后的文本另起一个 part', () => {
    const accumulator = createPartAccumulator();
    accumulator.addText('正在分析现场情况');
    accumulator.addActionCard(actionCardEvent());
    accumulator.addText('还想要补充一点的是');

    expect(names(accumulator.snapshot())).toEqual(['text', 'data:action-card', 'text']);
  });

  it('工具调用按 call_id 配对更新同一行；没有 started 时直接追加一条已完成', () => {
    const accumulator = createPartAccumulator();
    accumulator.startToolCall({ type: 'tool_call_started', tool_name: 'search_knowledge', call_id: 'c1' });
    accumulator.finishToolCall({
      type: 'tool_call_finished',
      tool_name: 'search_knowledge',
      call_id: 'c1',
      ok: true,
      error_code: null,
      summary: '找到 2 条',
    });
    const parts = accumulator.snapshot();
    expect(parts).toHaveLength(1);
    expect(parts[0]).toMatchObject({
      data: { callId: 'c1', state: 'finished', ok: true, summary: '找到 2 条' },
    });

    accumulator.finishToolCall({
      type: 'tool_call_finished',
      tool_name: 'search_cases',
      call_id: 'c2',
      ok: false,
      error_code: 'tool_failed',
      summary: '失败',
    });
    expect(names(accumulator.snapshot())).toEqual(['data:tool-call', 'data:tool-call']);
  });

  it('多条引用聚合成一块并始终停在消息尾', () => {
    const accumulator = createPartAccumulator();
    accumulator.addCitation(citation('c1', '第一条'));
    accumulator.addText('依据之后还有正文');
    accumulator.addCitation(citation('c2', '第二条'));

    const parts = accumulator.snapshot();
    // 依据区在末尾、只有一块、含两条。
    expect(names(parts)).toEqual(['text', 'data:citations']);
    const citations = parts.at(-1) as { data: { items: unknown[] } };
    expect(citations.data.items).toHaveLength(2);
  });

  it('提问与行动卡各追加一个 part，载荷原样透传', () => {
    const accumulator = createPartAccumulator();
    accumulator.addQuestion({ type: 'question', batch_id: 'b1', items: [...QUESTION_ITEMS] });
    accumulator.addActionCard(actionCardEvent());

    const parts = accumulator.snapshot();
    expect(names(parts)).toEqual(['data:question', 'data:action-card']);
    expect((parts[0] as { data: { batch_id: string } }).data.batch_id).toBe('b1');
    expect((parts[1] as { data: { card_id: string } }).data.card_id).toBe('card-1');
  });

  it('snapshot 是数组浅拷贝：外部拿到的快照不会被后续写入改变', () => {
    const accumulator = createPartAccumulator();
    accumulator.addText('第一段');
    const first = accumulator.snapshot();
    accumulator.addText('第二段');
    expect(first).toHaveLength(1);
    expect(accumulator.snapshot()).toHaveLength(1);
    expect((accumulator.snapshot()[0] as { text: string }).text).toBe('第一段第二段');
  });
});
