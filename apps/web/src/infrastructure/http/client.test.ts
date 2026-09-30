/**
 * 模块: src/infrastructure/http/client.test
 * 职责: fetch 包装器的 401 语义与失败分支（对抗用例）
 * 数据来源:
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 2 节错误码（401 清本地状态跳登录页）
 * 边界:
 *   - 依赖: 无（用 vi.stubGlobal 替换 fetch）
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止把 401 静默当成空数据（本用例守住这条）
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { HttpError, clearUnauthorizedHandler, request, setUnauthorizedHandler } from './client';

/** 构造一个最小 Response 替身；只实现被测代码读取的属性与方法。 */
function jsonResponse(status: number, body: unknown, statusText = ''): Response {
  const raw = JSON.stringify(body);
  return {
    status,
    ok: status >= 200 && status < 300,
    statusText,
    text: async () => raw,
    json: async () => JSON.parse(raw) as unknown,
  } as unknown as Response;
}

/** 构造一个正文不是 JSON 的响应（网关页等）。 */
function nonJsonResponse(status: number, statusText: string): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    statusText,
    text: async () => '<html>gateway</html>',
    json: async () => {
      throw new SyntaxError('Unexpected token <');
    },
  } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
  clearUnauthorizedHandler();
});

describe('request — 401 语义', () => {
  it('P0 401 触发处置回调并抛 HttpError', async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(401, { detail: 'unauthorised' })));

    await expect(request('/consult/sessions')).rejects.toThrow(HttpError);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('P1 非 401 失败不得触发处置回调', async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(503, { detail: '检索暂时不可用' })));

    await expect(request('/library/items')).rejects.toThrow('检索暂时不可用');
    expect(handler).not.toHaveBeenCalled();
  });

  it('P1 错误体不是 JSON 时回退状态文本，不吞掉状态码', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => nonJsonResponse(502, 'Bad Gateway')));

    await expect(request('/health')).rejects.toThrow('HTTP 502: Bad Gateway');
  });

  it('P1 错误体是空串时同样回退状态文本', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        status: 500,
        ok: false,
        statusText: 'Internal Server Error',
        text: async () => '',
      }) as unknown as Response),
    );

    await expect(request('/health')).rejects.toThrow('HTTP 500: Internal Server Error');
  });

  it('P3 成功响应原样返回解析后的载荷', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(200, { session_id: 's1' })));

    await expect(request<{ session_id: string }>('/consult/sessions')).resolves.toEqual({
      session_id: 's1',
    });
  });

  it('未装配处置回调时 401 仍然抛错（不静默返回空数据）', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(401, {})));

    await expect(request('/consult/sessions')).rejects.toThrow(HttpError);
  });

  it('P3 带 body 时自动补 Content-Type，不带 body 时不补', async () => {
    const sentHeaders: Record<string, string>[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: string, init?: RequestInit) => {
        sentHeaders.push({ ...(init?.headers as Record<string, string>) });
        return jsonResponse(200, {});
      }),
    );

    await request('/consult/sessions', { method: 'POST', body: '{}' });
    expect(sentHeaders[0]?.['Content-Type']).toBe('application/json');

    await request('/consult/sessions');
    expect(sentHeaders[1]?.['Content-Type']).toBeUndefined();
  });
});
