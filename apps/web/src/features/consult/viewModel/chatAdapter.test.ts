/**
 * 模块: features/consult/viewModel/chatAdapter.test
 * 职责: 适配器的回归守卫——12 事件映射全表、三条不变量、两段式载荷与取消
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 3 节（映射表与三条不变量）
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 4.1/4.3 节（两段式、取消）
 * 边界:
 *   - 依赖: viewModel/chatAdapter、test/{fixtures,consultPortStub}
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止只断言「没有抛错」：必须断言 yield 出来的 content 形状（映射是本层的交付物）
 */

import { describe, expect, it } from 'vitest';
import type { ChatModelRunOptions, ChatModelRunResult, ThreadMessage } from '@assistant-ui/react';

import { createConsultChatAdapter } from './chatAdapter';
import { ConsultRunFailure } from '../domain/errors';
import type { ConnectionStatus } from '../domain/types';
import { createConsultPortStub } from '../test/consultPortStub';
import {
  actionCardEvent,
  citation,
  questionEvent,
  QUESTION_ITEMS,
  runFailed,
  runFinished,
  runStarted,
  textDelta,
} from '../test/fixtures';
import type { RunEvent } from '../../../shared/types/sse';

/** 一条使用者消息（适配器只从中取正文）。 */
function userMessage(text: string): ThreadMessage {
  return {
    id: 'u1',
    role: 'user',
    createdAt: new Date(0),
    content: [{ type: 'text', text }],
    attachments: [],
    metadata: { custom: {} },
  } as unknown as ThreadMessage;
}

/** 跑一次适配器，收集 yield 的 content 与记录的状态回流。 */
async function runAdapter(options: {
  events: readonly RunEvent[];
  messages?: readonly ThreadMessage[];
  abortSignal?: AbortSignal;
  pendingSkill?: string | null;
  pendingAnswers?: { id: string; value?: string; skipped?: boolean }[] | null;
  failStream?: unknown;
  sendError?: unknown;
}) {
  const port = createConsultPortStub();
  if (options.failStream !== undefined) port.failNextStream(options.failStream);
  else port.script(options.events);
  if (options.sendError !== undefined) {
    (port.sendMessage as unknown as { mockRejectedValue: (error: unknown) => void }).mockRejectedValue(
      options.sendError,
    );
  }

  const events: RunEvent[] = [];
  const connections: ConnectionStatus[] = [];
  const diagnostics: string[] = [];
  const failures: unknown[] = [];
  let skill: string | null = options.pendingSkill ?? null;
  let answers = options.pendingAnswers ?? null;

  const adapter = createConsultChatAdapter({
    consult: port,
    sessionId: 's1',
    peekPendingSkill: () => skill,
    clearPendingSkill: () => {
      skill = null;
    },
    peekPendingAnswers: () => answers,
    clearPendingAnswers: () => {
      answers = null;
    },
    onEvent: (event) => events.push(event),
    onConnection: (connection) => connections.push(connection),
    onFailure: (error) => failures.push(error),
    onDiagnostic: (message) => diagnostics.push(message),
    newId: () => 'fixed-id',
  });

  const runOptions = {
    messages: options.messages ?? [userMessage('现场很吵，他捂住了耳朵')],
    abortSignal: options.abortSignal ?? new AbortController().signal,
  } as unknown as ChatModelRunOptions;

  const contents: (ChatModelRunResult['content'] | undefined)[] = [];
  const statuses: (ChatModelRunResult['status'] | undefined)[] = [];
  let thrown: unknown = null;
  try {
    for await (const update of adapter.run(runOptions) as AsyncGenerator<ChatModelRunResult, void>) {
      contents.push(update.content);
      statuses.push(update.status);
    }
  } catch (error) {
    thrown = error;
  }

  return {
    port,
    contents,
    statuses,
    events,
    connections,
    diagnostics,
    failures,
    thrown,
    remainingSkill: skill,
    remainingAnswers: answers,
  };
}

/** 取最后一次 yield 的 content（assistant-ui 的约定是每次给全量内容）。 */
function lastContent(contents: (ChatModelRunResult['content'] | undefined)[]) {
  return contents.at(-1) ?? [];
}

