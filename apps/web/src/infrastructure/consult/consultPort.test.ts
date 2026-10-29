/**
 * 模块: src/infrastructure/consult/consultPort.test
 * 职责: 咨询面端口实现的回归守卫——端点形状、错误翻译、401 处置与续传通告
 * 数据来源:
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 2 节错误码、第 3～5 节端点形状
 * 边界:
 *   - 依赖: infrastructure/consult/consultPort、http/client、sse
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止发明契约外的端点路径或字段
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { createConsultApi, translateConsultError } from './consultPort';
import { HttpError, clearUnauthorizedHandler, setUnauthorizedHandler } from '../http/client';
import { ConsultError } from '../../features/consult/domain/errors';
import type { RunEvent } from '../../shared/types/sse';
import { runFinished, runStarted, textDelta } from '../../features/consult/test/fixtures';

/** 一帧 SSE 的三行制文本。 */
function frame(id: number, event: RunEvent): string {
  return `id: ${String(id)}\nevent: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;
}

/** 组装一个 SSE 响应。 */
function sseResponse(text: string, status = 200): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(text));
      controller.close();
    },
  });
  return new Response(body, { status, headers: { 'Content-Type': 'text/event-stream' } });
}

/** JSON 响应。 */
function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { 'Content-Type': 'application/json' } });
}

afterEach(() => {
  clearUnauthorizedHandler();
  vi.unstubAllGlobals();
});

describe('createConsultApi — 端点形状', () => {
  it('建会话、发消息、应急入口与取消走契约路径', async () => {
    const calls: { url: string; init: RequestInit | undefined }[] = [];
    const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), init });
      if (String(input).endsWith('/cancel')) return new Response('', { status: 202 });
      if (String(input) === '/api/consult/sessions') {
        return jsonResponse({ session_id: 's1', support_object_id: null, onboarding_pending: false }, 201);
      }
      if (String(input) === '/api/consult/sessions/s1/messages') {
        return jsonResponse({ run_id: 'run-1', session_id: 's1' }, 202);
      }
      return jsonResponse({ session_id: 's-emg', run_id: 'run-emg' }, 202);
    }) as unknown as typeof fetch;
    vi.stubGlobal('fetch', fetchImpl);

    const api = createConsultApi({ fetchImpl });
    expect(await api.createSession()).toEqual({ session_id: 's1', support_object_id: null, onboarding_pending: false });
    expect(
      await api.sendMessage('s1', { content: '你好', skill: null, client_message_id: 'c1' }),
    ).toEqual({ run_id: 'run-1', session_id: 's1' });
    expect(await api.emergencyStart({ items: [] })).toEqual({ session_id: 's-emg', run_id: 'run-emg' });
    await api.cancelRun('run-1');

    // 期望的是**实际发出的 URL**，因此含 `/api` 前缀（2026-10-01 起业务接口统一在该前缀下）。
    // 这里写全路径是刻意的：它是「前端确实按契约拼了带前缀的地址」的唯一证据，
    // 用模糊匹配会让「少拼或多拼一层前缀」这类缺陷静默通过。
    expect(calls.map((call) => call.url)).toEqual([
      '/api/consult/sessions',
      '/api/consult/sessions/s1/messages',
      '/api/consult/emergency',
      '/api/consult/runs/run-1/cancel',
    ]);
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({});
    expect(JSON.parse(String(calls[1]?.init?.body))).toEqual({
      content: '你好',
      skill: null,
      client_message_id: 'c1',
    });
  });

  it('会话列表带分页参数，历史水合按 id 编码', async () => {
    const urls: string[] = [];
    const fetchImpl = (async (input: RequestInfo | URL) => {
      urls.push(String(input));
      return jsonResponse({ items: [], next_cursor: null });
    }) as unknown as typeof fetch;
    vi.stubGlobal('fetch', fetchImpl);

    const api = createConsultApi({ fetchImpl });
    await api.listSessions({ cursor: 'c1', limit: 20 });
    await api.listSessions({ cursor: null, limit: undefined });
    await api.loadHistory('a b/c');

    expect(urls).toEqual([
      '/api/consult/sessions?cursor=c1&limit=20',
      '/api/consult/sessions',
      '/api/consult/sessions/a%20b%2Fc/messages',
    ]);
  });

  it('202 空体的取消端点被当作成功（不因缺 JSON 正文而失败）', async () => {
    const fetchImpl = (async () => new Response('', { status: 202 })) as unknown as typeof fetch;
    vi.stubGlobal('fetch', fetchImpl);

    await expect(createConsultApi({ fetchImpl }).cancelRun('run-1')).resolves.toBeUndefined();
  });

  it('技能目录只含可手选的两个技能（值域裁决：应急走表单入口，不进选择器）', async () => {
    const skills = await createConsultApi().listSkills();
    expect(skills.map((skill) => skill.id)).toEqual(['daily-consulting', 'profile-curation']);
  });
});

describe('错误翻译', () => {
  it('HTTP 状态码映射到领域失败种类', () => {
    expect(translateConsultError(new HttpError(401, 'x')).kind).toBe('unauthorized');
    expect(translateConsultError(new HttpError(404, 'x')).kind).toBe('not-found');
    expect(translateConsultError(new HttpError(409, 'session_busy')).kind).toBe('busy');
    // 409 必须按 `detail` 分开（契约第 2 节码表 + 第 4.1 节）：两个码的处置相反。
    expect(translateConsultError(new HttpError(409, 'run_not_resumable')).kind).toBe('not-resumable');
    // 未知 409 不回落成 busy——那会让使用者白等一个不存在的运行，并掩盖新增错误码。
    expect(translateConsultError(new HttpError(409, 'something_new')).kind).toBe('unexpected');
    expect(translateConsultError(new HttpError(422, 'x')).kind).toBe('invalid');
    expect(translateConsultError(new HttpError(503, 'x')).kind).toBe('unavailable');
    expect(translateConsultError(new HttpError(500, 'x')).kind).toBe('unexpected');
    // 网络层失败（fetch 抛 TypeError）按可重试的网络失败呈现。
    expect(translateConsultError(new TypeError('Failed to fetch')).kind).toBe('network');
    // 已经是领域失败时原样返回（不重复包装）。
    const known = new ConsultError('busy', '忙');
    expect(translateConsultError(known)).toBe(known);
  });

  it('发消息端点的 409 run_not_resumable 不被说成「会话忙」（契约第 4.1 节）', async () => {
    // 端到端走一遍真实翻译链：`request()` 从响应体里取 `detail`，`HttpError` 带着它进来。
    const fetchImpl = (async () =>
      new Response(JSON.stringify({ detail: 'run_not_resumable' }), {
        status: 409,
        headers: { 'Content-Type': 'application/json' },
      })) as unknown as typeof fetch;
    vi.stubGlobal('fetch', fetchImpl);

    await expect(
      createConsultApi({ fetchImpl }).sendMessage('s1', { content: 'x', client_message_id: 'c1' }),
    ).rejects.toMatchObject({ kind: 'not-resumable' });
  });

  it('发消息端点的 409 session_busy 仍是 busy（既有行为不变）', async () => {
    const fetchImpl = (async () =>
      new Response(JSON.stringify({ detail: 'session_busy' }), {
        status: 409,
        headers: { 'Content-Type': 'application/json' },
      })) as unknown as typeof fetch;
    vi.stubGlobal('fetch', fetchImpl);

    await expect(
      createConsultApi({ fetchImpl }).sendMessage('s1', { content: 'x', client_message_id: 'c1' }),
    ).rejects.toMatchObject({ kind: 'busy' });
  });

  it('发消息端点的未知 409 不假设成 busy', async () => {
    const fetchImpl = (async () =>
      new Response(JSON.stringify({ detail: 'rate_limited_later' }), {
        status: 409,
        headers: { 'Content-Type': 'application/json' },
      })) as unknown as typeof fetch;
    vi.stubGlobal('fetch', fetchImpl);

    await expect(
      createConsultApi({ fetchImpl }).sendMessage('s1', { content: 'x', client_message_id: 'c1' }),
    ).rejects.toMatchObject({ kind: 'unexpected' });
  });

  it('JSON 端点的 401 触发 app 层处置回调并抛领域失败', async () => {
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    const fetchImpl = (async () => new Response('', { status: 401 })) as unknown as typeof fetch;
    vi.stubGlobal('fetch', fetchImpl);

    await expect(createConsultApi({ fetchImpl }).loadHistory('s1')).rejects.toMatchObject({ kind: 'unauthorized' });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });
});

describe('streamRun — 事件流与续传通告', () => {
  it('把 SSE 帧解成 RunEvent 流，事件名与载荷原样', async () => {
    const events: RunEvent[] = [
      runStarted(['daily-consulting']),
      textDelta('你好'),
      runFinished(),
    ];
    const text = events.map((event, index) => frame(index + 1, event)).join('');
    const fetchImpl = (async () => sseResponse(text)) as unknown as typeof fetch;

    const api = createConsultApi({ fetchImpl, onDiagnostic: () => undefined });
    const received: string[] = [];
    for await (const event of api.streamRun({ runId: 'run-1', signal: new AbortController().signal })) {
      received.push(event.type);
    }
    expect(received).toEqual(['run_started', 'text_delta', 'run_finished']);
  });

  it('SSE 的 401 走端口自带的处置回调（JSON 路径的处置覆盖不到它）', async () => {
    const onUnauthorized = vi.fn();
    const fetchImpl = (async () => new Response('', { status: 401 })) as unknown as typeof fetch;
    const api = createConsultApi({ fetchImpl, onUnauthorized, onDiagnostic: () => undefined });

    await expect(
      (async () => {
        for await (const event of api.streamRun({ runId: 'run-1', signal: new AbortController().signal })) {
          void event;
        }
      })(),
    ).rejects.toMatchObject({ kind: 'unauthorized' });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it('409 翻译成 not-resumable（调用方据此改走历史水合）', async () => {
    const fetchImpl = (async () => new Response('', { status: 409 })) as unknown as typeof fetch;
    const api = createConsultApi({ fetchImpl, onDiagnostic: () => undefined });

    await expect(
      (async () => {
        for await (const event of api.streamRun({ runId: 'run-1', signal: new AbortController().signal })) {
          void event;
        }
      })(),
    ).rejects.toMatchObject({ kind: 'not-resumable' });
  });

  it('重连时上报 reconnecting，恢复后上报 resumed', async () => {
    const notices: string[] = [];
    let call = 0;
    const fetchImpl = (async () => {
      call += 1;
      // 第一次连接直接断开（无终态），第二次给出终态。
      return call === 1
        ? sseResponse(frame(1, textDelta('前')))
        : sseResponse(frame(2, runFinished()));
    }) as unknown as typeof fetch;

    const api = createConsultApi({ fetchImpl, onDiagnostic: () => undefined });
    for await (const event of api.streamRun({
      runId: 'run-1',
      signal: new AbortController().signal,
      onNotice: (notice) => notices.push(notice.kind),
    })) {
      void event;
    }

    expect(notices).toEqual(['reconnecting', 'resumed']);
  });
});
