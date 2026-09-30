/**
 * 模块: src/infrastructure/sse.test
 * 职责: SSE 传输的回归守卫——真实字节格式解析、续传、重连上限与畸形行容错
 * 数据来源:
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 4.2 节（三行制 id/event/data、`: ping` 心跳、终态关闭、409）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 7 节（指数退避上限 3 次）
 * 边界:
 *   - 依赖: infrastructure/sse、shared/types/sse
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止用「看起来像」的自造行格式替代契约的真实字节（fixture 必须是 id/event/data 三行制）
 *   - 禁止断言重连「大概发生」——必须断言请求次数与 Last-Event-ID 头的具体值
 */

import { describe, expect, it, vi } from 'vitest';

import {
  backoffDelay,
  parseSseFrames,
  RunNotResumableError,
  RunStreamExhaustedError,
  subscribeRunEvents,
  type SseDiagnostic,
} from './sse';

/** 把文本块编码成字节流（按给定切分，用来制造跨 chunk 的半行）。 */
function byteStream(chunks: readonly string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

/** 逐块喂文本给解析器，收集帧与诊断。 */
async function parse(chunks: readonly string[]): Promise<{ frames: unknown[]; diagnostics: SseDiagnostic[] }> {
  async function* source(): AsyncGenerator<string> {
    for (const chunk of chunks) yield chunk;
  }
  const diagnostics: SseDiagnostic[] = [];
  const frames: unknown[] = [];
  for await (const frame of parseSseFrames(source(), { onDiagnostic: (item) => diagnostics.push(item) })) {
    frames.push(frame);
  }
  return { frames, diagnostics };
}

/** 真实线格式：注释心跳 + 三条事件（三行制），末尾是终态事件并关闭流。 */
const RUN_STREAM_BYTES =
  ': ping\n\n' +
  'id: 1\nevent: run_started\ndata: {"type":"run_started","run_id":"r1","session_id":"s1","surface":"consult","model":"m","activated_skills":["daily-consulting"],"injection_sources":[],"appended_messages":0}\n\n' +
  'id: 2\nevent: text_delta\ndata: {"type":"text_delta","delta":"你好"}\n\n' +
  'id: 3\nevent: progress\ndata: {"type":"progress","message":"正在检索资料…"}\n\n' +
  'id: 4\nevent: text_delta\ndata: {"type":"text_delta","delta":"，这是回答。"}\n\n' +
  'id: 5\nevent: run_finished\ndata: {"type":"run_finished","reason":"completed","citations":[],"usage":{"requests":1,"input_tokens":1,"output_tokens":1,"total_tokens":2},"elapsed_seconds":1.5,"compactions":[]}\n\n';

/** 取一次请求的某个头；缺请求或缺头都返回 undefined（断言里不再做可选链 + 断言）。 */
function headerOf(call: { init: RequestInit | undefined } | undefined, name: string): string | undefined {
  if (call === undefined) return undefined;
  const headers = call.init?.headers;
  if (headers === undefined || headers === null) return undefined;
  return (headers as Record<string, string>)[name];
}

/** 构造一个按调用次数返回不同响应的 fetch 替身。 */
function fetchSequence(responses: readonly (() => Response | Promise<Response>)[]): {
  fetchImpl: typeof fetch;
  calls: { url: string; init: RequestInit | undefined }[];
} {
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  let index = 0;
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    const factory = responses[Math.min(index, responses.length - 1)];
    index += 1;
    if (factory === undefined) throw new Error('测试替身没有更多响应');
    return factory();
  }) as unknown as typeof fetch;
  return { fetchImpl, calls };
}