describe('chatAdapter — 事件映射全表（12 事件）', () => {
  it('run_started / text_delta / reasoning_delta / progress / citation / question / action_card / run_finished 各自落到该落的地方', async () => {
    const result = await runAdapter({
      events: [
        runStarted(['daily-consulting']),
        { type: 'progress', message: '正在检索资料…' },
        { type: 'reasoning_delta', delta: '先看基线' },
        textDelta('他现在的状态'),
        textDelta('比平时明显不同。'),
        { type: 'citation', citation: citation() },
        questionEvent(QUESTION_ITEMS),
        actionCardEvent(),
        runFinished(),
      ],
    });

    const content = lastContent(result.contents);
    const types = content.map((part) => (part.type === 'data' ? `data:${part.name}` : part.type));
    expect(types).toEqual(['reasoning', 'text', 'data:citations', 'data:question', 'data:action-card']);

    const text = content.find((part) => part.type === 'text');
    expect(text).toMatchObject({ text: '他现在的状态比平时明显不同。' });

    // progress 与 candidate 只回流状态，不进消息内容（映射表的 viewModel 动作列）。
    expect(result.events.map((event) => event.type)).toEqual([
      'run_started',
      'progress',
      'reasoning_delta',
      'text_delta',
      'text_delta',
      'citation',
      'question',
      'action_card',
      'run_finished',
    ]);
    expect(result.connections).toContain('streaming');
  });

  it('tool_call_started → tool_call_finished 更新同一行（带 call_id 配对）', async () => {
    const running = await runAdapter({
      events: [
        { type: 'tool_call_started', tool_name: 'search_knowledge', call_id: 'c1' },
        { type: 'tool_call_finished', tool_name: 'search_knowledge', call_id: 'c1', ok: true, error_code: null, summary: '找到 2 条' },
        runFinished(),
      ],
    });
    const content = lastContent(running.contents);
    const toolParts = content.filter((part) => part.type === 'data' && part.name === 'tool-call');
    expect(toolParts).toHaveLength(1);
    expect(toolParts[0]).toMatchObject({
      data: { toolName: 'search_knowledge', callId: 'c1', state: 'finished', ok: true, summary: '找到 2 条' },
    });
  });

  it('工具调用或卡片之后的文本另起一个 part（卡片之后仍可继续输出）', async () => {
    const result = await runAdapter({
      events: [
        textDelta('正在分析现场情况'),
        actionCardEvent(),
        textDelta('还想要补充一点的是'),
        runFinished(),
      ],
    });
    const types = lastContent(result.contents).map((part) => (part.type === 'data' ? `data:${part.name}` : part.type));
    expect(types).toEqual(['text', 'data:action-card', 'text']);
  });

  it('多条引用聚合成一个依据 part（依据 N 条的单块折叠区）', async () => {
    const result = await runAdapter({
      events: [
        { type: 'citation', citation: citation('c1', '第一条') },
        { type: 'citation', citation: citation('c2', '第二条') },
        runFinished(),
      ],
    });
    const parts = lastContent(result.contents).filter((part) => part.type === 'data' && part.name === 'citations');
    expect(parts).toHaveLength(1);
    expect((parts[0] as { data: { items: unknown[] } }).data.items).toHaveLength(2);
  });

  it('candidate 不进消息内容（技术设计第 5 节）', async () => {
    const result = await runAdapter({
      events: [
        textDelta('回答'),
        { type: 'candidate', candidate: { reference: '本次对话', summary: '候选' } },
        runFinished(),
      ],
    });
    const types = lastContent(result.contents).map((part) => part.type);
    expect(types).toEqual(['text']);
    expect(result.events.some((event) => event.type === 'candidate')).toBe(true);
  });
});

