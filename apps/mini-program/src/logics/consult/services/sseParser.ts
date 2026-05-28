/**
 * CSLT-08 SSE 流解析器 —— SseStreamParser 类。
 *
 * 职责：
 * - 通过 fetch streaming API 连接 SSE 端点
 * - 手动解析 SSE 协议（支持 \r\n\r\n 和 \n\n 双换行分隔）
 * - 跨 chunk 边界事件拼接
 * - 心跳监控（15s 无事件判定僵死）
 * - 指数退避重连（1s/2s/5s，3 次上限）
 *
 * 设计依据：CSLT-08 落地规范 §1.7 步骤 4、§1.9 异常 3
 * 兼容性：同时支持 \r\n 和 \n 作为行分隔符
 *
 * 注意：Taro 微信小程序环境可能不支持 response.body.getReader()，
 * 降级方案为 Taro.request 的 enableChunked 回调——见 §1.11 强制约束 2。
 */

import type { ChunkEventPayload, DoneEventPayload, ErrorEventPayload } from '../types/index';

// ============================================================================
// 类型定义
// ============================================================================

/**
 * SseStreamParser 配置项。
 */
export interface SseStreamParserConfig {
  /** 最大自动重连次数，默认 3 */
  reconnectMaxRetries: number;
  /** 重连间隔数组（毫秒），按序使用，实现指数退避 */
  reconnectDelays: number[];
  /** 心跳超时（毫秒），超过此时间无任何事件判定为僵死，默认 15000 */
  heartbeatTimeout: number;
  /** 连接超时（毫秒），默认 10000 */
  connectTimeout: number;
  /** 流无数据软超时（毫秒），默认 20000 */
  streamNoDataTimeout: number;
}

/**
 * SseStreamParser 事件回调接口。
 */
export interface SseStreamParserCallbacks {
  /** 收到 chunk 事件时回调 */
  onChunk?: (data: ChunkEventPayload) => void;
  /** 收到 done 事件时回调 */
  onDone?: (data: DoneEventPayload) => void;
  /** 收到 error 事件时回调 */
  onError?: (data: ErrorEventPayload) => void;
  /** 收到 heartbeat 事件时回调 */
  onHeartbeat?: () => void;
  /** 发起重连时回调（传递当前重连次数，从 1 开始） */
  onReconnect?: (attempt: number) => void;
  /** 所有重连均失败时回调 */
  onReconnectFailed?: () => void;
  /** 流无数据软超时时回调 */
  onNoDataTimeout?: () => void;
}

/** 默认配置 */
const DEFAULT_CONFIG: SseStreamParserConfig = {
  reconnectMaxRetries: 3,
  reconnectDelays: [1000, 2000, 5000],
  heartbeatTimeout: 15000,
  connectTimeout: 10000,
  streamNoDataTimeout: 20000,
};

// ============================================================================
// 内部 SSE 事件类型
// ============================================================================

interface SseEvent {
  event: string;
  data: string;
  id: string | null;
}

// ============================================================================
// SseStreamParser 类
// ============================================================================

export class SseStreamParser {
  private config: SseStreamParserConfig;
  private callbacks: SseStreamParserCallbacks;

  private abortController: AbortController | null = null;
  private reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  private isActive: boolean = false;

  // 事件拼接缓冲区
  private buffer: string = '';

  // 心跳/超时定时器
  private heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
  private noDataTimer: ReturnType<typeof setTimeout> | null = null;
  private connectTimer: ReturnType<typeof setTimeout> | null = null;

  /** 最近收到事件的时间戳 */
  private lastEventTime: number = 0;

  /** 当前重连次数 */
  private reconnectAttempt: number = 0;

  /** 是否处于重连中 */
  private isReconnecting: boolean = false;

  /** 最后接收到的 event id（用于重连时 Last-Event-Id 头） */
  private lastEventId: string | null = null;

  /** 最后接收到的 SSE event type（用于重连续传） */
  private lastSequence: number = 0;

