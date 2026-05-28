/**
 * 微信小程序运行时 polyfills。
 *
 * AbortController — 微信基础库部分版本缺失此 API，
 * 但 Taro.request 的 signal 参数依赖它。
 * 提供最小化 polyfill，使现有 AbortController 代码无需修改。
 */

/* eslint-disable @typescript-eslint/no-extraneous-class */

interface PolyfillAbortSignal {
  aborted: boolean;
  reason?: unknown;
  onabort: (() => void) | null;
  _listeners: Array<() => void>;
  addEventListener(_type: string, listener: () => void): void;
  removeEventListener(_type: string, listener: () => void): void;
}

class PolyfillAbortSignalImpl implements PolyfillAbortSignal {
  aborted: boolean = false;
  reason: unknown = undefined;
  onabort: (() => void) | null = null;
  _listeners: Array<() => void> = [];

  addEventListener(_type: string, listener: () => void): void {
    this._listeners.push(listener);
  }

  removeEventListener(_type: string, listener: () => void): void {
    const idx = this._listeners.indexOf(listener);
    if (idx >= 0) this._listeners.splice(idx, 1);
  }

  _abort(reason?: unknown): void {
    if (this.aborted) return;
    this.aborted = true;
    this.reason = reason;
    if (this.onabort) this.onabort();
    this._listeners.forEach((fn) => fn());
  }
}

class PolyfillAbortController {
  signal: PolyfillAbortSignalImpl;

  constructor() {
    this.signal = new PolyfillAbortSignalImpl();
  }

  abort(reason?: unknown): void {
    this.signal._abort(reason);
  }
}

// 仅在不支持时注入
if (typeof (globalThis as Record<string, unknown>).AbortController === 'undefined') {
  (globalThis as Record<string, unknown>).AbortController = PolyfillAbortController;
}

if (typeof (globalThis as Record<string, unknown>).DOMException === 'undefined') {
  (globalThis as Record<string, unknown>).DOMException = class DOMException extends Error {
    constructor(message: string, _name?: string) {
      super(message);
    }
  };
}
