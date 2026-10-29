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

import { describe, expect, it, vi } from 'vitest';
import type { ChatModelRunOptions, ChatModelRunResult, ThreadMessage } from '@assistant-ui/react';

import { createConsultChatAdapter } from './chatAdapter';
import { ConsultError, ConsultRunFailure } from '../domain/errors';
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
  pendingSubmission?: { batchId: string; answers: { id: string; value?: string; skipped?: boolean }[] } | null;
  failStream?: unknown;
  sendError?: unknown;
  /** 已存在的待认领运行（应急入口交接）；null = 没有交接。 */
  attachedRunId?: string | null;
  /** 触发点声明的认领意图（startRun 路径置位）。 */
  attachIntent?: boolean;
  /**
   * 收到第一段更新后就把 abortSignal 置为已中止（模拟点「停止」）。
   *
   * 为什么要它：取消的判据是「流还在跑的时候中止」，而普通脚本是一次性消费完的——
   * 在生成器跑完之后再 abort 观察不到任何东西（旧用例因此只能断言 `<= 1`，恒真）。
   */
  abortAfterFirstChunk?: boolean;
  /** 注入已准备好的端口替身（例如要先 `holdStream`）；提供时不再脚本化 `events`。 */
  port?: ReturnType<typeof createConsultPortStub>;
}) {
  const port = options.port ?? createConsultPortStub();
  if (options.port === undefined) {
    if (options.failStream !== undefined) port.failNextStream(options.failStream);
    else port.script(options.events);
  }
  if (options.sendError !== undefined) {
    (port.sendMessage as unknown as { mockRejectedValue: (error: unknown) => void }).mockRejectedValue(
      options.sendError,
    );
  }

  const events: RunEvent[] = [];
  const connections: ConnectionStatus[] = [];
  const diagnostics: string[] = [];
  const failures: unknown[] = [];
  const resyncs: string[] = [];
  let skill: string | null = options.pendingSkill ?? null;
  let submission = options.pendingSubmission ?? null;
  let attached = options.attachedRunId ?? null;
  let attachIntent = options.attachIntent ?? false;

  const adapter = createConsultChatAdapter({
    consult: port,
    sessionId: 's1',
    peekPendingSkill: () => skill,
    clearPendingSkill: () => {
      skill = null;
    },
    peekPendingSubmission: () => submission,
    clearPendingSubmission: () => {
      submission = null;
    },
    onEvent: (event) => events.push(event),
    onConnection: (connection) => connections.push(connection),
    onFailure: (error) => failures.push(error),
    onNeedsResync: () => resyncs.push('requested'),
    peekAttachedRunId: () => attached,
    consumeAttachIntent: () => {
      const intent = attachIntent;
      attachIntent = false;
      return intent;
    },
    clearAttachedRun: () => {
      attached = null;
    },
    onDiagnostic: (message) => diagnostics.push(message),
    newId: () => 'fixed-id',
  });

  const abortController = new AbortController();
  const runOptions = {
    messages: options.messages ?? [userMessage('现场很吵，他捂住了耳朵')],
    abortSignal: options.abortSignal ?? abortController.signal,
  } as unknown as ChatModelRunOptions;

  const contents: (ChatModelRunResult['content'] | undefined)[] = [];
  const statuses: (ChatModelRunResult['status'] | undefined)[] = [];
  let thrown: unknown = null;
  let aborted = false;
  try {
    for await (const update of adapter.run(runOptions) as AsyncGenerator<ChatModelRunResult, void>) {
      contents.push(update.content);
      statuses.push(update.status);
      if (options.abortAfterFirstChunk === true && !aborted) {
        aborted = true;
        abortController.abort();
      }
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
    resyncs,
    thrown,
    remainingSkill: skill,
    remainingSubmission: submission,
    remainingAttached: attached,
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

  it('不变量 2：检索类失败文案是「检索暂时不可用」，不是「没有资料」', async () => {
    const result = await runAdapter({ events: [runFailed('injection_failed')] });
    const failure = result.failures[0] as ConsultRunFailure;
    const view = (await import('../domain/errors')).failureViewFor(failure);
    // 标题逐字取设计固定文案（对话页设计数据与文案节），不接受同义改写。
    expect(view.title).toBe('检索暂时不可用');
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

  it('整组回答：POST 走 answers 形态（不发 content），并带上本组的 batch_id', async () => {
    const result = await runAdapter({
      events: [textDelta('收到'), runFinished()],
      pendingSubmission: {
        batchId: 'batch-live-7f3a',
        answers: [
          { id: 'q1', value: '可以' },
          { id: 'q2', skipped: true },
        ],
      },
      pendingSkill: null,
    });

    expect(result.port.sendCalls[0]?.payload).toEqual({
      answers: [
        { id: 'q1', value: '可以' },
        { id: 'q2', skipped: true },
      ],
      // ★ 出网键名逐字 snake_case，值取自提交件里绑定的那一组。
      batch_id: 'batch-live-7f3a',
      skill: null,
      client_message_id: 'fixed-id',
    });
    // 实际序列化后的字节（不是内存对象）——键名以 JSON 文本为准。
    expect(JSON.stringify(result.port.sendCalls[0]?.payload)).toContain('"batch_id":"batch-live-7f3a"');
    expect(JSON.stringify(result.port.sendCalls[0]?.payload)).not.toContain('batchId');
    expect(result.remainingSubmission).toBeNull();
  });

  it('★ 无 batchId 时不阻断提交：载荷里【没有】batch_id 这个键（不是 undefined、不是空串）', async () => {
    const result = await runAdapter({
      events: [textDelta('收到'), runFinished()],
      // 实时路径历史上可能给不出批次标识；契约说它是可选的 ⇒ 不得因此拒发。
      pendingSubmission: { batchId: '', answers: [{ id: 'q1', value: '可以' }] },
    });

    const payload = result.port.sendCalls[0]?.payload ?? {};
    expect(result.port.sendCalls).toHaveLength(1);
    expect(payload).toEqual({
      answers: [{ id: 'q1', value: '可以' }],
      skill: null,
      client_message_id: 'fixed-id',
    });
    // 「键不存在」而不是「键存在但值为 undefined」——后者经 JSON.stringify 后同样消失，
    // 但内存里的形状不同：用 in 断言把两者区分开。
    expect('batch_id' in payload).toBe(false);
    expect(JSON.stringify(payload)).toBe(
      '{"answers":[{"id":"q1","value":"可以"}],"skill":null,"client_message_id":"fixed-id"}',
    );
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

  it('发送阶段的 409 run_not_resumable：请求历史水合，且**不重发**第二条消息', async () => {
    // 场景（契约第 4.1 节）：同一个 client_message_id 在十分钟后重放，首次那次的运行
    // 传输态已过期。服务端回 409 `run_not_resumable`，此时唯一正确的动作是重读历史
    // ——自动重发会再落一条使用者消息，正是服务端拒绝交出失效 run_id 要防的事。
    const result = await runAdapter({
      events: [],
      sendError: new ConsultError('not-resumable', '这条回答的运行已不可续传'),
    });

    expect(result.resyncs).toEqual(['requested']);
    // 只发过一次：没有任何自动重试（`sendCalls` 记录由替身实现写入，本用例把
    // `sendMessage` 换成了直接拒绝的 mock，因此这里数 mock 的调用次数）。
    expect(vi.mocked(result.port.sendMessage)).toHaveBeenCalledTimes(1);
    // 也没有走进订阅：没有 run_id 可订。
    expect(result.port.streamCalls).toHaveLength(0);
    expect(result.diagnostics).toContain('发送阶段不可续传：改走历史水合，不重发');
    expect(result.failures[0]).toBeInstanceOf(ConsultError);
    expect(result.statuses.at(-1)).toMatchObject({ type: 'incomplete', reason: 'error' });
  });

  it('发送阶段的其他失败不请求重读（历史里没有新东西，重读只会闪屏）', async () => {
    const result = await runAdapter({
      events: [],
      sendError: new ConsultError('busy', '会话上已有正在进行的运行'),
    });

    expect(result.resyncs).toEqual([]);
    expect(vi.mocked(result.port.sendMessage)).toHaveBeenCalledTimes(1);
  });

  it('运行中途取消（abortSignal）触发 POST cancel，并停在已收到的 partial 上', async () => {
    // 这条用例此前是 `cancelCalls.length <= 1`，而它在「一次都没取消」时同样成立——
    // 一个永远不会失败的检查（2026-10-29 审查）。现在改成在流**还没结束**时中止：
    // 判据是 cancel 恰好打了一次，且已渲染的正文没有被丢掉。
    const port = createConsultPortStub();
    // holdStream：先吐一段正文，随后一直挂着，直到 signal 中止——取消只能发生在这一窗口里。
    port.holdStream([textDelta('写了一半')]);

    const result = await runAdapter({ events: [], abortAfterFirstChunk: true, port });

    expect(result.thrown).toBeNull();
    expect(result.port.cancelCalls).toEqual(['run-1']);
    // 只发过一条消息、只订阅过一条运行：取消不会重放运行，也不会再落一条使用者消息。
    expect(result.port.sendCalls).toHaveLength(1);
    expect(result.port.streamCalls).toHaveLength(1);
    expect(lastContent(result.contents).some((part) => part.type === 'text')).toBe(true);
  });

  it('传输失败回流给状态层并以未完成收尾（不静默吞、也不抛未捕获拒绝）', async () => {
    const result = await runAdapter({ events: [], failStream: new Error('连接中断') });

    expect(result.failures[0]).toBeInstanceOf(Error);
    expect(result.thrown).toBeNull();
    expect(result.statuses.at(-1)).toMatchObject({ type: 'incomplete', reason: 'error' });
    expect(result.connections).toContain('failed');
  });
});

/**
 * 应急入口交接（回归守卫）。
 *
 * 缺陷本体（EMG-01）：应急入口的运行业已由 `POST /api/consult/emergency` 启动，而对话页
 * 拿到了 `run_id` 却只用它跳转、从不订阅——运行期间的输出与行动卡一律不显示，必须手动刷新。
 * 因此这里守住的判据是：**认领路径不得再发一条消息，且必须订阅交接过来的那个 run_id**。
 * 下面第二条断言就是「不再发消息」——它在修复前必然失败（旧实现无条件先 sendMessage）。
 */
describe('createConsultChatAdapter — 应急入口认领既有运行', () => {
  it('认领既有运行：不发消息，直接订阅交接过来的 run_id', async () => {
    const result = await runAdapter({
      events: [textDelta('先坐下'), runFinished()],
      attachedRunId: 'run-emg',
      attachIntent: true,
    });

    expect(result.port.sendCalls).toHaveLength(0);
    expect(result.port.streamCalls.map((call) => call.runId)).toEqual(['run-emg']);
    expect(result.thrown).toBeNull();
  });

  it('认领时不消费技能选择与整组回答（本轮没有发送，发送即消费不成立）', async () => {
    const result = await runAdapter({
      events: [runFinished()],
      attachedRunId: 'run-emg',
      attachIntent: true,
      pendingSkill: 'emergency-consulting',
    });

    // 没有发送发生（sendCalls 为空），因此技能选择必须原样留着，下一次发送仍能用。
    expect(result.port.sendCalls).toHaveLength(0);
    expect(result.remainingSkill).toBe('emergency-consulting');
  });

  it('认领的运行到终态后清掉交接（否则后续装配会重复订阅同一次运行）', async () => {
    const result = await runAdapter({
      events: [textDelta('先坐下'), runFinished()],
      attachedRunId: 'run-emg',
      attachIntent: true,
    });

    expect(result.remainingAttached).toBeNull();
  });

  it('流结束但未到终态时不清交接（离开页面或 StrictMode 的模拟卸载后还要能重新认领）', async () => {
    const result = await runAdapter({
      events: [textDelta('只到了一半')],
      attachedRunId: 'run-emg',
      attachIntent: true,
    });

    expect(result.port.sendCalls).toHaveLength(0);
    expect(result.remainingAttached).toBe('run-emg');
  });

  it('没有认领意图时走正常两段式，并清掉过期的交接', async () => {
    const result = await runAdapter({ events: [runFinished()], attachedRunId: 'run-emg' });

    expect(result.port.sendCalls).toHaveLength(1);
    expect(result.port.streamCalls.map((call) => call.runId)).toEqual(['run-1']);
    expect(result.remainingAttached).toBeNull();
  });

  it('有认领意图却没有交接：不发消息也不订阅，留一条诊断（不得静默吞）', async () => {
    const result = await runAdapter({ events: [runFinished()], attachIntent: true });

    expect(result.port.sendCalls).toHaveLength(0);
    expect(result.port.streamCalls).toHaveLength(0);
    expect(result.diagnostics.join('')).toContain('没有对应的运行交接');
  });

  it('认领路径的本地中断**不**取消服务端运行（那次运行由应急入口启动，取消它等于毁掉应急回答）', async () => {
    const controller = new AbortController();
    controller.abort();
    const result = await runAdapter({
      events: [textDelta('先坐下')],
      attachedRunId: 'run-emg',
      attachIntent: true,
      abortSignal: controller.signal,
    });

    expect(result.port.cancelCalls).toHaveLength(0);
    expect(result.diagnostics.join('')).toContain('不取消服务端运行');
  });

  it('对照：普通发送路径的本地中断**要**取消服务端运行（停止按钮语义不能一起丢掉）', async () => {
    const controller = new AbortController();
    controller.abort();
    const result = await runAdapter({ events: [textDelta('写了一半')], abortSignal: controller.signal });

    expect(result.port.cancelCalls).toEqual(['run-1']);
  });
});

describe('chatAdapter — 订阅不可续传后请求历史水合', () => {
  it('not-resumable（409 / 404 归一类）：请求一次重读，并如实收尾为未完成', async () => {
    const result = await runAdapter({
      events: [],
      failStream: new ConsultError('not-resumable', '运行元数据已不在（404）'),
    });

    // 这是本次修复的判据：从前这条路径既不重读、也没有任何出口。
    expect(result.resyncs).toEqual(['requested']);
    expect(result.connections).toContain('failed');
    expect(result.statuses.at(-1)?.type).toBe('incomplete');
    // 已 yield 的 partial 保留（不变量 1）：这里没有正文，但仍是「未完成 + 错误」而不是成功。
    expect(result.thrown).toBeNull();
  });

  it('其他失败不请求重读（401/网络这些情形历史里没有新东西，重读只会闪屏）', async () => {
    const result = await runAdapter({
      events: [],
      failStream: new ConsultError('network', '网络请求失败'),
    });

    expect(result.resyncs).toEqual([]);
    expect(result.connections).toContain('failed');
    expect(result.statuses.at(-1)?.type).toBe('incomplete');
  });
});