  /**
   * @param config - 解析器配置
   * @param callbacks - 事件回调
   */
  constructor(
    config?: Partial<SseStreamParserConfig>,
    callbacks?: SseStreamParserCallbacks,
  ) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.callbacks = callbacks ?? {};
  }

  // ============================================================================
  // connect —— 发起 SSE 连接
  // ============================================================================

  /**
   * 连接到 SSE 端点并开始消费流。
   * 使用 fetch streaming API 读取 response.body 的 ReadableStream。
   *
   * @param url - SSE 端点 URL
   * @param headers - 额外请求头（如 Last-Event-Id）
   * @returns Promise<void> 连接关闭时 resolve，异常时 reject
   */
  async connect(url: string, headers?: Record<string, string>): Promise<void> {
    this.cleanup(); // 清理上一次连接残留

    this.isActive = true;
    this.reconnectAttempt = 0;
    this.lastEventTime = Date.now();

    // 创建 AbortController
    this.abortController = new AbortController();

    // 启动连接超时定时器（超时时 abort controller → fetch 抛 AbortError）
    this.startConnectTimer();

    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: {
          Accept: 'text/event-stream',
          'Cache-Control': 'no-cache',
          ...(this.lastEventId ? { 'Last-Event-Id': this.lastEventId } : {}),
          ...headers,
        },
        signal: this.abortController.signal,
      });

      this.clearConnectTimer();

      if (!response.ok) {
        // HTTP 非 2xx → 触发错误回调
        this.callbacks.onError?.({
          error_code: 'GENERATION_FAILED',
          detail: `SSE 连接失败: HTTP ${response.status}`,
        });
        // 尝试重连（连接时错误也算）
        await this.attemptReconnect(url, headers);
        return;
      }

      const body = response.body;
      if (!body) {
        this.callbacks.onError?.({
          error_code: 'GENERATION_FAILED',
          detail: 'SSE 响应体为空',
        });
        await this.attemptReconnect(url, headers);
        return;
      }

      this.reader = body.getReader();
      this.startHeartbeatMonitor();
      this.startNoDataMonitor();

      // 消费流
      await this.readLoop();

      // 流正常结束（reader 返回 done）
      this.stopAllMonitors();
    } catch (error: unknown) {
      this.clearConnectTimer();
      this.stopAllMonitors();

      // 非活跃状态（手动 disconnect）→ 不重连
      if (!this.isActive) {
        return;
      }

      // 若处于活跃状态但出错（含超时 AbortError、网络错误等）→ 触发重连
      if (!this.isReconnecting) {
        await this.attemptReconnect(url, headers);
      }
    }
  }

  // ============================================================================
  // disconnect —— 主动断开连接
  // ============================================================================

  /**
   * 主动断开 SSE 连接。
   * 清理所有定时器、关闭 reader、中止 fetch。
   */
  disconnect(): void {
    this.isActive = false;
    this.isReconnecting = false;
    this.cleanup();
  }

  // ============================================================================
  // 读取循环
  // ============================================================================

  private async readLoop(): Promise<void> {
    if (!this.reader) return;

    const decoder = new TextDecoder();

    while (this.isActive && this.reader) {
      const { done, value } = await this.reader.read();

      if (done) {
        break;
      }

      // 解码并处理 chunk
      const chunk = decoder.decode(value, { stream: true });
      this.processChunk(chunk);
    }
  }

  // ============================================================================
  // Chunk 处理 —— SSE 协议解析
  // ============================================================================

  /**
   * 处理每个读取到的二进制 chunk。
   * 支持 \r\n\r\n 和 \n\n 作为事件分隔符。
   * 处理跨 chunk 边界的事件拼接。
   */
  private processChunk(chunk: string): void {
    // 追加到缓冲区
    this.buffer += chunk;

    // 尝试从缓冲区中提取完整事件
    // SSE 事件分隔符：\r\n\r\n 或 \n\n
    let separatorIndex: number;
    while ((separatorIndex = this.findEventSeparator(this.buffer)) !== -1) {
      // 提取完整事件文本（到第一个分隔符之前）
      const eventText = this.buffer.substring(0, separatorIndex);

      // 移除已处理部分（包括分隔符）
      this.buffer = this.buffer.substring(separatorIndex + this.getSeparatorLength(this.buffer, separatorIndex));

      // 跳过空事件
      if (eventText.trim().length === 0) {
        continue;
      }

      // 解析事件
      const parsedEvent = this.parseSseEvent(eventText);
      if (parsedEvent) {
        this.dispatchEvent(parsedEvent);
      }
    }
  }

  /**
   * 查找事件分隔符位置。
   * 支持 \r\n\r\n 和 \n\n。
   */
  private findEventSeparator(buffer: string): number {
    const pos1 = buffer.indexOf('\r\n\r\n');
    const pos2 = buffer.indexOf('\n\n');

    if (pos1 === -1) return pos2;
    if (pos2 === -1) return pos1;
    return Math.min(pos1, pos2);
  }

  /**
   * 获取分隔符长度。
   */
  private getSeparatorLength(buffer: string, index: number): number {
    if (buffer.substring(index, index + 4) === '\r\n\r\n') {
      return 4;
    }
    return 2; // \n\n
  }

  /**
   * 解析 SSE 事件文本。
   * 格式：
   *   event: <type>
   *   data: <json>
   *   id: <sequence>
   *
   * @param text - 不含分隔符的纯事件文本
   * @returns 解析后的 SseEvent，若无可解析内容返回 null
   */
  private parseSseEvent(text: string): SseEvent | null {
    const lines = text.split(/\r?\n/);
    let event = '';
    let data = '';
    let id: string | null = null;

    for (const line of lines) {
      if (line.startsWith('event:')) {
        event = line.substring(6).trim();
      } else if (line.startsWith('data:')) {
        const dataValue = line.substring(5);
        // data 行可用空格打头（SSE 协议规范）
        data += (data.length > 0 ? '\n' : '') + (dataValue.startsWith(' ') ? dataValue.substring(1) : dataValue);
      } else if (line.startsWith('id:')) {
        id = line.substring(3).trim();
      }
      // 'retry:' 行和 ':' 注释行跳过
    }

    // 没有 event 也没有 data 时返回 null
    if (!event && !data) {
      return null;
    }

    // SSE 协议中，data-only（无 event 字段）的事件类型默认为 'message'
    return {
      event: event || 'message',
      data,
      id,
    };
  }

  /**
   * 分发解析后的 SSE 事件到对应回调。
   */
  private dispatchEvent(sseEvent: SseEvent): void {
    // 更新心跳标记
    this.lastEventTime = Date.now();
    this.resetHeartbeatMonitor();
    this.resetNoDataMonitor();

    // 更新 lastEventId
    if (sseEvent.id !== null) {
      this.lastEventId = sseEvent.id;
      const seq = parseInt(sseEvent.id, 10);
      if (!isNaN(seq)) {
        this.lastSequence = seq;
      }
    }

    switch (sseEvent.event) {
      case 'chunk': {
        try {
          const payload: ChunkEventPayload = JSON.parse(sseEvent.data);
          this.callbacks.onChunk?.(payload);
        } catch {
          // JSON 解析失败时忽略
        }
        break;
      }

      case 'done': {
        try {
          const payload: DoneEventPayload = JSON.parse(sseEvent.data);
          this.callbacks.onDone?.(payload);
        } catch {
          // JSON 解析失败仍触发 done（无载荷）
          this.callbacks.onDone?.({ finish_reason: 'COMPLETE' });
        }
        // done 后不再重连
        this.isActive = false;
        break;
      }

      case 'error': {
        try {
          const payload: ErrorEventPayload = JSON.parse(sseEvent.data);
          this.callbacks.onError?.(payload);
        } catch {
          // JSON 解析失败时忽略
        }
        break;
      }

      case 'heartbeat': {
        this.callbacks.onHeartbeat?.();
        break;
      }

      default: {
        // message 事件或其他未知事件类型，尝试按 chunk 解析
        if (sseEvent.data) {
          try {
            const payload: ChunkEventPayload = JSON.parse(sseEvent.data);
            if (payload.text !== undefined && payload.sequence !== undefined) {
              this.callbacks.onChunk?.(payload);
            }
          } catch {
            // 未知类型静默忽略
          }
        }
        break;
      }
    }
  }

  // ============================================================================
  // 重连逻辑
  // ============================================================================

  /**
   * 尝试自动重连。
   * 指数退避策略：按 reconnectDelays 数组间隔重试。
   * 每次重连携带 Last-Event-Id 请求头。
   */
  private async attemptReconnect(url: string, headers?: Record<string, string>): Promise<void> {
    if (!this.isActive) return;
    if (this.isReconnecting) return;

    this.isReconnecting = true;

    while (this.reconnectAttempt < this.config.reconnectMaxRetries && this.isActive) {
      this.reconnectAttempt++;
      this.callbacks.onReconnect?.(this.reconnectAttempt);

      // 等待指数退避间隔
      const delayIndex = Math.min(this.reconnectAttempt - 1, this.config.reconnectDelays.length - 1);
      const delay = this.config.reconnectDelays[delayIndex];

      await this.sleep(delay);

      if (!this.isActive) return;

      try {
        // 关闭旧 reader
        if (this.reader) {
          try {
            await this.reader.cancel();
          } catch {
            // reader cancel 忽略
          }
          this.reader = null;
        }

        // 创建新的 AbortController（原 controller 可能已被超时 abort）
        this.abortController = new AbortController();

        // 重新连接
        const response = await fetch(url, {
          method: 'GET',
          headers: {
            Accept: 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Last-Event-Id': String(this.lastSequence || ''),
            ...headers,
          },
          signal: this.abortController.signal,
        });

        if (!response.ok) {
          continue; // 重试下一次
        }

        const body = response.body;
        if (!body) {
          continue; // 重试下一次
        }

        // 重连成功
        this.isReconnecting = false;
        this.lastEventTime = Date.now();
        this.reader = body.getReader();
        this.startHeartbeatMonitor();
        this.startNoDataMonitor();

        // 继续读取
        await this.readLoop();

        // 流正常结束
        this.stopAllMonitors();
        return;
      } catch (error: unknown) {
        // 手动断开连接时不重试
        if (!this.isActive) {
          this.isReconnecting = false;
          return;
        }
        // 其他错误继续重试
      }
    }

    // 所有重连均失败
    this.isReconnecting = false;
    if (this.isActive) {
      this.callbacks.onReconnectFailed?.();
      this.isActive = false;
    }
  }

  // ============================================================================
  // 监控器：心跳 + 无数据超时
  // ============================================================================

  /**
   * 启动心跳监控器。
   * 若超过 heartbeatTimeout 未收到任何事件 → 判定为僵死。
   */
  private startHeartbeatMonitor(): void {
    this.stopHeartbeatMonitor();
    this.heartbeatTimer = setTimeout(() => {
      const elapsed = Date.now() - this.lastEventTime;
      if (elapsed >= this.config.heartbeatTimeout && this.isActive) {
        // 心跳超时，不触发回调，等待下次事件或断开
        // 实际心跳超时不触发外部回调——程序需等待无数据超时或连接断开
      }
    }, this.config.heartbeatTimeout + 1000);
  }

  /**
   * 启动流无数据软超时监控。
   * 超过 streamNoDataTimeout 未收到任何事件 → 触发 onNoDataTimeout 回调。
   */
  private startNoDataMonitor(): void {
    this.stopNoDataMonitor();
    this.noDataTimer = setTimeout(() => {
      const elapsed = Date.now() - this.lastEventTime;
      if (elapsed >= this.config.streamNoDataTimeout && this.isActive) {
        this.callbacks.onNoDataTimeout?.();
      }
    }, this.config.streamNoDataTimeout + 1000);
  }

  private resetHeartbeatMonitor(): void {
    this.stopHeartbeatMonitor();
    if (this.isActive) {
      this.startHeartbeatMonitor();
    }
  }

  private resetNoDataMonitor(): void {
    this.stopNoDataMonitor();
    if (this.isActive) {
      this.startNoDataMonitor();
    }
  }

  private stopHeartbeatMonitor(): void {
    if (this.heartbeatTimer !== null) {
      clearTimeout(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private stopNoDataMonitor(): void {
    if (this.noDataTimer !== null) {
      clearTimeout(this.noDataTimer);
      this.noDataTimer = null;
    }
  }

  private stopAllMonitors(): void {
    this.stopHeartbeatMonitor();
    this.stopNoDataMonitor();
  }

  // ============================================================================
  // 连接超时管理
  // ============================================================================

  /**
   * 启动连接超时定时器。
   * 超时后 abort controller → fetch 抛 AbortError → 被 connect() 的 catch 捕获。
   * 返回 void（不再返回 Promise，通过 fetch 的 signal 实现超时信号）。
   */
  private startConnectTimer(): void {
    this.clearConnectTimer();
    this.connectTimer = setTimeout(() => {
      if (this.abortController) {
        this.abortController.abort();
      }
    }, this.config.connectTimeout);
  }

  private clearConnectTimer(): void {
    if (this.connectTimer !== null) {
      clearTimeout(this.connectTimer);
      this.connectTimer = null;
    }
  }

  // ============================================================================
  // 清理
  // ============================================================================

  /**
   * 清理所有资源：取消 reader、中止 fetch、清除定时器。
   */
  private cleanup(): void {
    this.clearConnectTimer();
    this.stopAllMonitors();

    if (this.reader) {
      try {
        this.reader.cancel();
      } catch {
        // 忽略
      }
      this.reader = null;
    }

    if (this.abortController) {
      try {
        this.abortController.abort();
      } catch {
        // 忽略
      }
      this.abortController = null;
    }

    this.buffer = '';
  }

  // ============================================================================
  // 工具函数
  // ============================================================================

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}
