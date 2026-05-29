/**
 * CSLT-08 SSE 流解析器 —— SseStreamParser 类（小程序 enableChunked 版）。
 *
 * 职责：
 * - 通过 Taro.request({ enableChunked: true }) 连接 SSE 端点
 * - 监听 onChunkReceived 回调接收 chunk（responseType: 'text'，直接拿到字符串）
 * - 手动解析 SSE 协议（支持 \r\n\r\n 和 \n\n 双换行分隔）
 * - 跨 chunk 边界事件拼接
 * - 心跳监控（15s 无事件判定僵死）
 * - 指数退避重连（1s/2s/5s，3 次上限）
 *
 * 设计依据：CSLT-08 落地规范 §1.7 步骤 4、§1.9 异常 3
 * 兼容性：微信小程序基础库 2.18.0+（支持 enableChunked / onChunkReceived）
 */

import Taro from '@tarojs/taro';
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

  /** Taro 请求任务（用于 abort 和 onChunkReceived） */
  private task: Taro.RequestTask<unknown> | null = null;
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
   * 使用 Taro.request({ enableChunked: true }) 获取 chunk 数据。
   *
   * @param url - SSE 端点 URL
   * @param headers - 额外请求头（如 Last-Event-Id）
   * @returns Promise<void> 连接关闭时 resolve，异常时内部自动重连
   */
  async connect(url: string, headers?: Record<string, string>): Promise<void> {
    this.cleanup();

    this.isActive = true;
    this.reconnectAttempt = 0;
    this.lastEventTime = Date.now();

    try {
      await this._doConnect(url, headers);
    } catch {
      // 首次连接失败 → 触发重连
      if (this.isActive && !this.isReconnecting) {
        await this.attemptReconnect(url, headers);
      }
    }
  }

  /**
   * 执行一次 SSE 连接。
   * 内部通过 Promise 包装 Taro.request，解耦回调与 async/await。
   */
  private _doConnect(url: string, headers?: Record<string, string>): Promise<void> {
    return new Promise((resolve, reject) => {
      this.startConnectTimer();

      const task = Taro.request({
        url,
        method: 'GET',
        header: {
          Accept: 'text/event-stream',
          'Cache-Control': 'no-cache',
          ...(this.lastEventId ? { 'Last-Event-Id': this.lastEventId } : {}),
          ...headers,
        },
        responseType: 'text',
        enableChunked: true,
        success: (res) => {
          this.clearConnectTimer();
          this.stopAllMonitors();

          if (!this.isActive) {
            resolve();
            return;
          }

          if (res.statusCode && (res.statusCode < 200 || res.statusCode >= 300)) {
            this.callbacks.onError?.({
              error_code: 'GENERATION_FAILED',
              detail: `SSE 连接失败: HTTP ${res.statusCode}`,
            });
            reject(new Error(`HTTP ${res.statusCode}`));
            return;
          }

          resolve();
        },
        fail: (err) => {
          this.clearConnectTimer();
          this.stopAllMonitors();

          if (!this.isActive) {
            resolve();
            return;
          }

          reject(err);
        },
      }) as unknown as Taro.RequestTask<unknown>;

      this.task = task;

      // ---- 注册 onChunkReceived（微信小程序 2.18.0+）----
      if (task.onChunkReceived) {
        task.onChunkReceived((res) => {
          this.clearConnectTimer();

          // responseType: 'text' 下微信小程序直接返回字符串
          const chunk = typeof res.data === 'string' ? res.data : '';
          if (chunk) {
            this.processChunk(chunk);
          }

          this.lastEventTime = Date.now();
          this.resetHeartbeatMonitor();
          this.resetNoDataMonitor();
        });
      }

      this.startHeartbeatMonitor();
      this.startNoDataMonitor();
    });
  }

  // ============================================================================
  // disconnect —— 主动断开连接
  // ============================================================================

  /**
   * 主动断开 SSE 连接。
   * 清理所有定时器、中止 Taro 请求。
   */
  disconnect(): void {
    this.isActive = false;
    this.isReconnecting = false;
    if (this.task) {
      try {
        this.task.abort();
      } catch {
        // 忽略
      }
      this.task = null;
    }
    this.cleanup();
  }

  // ============================================================================
  // Chunk 处理 —— SSE 协议解析
  // ============================================================================

  /**
   * 处理每个读取到的文本 chunk。
   * 支持 \r\n\r\n 和 \n\n 作为事件分隔符。
   * 处理跨 chunk 边界的事件拼接。
   */
  private processChunk(chunk: string): void {
    // 追加到缓冲区
    this.buffer += chunk;

    // 尝试从缓冲区中提取完整事件
    let separatorIndex: number;
    while ((separatorIndex = this.findEventSeparator(this.buffer)) !== -1) {
      // 提取完整事件文本（到第一个分隔符之前）
      const eventText = this.buffer.substring(0, separatorIndex);

      // 移除已处理部分（包括分隔符）
      this.buffer = this.buffer.substring(
        separatorIndex + this.getSeparatorLength(this.buffer, separatorIndex),
      );

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
        } catch (err: unknown) {
          console.warn('[sse] chunk dispatch failed:', err instanceof Error ? err.message : String(err));
        }
        break;
      }

      case 'done': {
        try {
          const payload: DoneEventPayload = JSON.parse(sseEvent.data);
          this.callbacks.onDone?.(payload);
        } catch (err: unknown) {
          console.warn('[sse] done dispatch failed:', err instanceof Error ? err.message : String(err));
          this.callbacks.onDone?.({ finish_reason: 'COMPLETE' });
        }
        this.isActive = false;
        break;
      }

      case 'error': {
        try {
          const payload: ErrorEventPayload = JSON.parse(sseEvent.data);
          this.callbacks.onError?.(payload);
        } catch (err: unknown) {
          console.warn('[sse] error dispatch failed:', err instanceof Error ? err.message : String(err));
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

      if (!this.isActive) {
        this.isReconnecting = false;
        return;
      }

      try {
        // 关闭旧 task
        if (this.task) {
          try {
            this.task.abort();
          } catch {
            // 忽略
          }
          this.task = null;
        }

        // 重新连接
        await this._doConnect(url, headers);

        // 重连成功且流正常结束
        this.isReconnecting = false;
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
        // 心跳超时，不触发外部回调，等待无数据超时或连接断开
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
   * 超时后 task.abort() → Taro.request fail 回调 → Promise reject。
   */
  private startConnectTimer(): void {
    this.clearConnectTimer();
    this.connectTimer = setTimeout(() => {
      if (this.task) {
        try {
          this.task.abort();
        } catch {
          // 忽略
        }
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
   * 清理所有资源：中止 Taro 请求、清除定时器、清空缓冲区。
   */
  private cleanup(): void {
    this.clearConnectTimer();
    this.stopAllMonitors();

    if (this.task) {
      try {
        this.task.abort();
      } catch {
        // 忽略
      }
      this.task = null;
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
