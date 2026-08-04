/**
 * SSE 事件流客户端（AI 服务接口契约 §三）。
 *
 * EventSource 不支持自定义 Authorization 头——以 fetch + ReadableStream
 * 实现（Bearer 注入），按 SSE 帧格式解析 event/id/data 三元组。
 * 支持 Last-Event-Id 续传。
 */

import { tokenStorage } from '@/infrastructure/http/tokenManager';

export interface SseFrame {
  type: string;
  id: number;
  data: Record<string, unknown>;
}

const API_BASE: string = import.meta.env.VITE_API_BASE || '';

export interface StreamHandlers {
  onFrame: (frame: SseFrame) => void;
  onError?: (err: Error) => void;
}

/** 订阅应急会话事件流；返回取消函数。 */
export function streamConsultEvents(
  sessionId: string,
  handlers: StreamHandlers,
  lastEventId = 0,
): () => void {
  const controller = new AbortController();

  (async () => {
    try {
      const headers: Record<string, string> = {};
      const token = tokenStorage.getAccessToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;
      if (lastEventId > 0) headers['Last-Event-Id'] = String(lastEventId);

      const res = await fetch(`${API_BASE}/api/v1/consult/stream/${sessionId}`, {
        method: 'GET',
        headers,
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        handlers.onError?.(new Error(`事件流连接失败（${res.status}）`));
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      let currentType = '';
      let currentId = 0;
      let currentData = '';

      const flush = () => {
        if (!currentType) return;
        let parsed: Record<string, unknown> = {};
        try {
          parsed = JSON.parse(currentData || '{}');
        } catch {
          parsed = {};
        }
        handlers.onFrame({ type: currentType, id: currentId, data: parsed });
        currentType = '';
        currentData = '';
      };

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let idx: number;
        while ((idx = buffer.indexOf('\n')) !== -1) {
          const line = buffer.slice(0, idx).replace(/\r$/, '');
          buffer = buffer.slice(idx + 1);
          if (line === '') {
            flush();
          } else if (line.startsWith('event: ')) {
            currentType = line.slice(7);
          } else if (line.startsWith('id: ')) {
            currentId = Number(line.slice(4)) || 0;
          } else if (line.startsWith('data: ')) {
            currentData = line.slice(6);
          }
        }
      }
      flush();
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        handlers.onError?.(err as Error);
      }
    }
  })();

  return () => controller.abort();
}