/** SSE 成功响应。 */
function sseResponse(chunks: readonly string[]): Response {
  return new Response(byteStream(chunks), { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
}

describe('parseSseFrames — 真实线格式', () => {
  it('解析三行制事件，忽略 `: ping` 心跳，id 即序号', async () => {
    const { frames, diagnostics } = await parse([RUN_STREAM_BYTES]);

    expect(diagnostics).toEqual([]);
    expect(frames).toHaveLength(5);
    expect(frames.map((frame) => (frame as { id: number }).id)).toEqual([1, 2, 3, 4, 5]);
    expect((frames[1] as { data: { delta: string } }).data.delta).toBe('你好');
    expect((frames[4] as { event: string }).event).toBe('run_finished');
  });

  it('在半行与多字节字符被切开时仍能解析（跨 chunk 边界）', async () => {
    // 逐字节切分：\\r\\n 与 UTF-8 汉字都被切开。
    const bytes = Array.from(RUN_STREAM_BYTES);
    const chunks: string[] = [];
    for (let index = 0; index < bytes.length; index += 3) {
      chunks.push(bytes.slice(index, index + 3).join(''));
    }
    const { frames } = await parse(chunks);
    expect(frames).toHaveLength(5);
    expect((frames[1] as { data: { delta: string } }).data.delta).toBe('你好');
  });

  it('兼容 CRLF 行尾', async () => {
    const { frames } = await parse(['id: 7\r\nevent: text_delta\r\ndata: {"type":"text_delta","delta":"甲"}\r\n\r\n']);
    expect(frames).toHaveLength(1);
    expect(frames[0]).toMatchObject({ id: 7, event: 'text_delta' });
  });

  it('丢帧都有诊断，且不影响其它帧', async () => {
    const { frames, diagnostics } = await parse([
      'id: 1\nevent: text_delta\n\n', // 缺 data
      'id: 2\nevent: text_delta\ndata: {不是 JSON}\n\n', // JSON 非法
      'id: 3\nevent: text_delta\ndata: {"type":"text_delta","delta":"甲"}\n\n', // 合法
      'id: 4\nevent: 不存在的事件\ndata: {"type":"不存在的事件"}\n\n', // 契约外事件名
      'id: abc\nevent: text_delta\ndata: {"type":"text_delta","delta":"乙"}\n\n', // id 非数字
      'id: 5\nevent: progress\ndata: {"type":"text_delta","delta":"丙"}\n\n', // event 与 data.type 不一致
      'id: 6\nevent: text_delta\ndata: "字符串载荷"\n\n', // 载荷不是事件对象
      'retry: 1000\n\n', // 未知字段（retry 是标准字段，不报诊断）
      'id: 7\nevent: tool_call_started\ndata: {"type":"tool_call_started","tool_name":"search_knowledge","call_id":"c1"}\n\n',
    ]);

    // canary：合法帧确实被解析出来（说明丢弃不是因为解析器整体失效）。
    expect(frames.map((frame) => (frame as { id: number }).id)).toEqual([3, 4, 7]);
    expect(diagnostics.map((item) => item.reason)).toEqual([
      'missing-data',
      'invalid-json',
      'unknown-event',
      'invalid-id',
      'event-mismatch',
      'invalid-payload',
    ]);
    // id 非数字时沿用上一帧的 id（续传依据不得被改写成 0）。
    expect((frames[1] as { id: number }).id).toBe(4);
  });

  it('流末尾的半帧被丢弃并留痕', async () => {
    const { frames, diagnostics } = await parse(['id: 9\nevent: text_delta\ndata: {"type":"text_delta","delta":"未完"}\n']);
    expect(frames).toHaveLength(0);
    expect(diagnostics.map((item) => item.reason)).toEqual(['truncated-frame']);
  });
});

describe('subscribeRunEvents — 订阅、续传与重连', () => {
  it('收到终态事件后结束，不再重连', async () => {
    const { fetchImpl, calls } = fetchSequence([() => sseResponse([RUN_STREAM_BYTES])]);
    const controller = new AbortController();
    const events: string[] = [];

    for await (const event of subscribeRunEvents({ runId: 'r1', signal: controller.signal, fetchImpl })) {
      events.push(event.type);
    }

    expect(events).toEqual(['run_started', 'text_delta', 'progress', 'text_delta', 'run_finished']);
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe('/consult/runs/r1/stream');
    expect(calls[0]?.init?.headers).toMatchObject({ Accept: 'text/event-stream' });
  });

  it('断线（无终态即关闭）时带 Last-Event-ID 续传', async () => {
    const first = 'id: 1\nevent: text_delta\ndata: {"type":"text_delta","delta":"前"}\n\n';
    const { fetchImpl, calls } = fetchSequence([
      () => sseResponse([first]),
      () => sseResponse([RUN_STREAM_BYTES]),
    ]);
    const controller = new AbortController();
    const diagnostics: SseDiagnostic[] = [];
    const events: string[] = [];

    for await (const event of subscribeRunEvents({
      runId: 'r2',
      signal: controller.signal,
      fetchImpl,
      onDiagnostic: (item) => diagnostics.push(item),
      wait: () => Promise.resolve(),
    })) {
      events.push(event.type);
    }

    expect(calls).toHaveLength(2);
    expect(headerOf(calls[0], 'Last-Event-ID')).toBeUndefined();
    // 续传起点是「已收到的最大 id」。
    expect(headerOf(calls[1], 'Last-Event-ID')).toBe('1');
    expect(diagnostics.map((item) => item.reason)).toEqual(['reconnect']);
    expect(diagnostics[0]?.attempt).toBe(1);
    expect(events).toEqual(['text_delta', 'run_started', 'text_delta', 'progress', 'text_delta', 'run_finished']);
  });

  it('重连次数耗尽抛出 RunStreamExhaustedError（默认 3 次 → 共 4 次请求）', async () => {
    const { fetchImpl, calls } = fetchSequence([() => sseResponse([': ping\n\n'])]);
    const controller = new AbortController();
    const diagnostics: SseDiagnostic[] = [];

    await expect(
      (async () => {
        for await (const event of subscribeRunEvents({
          runId: 'r3',
          signal: controller.signal,
          fetchImpl,
          onDiagnostic: (item) => diagnostics.push(item),
          wait: () => Promise.resolve(),
        })) {
          void event;
        }
      })(),
    ).rejects.toBeInstanceOf(RunStreamExhaustedError);

    expect(calls).toHaveLength(4);
    expect(diagnostics.filter((item) => item.reason === 'reconnect')).toHaveLength(3);
    expect(diagnostics.at(-1)?.reason).toBe('reconnect-exhausted');
  });

  it('409 run_not_resumable 直接抛出，不重连', async () => {
    const { fetchImpl, calls } = fetchSequence([() => new Response('', { status: 409 })]);

    await expect(
      (async () => {
        for await (const event of subscribeRunEvents({
          runId: 'r4',
          signal: new AbortController().signal,
          fetchImpl,
          wait: () => Promise.resolve(),
        })) {
          void event;
        }
      })(),
    ).rejects.toBeInstanceOf(RunNotResumableError);
    expect(calls).toHaveLength(1);
  });

  it('取消（abort）结束订阅且不抛错、不重连', async () => {
    const first = 'id: 1\nevent: text_delta\ndata: {"type":"text_delta","delta":"甲"}\n\n';
    const { fetchImpl, calls } = fetchSequence([() => sseResponse([first])]);
    const controller = new AbortController();
    const events: string[] = [];

    for await (const event of subscribeRunEvents({ runId: 'r5', signal: controller.signal, fetchImpl })) {
      events.push(event.type);
      controller.abort();
    }

    expect(events).toEqual(['text_delta']);
    expect(calls).toHaveLength(1);
  });

  it('退避时长有界：指数增长并封顶', () => {
    expect(backoffDelay(1, 500)).toBe(500);
    expect(backoffDelay(2, 500)).toBe(1000);
    expect(backoffDelay(3, 500)).toBe(2000);
    expect(backoffDelay(9, 500)).toBe(4000);
  });
});

describe('契约字节 fixture 的自检', () => {
  it('fixture 含心跳、三行制与终态关闭（防止 fixture 退化成自造格式）', () => {
    expect(RUN_STREAM_BYTES).toContain(': ping');
    expect(RUN_STREAM_BYTES).toContain('\nid: 1\nevent: run_started\ndata: ');
    expect(RUN_STREAM_BYTES).toContain('"type":"run_finished"');
    expect(RUN_STREAM_BYTES.endsWith('}\n\n')).toBe(true);
  });

  it('byteStream 产出的是真实字节而不是字符串', async () => {
    const reader = byteStream([': ping\n\n']).getReader();
    const chunk = await reader.read();
    // 用 ArrayBuffer.isView 而不是 instanceof：jsdom 与 Node 的 Uint8Array 是两份类对象
    // （T09 实测过同类问题），instanceof 在这种环境下恒假。
    expect(ArrayBuffer.isView(chunk.value)).toBe(true);
    expect(new TextDecoder().decode(chunk.value)).toBe(': ping\n\n');
    expect(vi.isMockFunction(fetch)).toBe(false);
  });
});