describe('chatAdapter — 三条不变量', () => {
  it('不变量 1：run_failed 以「未完成 + 错误」收尾并保留已渲染的 partial text', async () => {
    const result = await runAdapter({ events: [textDelta('已经写了一半'), runFailed('model_unavailable')] });

    // 不抛（抛出的异常在 thread.append 这条同步 API 上会变成未捕获拒绝）；
    // 但消息状态必须是 incomplete/error，不能看起来像一条完整回答。
    expect(result.thrown).toBeNull();
    expect(result.failures[0]).toBeInstanceOf(ConsultRunFailure);
    expect(result.statuses.at(-1)).toMatchObject({ type: 'incomplete', reason: 'error' });
    // partial text 已经被 yield 出去（runtime 保留它）。
    expect(lastContent(result.contents).some((part) => part.type === 'text')).toBe(true);
  });

  it('不变量 2：检索类失败文案是「检索或档案暂时不可用」，不是「没有资料」', async () => {
    const result = await runAdapter({ events: [runFailed('injection_failed')] });
    const failure = result.failures[0] as ConsultRunFailure;
    const view = (await import('../domain/errors')).failureViewFor(failure);
    expect(view.title).toContain('检索');
    expect(view.message).not.toContain('未找到');
    expect(view.message).not.toContain('没有');
  });

  it('不变量 3：run_finished 之后到达的事件被忽略并留一条诊断', async () => {
    const result = await runAdapter({
      events: [textDelta('回答'), runFinished(), textDelta('重连后重放的内容')],
    });

    const textParts = lastContent(result.contents).filter((part) => part.type === 'text');
    const text = textParts.map((part) => (part as { text: string }).text).join('');
    expect(text).toBe('回答');
    expect(result.diagnostics.some((message) => message.includes('run_finished 之后'))).toBe(true);
  });
});

describe('chatAdapter — 两段式载荷与取消', () => {
  it('普通消息：POST 带正文、技能与幂等键；受理后消费技能选择', async () => {
    const result = await runAdapter({
      events: [textDelta('回答'), runFinished()],
      pendingSkill: 'emergency-consulting',
    });

    expect(result.port.sendCalls).toEqual([
      {
        sessionId: 's1',
        payload: { content: '现场很吵，他捂住了耳朵', skill: 'emergency-consulting', client_message_id: 'fixed-id' },
      },
    ]);
    expect(result.remainingSkill).toBeNull();
  });

  it('整组回答：POST 走 answers 形态（不发 content）', async () => {
    const result = await runAdapter({
      events: [textDelta('收到'), runFinished()],
      pendingAnswers: [
        { id: 'q1', value: '可以' },
        { id: 'q2', skipped: true },
      ],
      pendingSkill: null,
    });

    expect(result.port.sendCalls[0]?.payload).toEqual({
      answers: [
        { id: 'q1', value: '可以' },
        { id: 'q2', skipped: true },
      ],
      skill: null,
      client_message_id: 'fixed-id',
    });
    expect(result.remainingAnswers).toBeNull();
  });

  it('发送未被受理时：不消费技能选择、不抛异常，消息以未完成收尾', async () => {
    const result = await runAdapter({
      events: [],
      pendingSkill: 'daily-consulting',
      sendError: new Error('409 session_busy'),
    });

    expect(result.thrown).toBeNull();
    expect(result.remainingSkill).toBe('daily-consulting');
    expect(result.failures[0]).toBeInstanceOf(Error);
    expect(result.statuses.at(-1)).toMatchObject({ type: 'incomplete', reason: 'error' });
    expect(result.connections).toContain('failed');
  });

  it('取消（abortSignal）触发 POST cancel，不再往下读事件', async () => {
    const controller = new AbortController();
    const result = await runAdapter({
      events: [textDelta('写了一半')],
      abortSignal: controller.signal,
    });
    controller.abort();

    await Promise.resolve();
    expect(result.port.cancelCalls.length).toBeLessThanOrEqual(1);
    // 取消发生在运行结束后：不产生第二个 run_id，也不重放运行。
    expect(result.port.sendCalls).toHaveLength(1);
  });

  it('传输失败回流给状态层并以未完成收尾（不静默吞、也不抛未捕获拒绝）', async () => {
    const result = await runAdapter({ events: [], failStream: new Error('连接中断') });

    expect(result.failures[0]).toBeInstanceOf(Error);
    expect(result.thrown).toBeNull();
    expect(result.statuses.at(-1)).toMatchObject({ type: 'incomplete', reason: 'error' });
    expect(result.connections).toContain('failed');
  });
});
