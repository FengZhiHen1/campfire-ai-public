/**
 * 模块: infrastructure/sse
 * 职责: 裸 SSE 传输——按契约把一条运行的事件流解成 RunEvent 异步流（解析、续传、重连）
 * 数据来源:
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 2 节（不得用 EventSource）、
 *     第 4.2 节（每条事件三行 id/event/data、id 即续传依据、`: ping` 心跳、终态后关闭）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 3 节（事件顺序防御）、
 *     第 7 节（带 Last-Event-ID 重连，指数退避上限 3 次，409 改走水合）
 * 边界:
 *   - 依赖: shared/types/sse（线格式类型）、infrastructure/http/client（HttpError）
 *   - 被依赖: features/consult 的端口实现
 * 禁止行为:
 *   - 禁止用 EventSource（无法携带 anti-CSRF 自定义头，契约第 2 节）
 *   - 禁止在诊断信息里复述事件载荷正文或任何凭据（只报原因与字段名）
 *   - 禁止在解析失败时静默丢弃（每条丢弃都经 onDiagnostic 报出，技术设计不变量 3）
 */

import type { RunEvent, RunEventName, SseFrame } from '../shared/types/sse';
import { HttpError, withApiPrefix } from './http/client';

/** 事件名全集；用于拒绝契约外的 event 名（改名等于改契约，不得静默放行）。 */
const RUN_EVENT_NAMES: readonly RunEventName[] = [
  'run_started',
  'text_delta',
  'reasoning_delta',
  'progress',
  'tool_call_started',
  'tool_call_finished',
  'citation',
  'candidate',
  'question',
  'action_card',
  'run_finished',
  'run_failed',
];

/** 终态事件：到达即结束本次订阅（契约第 4.2 节结束行）。 */
const TERMINAL_EVENTS: ReadonlySet<string> = new Set<string>(['run_finished', 'run_failed']);

/** 指数退避的等待上限；重连次数另有上限，两层上界都显式（CORE-11）。 */
const MAX_BACKOFF_MS = 4000;

/** 行结束符：兼容 CRLF / LF / 单独 CR（SSE 规范允许三者）。 */
const LINE_END = /\r\n|\n|\r/;

/** 默认重连次数上限（技术设计第 7 节：指数退避，上限 3 次）。 */
export const DEFAULT_MAX_RECONNECTS = 3;

/** 默认退避基数：第 n 次重连等待 base * 2^(n-1)。 */
export const DEFAULT_BACKOFF_BASE_MS = 500;

/** 丢弃一帧或降级连接的原因。每条都有对应诊断，不静默。 */
export type SseDiagnosticReason =
  | 'missing-data'
  | 'invalid-json'
  | 'invalid-payload'
  | 'unknown-event'
  | 'event-mismatch'
  | 'invalid-id'
  | 'unknown-field'
  | 'truncated-frame'
  | 'reconnect'
  | 'reconnect-exhausted';

/** 一条解析/连接诊断。detail 只含原因与字段名，不含载荷正文。 */
export interface SseDiagnostic {
  reason: SseDiagnosticReason;
  detail: string;
  /** `reconnect` 专用：第几次重连（1 起），供上层显示「正在重连」。 */
  attempt?: number;
}

/** 诊断回调；调用方决定落到哪里（本模块不自己打日志）。 */
export type SseDiagnosticSink = (diagnostic: SseDiagnostic) => void;

/** 解析器选项。 */
export interface SseParserOptions {
  onDiagnostic?: SseDiagnosticSink;
}

/**
 * 运行事件流已不可续传：缓冲失效或运行元数据不在了，调用方须改走历史水合
 * （契约第 4.2 节续传行）。
 *
 * 两种状态码归到同一个异常是刻意的：
 * - **409 `run_not_resumable`**：服务端自己判定缓冲失效、且没有可续内容；
 * - **404**：`run:<id>:meta` 不在了（到期，或这条运行从来不属于当前账号）。服务端此时
 *   无法回放，客户端继续重连也不会成功——**但它的答案已经在会话真源里**，所以正确的
 *   处置与 409 相同：改成读历史，而不是给使用者一张「找不到这条内容」的死胡同卡片。
 *   2026-10-28 实测：真实走查中流订阅偶发 404，前端当时把它翻成不可重试的致命错误卡，
 *   使用者既看不到回答也没有重试入口（`apps/web/src/features/consult/domain/errors.ts`）。
 */
export class RunNotResumableError extends Error {
  constructor(readonly reason: 'not-resumable-409' | 'run-meta-gone-404' = 'not-resumable-409') {
    super(
      reason === 'run-meta-gone-404'
        ? '运行元数据已不在（404），本次订阅无法续传'
        : '运行事件流已不可续传（409 run_not_resumable）',
    );
    this.name = 'RunNotResumableError';
  }
}

/** 重连次数耗尽：订阅没能恢复（契约第 8 节「重连耗尽」行）。 */
export class RunStreamExhaustedError extends Error {
  constructor(
    readonly attempts: number,
    cause: unknown,
  ) {
    super(`事件流重连 ${attempts} 次仍未恢复`, { cause });
    this.name = 'RunStreamExhaustedError';
  }
}

/** 响应没有可读流（服务端违约）：无法解析，直接失败而不是空转。 */
export class SseTransportError extends Error {
  constructor(detail: string) {
    super(detail);
    this.name = 'SseTransportError';
  }
}

/** 订阅选项。 */
export interface SubscribeRunEventsOptions {
  /** 运行 id（GET /consult/runs/{run_id}/stream）。 */
  runId: string;
  /** 取消信号；触发即停止订阅（取消不发终态事件，契约第 4.3 节）。 */
  signal: AbortSignal;
  /** 续传起点：上一次已收到的事件序号。 */
  lastEventId?: number;
  /** fetch 实现；测试注入 mock 流。 */
  fetchImpl?: typeof fetch;
  onDiagnostic?: SseDiagnosticSink;
  /** 重连次数上限；默认 DEFAULT_MAX_RECONNECTS。 */
  maxReconnects?: number;
  /** 退避基数（毫秒）；默认 DEFAULT_BACKOFF_BASE_MS。 */
  backoffBaseMs?: number;
  /** 等待实现；测试注入以避免真实计时。 */
  wait?: (ms: number, signal: AbortSignal) => Promise<void>;
}

/**
 * 一次订阅使用的默认等待。
 *
 * 为什么自己写而不是 setTimeout 裸等：abort 后必须立刻结束等待，否则取消一次运行后
 * 退避计时器仍会把它拖住（最长 4 秒），页面上表现为「停止按钮点了没反应」。
 */
function defaultWait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise<void>((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const finish = (): void => {
      clearTimeout(timer);
      signal.removeEventListener('abort', finish);
      resolve();
    };
    const timer = setTimeout(finish, ms);
    signal.addEventListener('abort', finish, { once: true });
  });
}

/** 第 attempt 次重连的等待时长：base * 2^(attempt-1)，封顶 MAX_BACKOFF_MS。 */
export function backoffDelay(attempt: number, baseMs: number = DEFAULT_BACKOFF_BASE_MS): number {
  const safeAttempt = Math.max(1, Math.trunc(attempt));
  return Math.min(baseMs * 2 ** (safeAttempt - 1), MAX_BACKOFF_MS);
}

/** 一帧的解析中间态（可能跨多个 chunk 拼成）。 */
interface PendingFrame {
  id?: string;
  event?: string;
  data: string[];
}

/**
 * 把读到的字节解码成文本块。
 *
 * 用 TextDecoder 的流式模式：一个多字节字符可能被切在两个 chunk 之间，
 * 非流式解码会把它解成替换字符，正文出现乱码。
 */
async function* decodeChunks(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
): AsyncGenerator<string, void> {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8');
  const onAbort = (): void => {
    // 取消时主动断开读取：否则 for-await 会一直挂在 read() 上，直到服务端下次推送。
    void reader.cancel().catch(() => undefined);
  };
  signal.addEventListener('abort', onAbort, { once: true });
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) return;
      if (value.length > 0) yield decoder.decode(value, { stream: true });
    }
  } finally {
    signal.removeEventListener('abort', onAbort);
    void reader.cancel().catch(() => undefined);
  }
}

/**
 * 解析 SSE 帧流。
 *
 * 前置: chunks 是同一响应的文本块序列（按到达顺序，可任意切分）
 * 后置: 逐个 yield 合法 SseFrame；畸形帧被丢弃并经 onDiagnostic 报出原因
 * 异常: 不抛出——解析失败是数据问题，不是传输问题；连接层的失败由上层处置
 *
 * id 的行为按 SSE 规范：没有 id 行（或 id 非法）时沿用上一帧的 lastEventId，
 * 因为 id 是续传的唯一依据，凭空写 0 会让重连从头发起、二次追加使用者消息。
 */
export async function* parseSseFrames(
  chunks: AsyncIterable<string>,
  options: SseParserOptions = {},
): AsyncGenerator<SseFrame, void> {
  const report = options.onDiagnostic;
  let buffer = '';
  let pending: PendingFrame | null = null;
  let lastEventId = 0;

  const current = (): PendingFrame => {
    pending ??= { data: [] };
    return pending;
  };

  /**
   * 读当前半帧。
   *
   * 为什么用一个函数读：`pending` 只在闭包里被赋值，控制流分析在循环之后会把它窄化成
   * 初始值 null，于是「流末尾还有半帧」这条分支被推断成 never 而失去判别力。
   */
  const readPending = (): PendingFrame | null => pending;

  /** 处理一帧完整数据；返回要 yield 的帧（无则 null）。 */
  const flushFrame = (frame: PendingFrame): SseFrame | null => {
    // id 先解析：即使这一帧因载荷问题被丢弃，续传起点也应前进到这个序号——
    // 否则重连会把已经收到过的帧再放一遍。
    if (frame.id !== undefined) {
      const idText = frame.id.trim();
      // 契约的 id 是「本次运行内单调递增的序号」；非数字（代理插的 UUID、空值）不能当序号用，
      // 沿用上一帧的 id 并留痕——写成 0 会让重连从头发起。
      if (/^\d+$/.test(idText)) {
        lastEventId = Number.parseInt(idText, 10);
      } else {
        report?.({ reason: 'invalid-id', detail: `id=${frame.id}` });
      }
    }

    if (frame.data.length === 0) {
      report?.({ reason: 'missing-data', detail: `event=${frame.event ?? '(缺失)'}` });
      return null;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(frame.data.join('\n'));
    } catch {
      report?.({ reason: 'invalid-json', detail: `event=${frame.event ?? '(缺失)'}` });
      return null;
    }

    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      report?.({ reason: 'invalid-payload', detail: `event=${frame.event ?? '(缺失)'}` });
      return null;
    }

    const payloadType = (parsed as { type?: unknown }).type;
    if (typeof payloadType !== 'string' || !(RUN_EVENT_NAMES as readonly string[]).includes(payloadType)) {
      // 契约外的事件名一律不猜：改名等于改契约，静默放行会让载荷以错误形状进入视图。
      report?.({ reason: 'unknown-event', detail: `type=${String(payloadType)}` });
      return null;
    }

    // event 行与 data.type 恒等（契约第 4.2 节）。不一致说明两端对不齐：
    // 以 event 行分派为依据，载荷与它不符时丢弃整帧而不是猜一个解释。
    if (frame.event !== undefined && frame.event !== payloadType) {
      report?.({ reason: 'event-mismatch', detail: `event=${frame.event} data.type=${payloadType}` });
      return null;
    }

    return { id: lastEventId, event: payloadType as RunEventName, data: parsed as RunEvent };
  };

  /** 逐行喂入；返回本行触发的 complete frame（无则 null）。 */
  const consumeLine = (line: string): PendingFrame | null => {
    if (line === '') {
      const frame = pending;
      pending = null;
      return frame;
    }
    // `: ping` 心跳与其它注释行不承载语义（契约第 4.2 节心跳行）。
    if (line.startsWith(':')) return null;

    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    const rawValue = colon === -1 ? '' : line.slice(colon + 1);
    const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue;

    switch (field) {
      case 'id':
        current().id = value;
        return null;
      case 'event':
        current().event = value;
        return null;
      case 'data':
        current().data.push(value);
        return null;
      case 'retry':
        // SSE 标准字段，服务端未使用（契约只约定 `: ping` 心跳）；退避策略由前端拥有，
        // 不接受服务端建议，因此这里不改变任何行为也不报诊断、不新建半帧。
        return null;
      default:
        report?.({ reason: 'unknown-field', detail: `field=${field}` });
        return null;
    }
  };

  const drain = function* (flush: boolean): Generator<SseFrame, void> {
    while (true) {
      LINE_END.lastIndex = 0;
      const match = LINE_END.exec(buffer);
      if (match === null) {
        // 结尾的单 \r 可能是被切开的 CRLF 前半：流未结束时等下一个 chunk；
        // 流已结束时它是帧结束符（空行），按空行处理以冲刷已收到的帧。
        if (!flush || buffer === '') break;
        const line = buffer === '\r' ? '' : buffer;
        buffer = '';
        const frame = consumeLine(line);
        if (frame !== null) {
          const parsedFrame = flushFrame(frame);
          if (parsedFrame !== null) yield parsedFrame;
        }
        break;
      }
      const line = buffer.slice(0, match.index);
      buffer = buffer.slice(match.index + match[0].length);
      const frame = consumeLine(line);
      if (frame === null) continue;
      const parsedFrame = flushFrame(frame);
      if (parsedFrame !== null) yield parsedFrame;
    }
  };

  for await (const chunk of chunks) {
    buffer += chunk;
    yield* drain(false);
  }

  // 流结束：SSE 规范丢弃未以空行收尾的半帧，但丢弃要留痕（不当成「读完了」）。
  const leftover = readPending();
  if (leftover !== null && leftover.data.length > 0) {
    report?.({ reason: 'truncated-frame', detail: `event=${leftover.event ?? '(缺失)'}` });
  }
  yield* drain(true);
}

/** 请求一条运行的事件流并按帧产出；不含重连（重连在 subscribeRunEvents 里）。 */
async function* requestRunFrames(
  fetchImpl: typeof fetch,
  options: SubscribeRunEventsOptions,
  lastEventId: number | undefined,
): AsyncGenerator<SseFrame, void> {
  const headers: Record<string, string> = { Accept: 'text/event-stream' };
  if (lastEventId !== undefined) headers['Last-Event-ID'] = String(lastEventId);

  // 走 withApiPrefix 而不是自己拼 `/api`：前缀规则在 client.ts 里只有一份，
  // 且本模块继续只写业务路径（`/consult/runs/...`），与后端 router 的声明一致。
  const response = await fetchImpl(withApiPrefix(`/consult/runs/${encodeURIComponent(options.runId)}/stream`), {
    method: 'GET',
    headers,
    // 会话凭据经 httpOnly cookie 自动携带；anti-CSRF 头由 supertokens-web-js 的 fetch 包装注入
    // （契约第 2 节），本模块不重复实现，也不用 EventSource（它无法带自定义头）。
    credentials: 'same-origin',
    signal: options.signal,
  });

  if (response.status === 409) {
    // 契约第 4.2 节：缓冲失效或已无可续内容。重连不会成功，调用方改走历史水合。
    throw new RunNotResumableError('not-resumable-409');
  }
  if (response.status === 404) {
    // 见 `RunNotResumableError` 的说明：元数据不在了，重连不会成功；答案已在会话真源里，
    // 因此与 409 同样处置（改走历史水合），而不是让上层翻成不可重试的致命错误。
    throw new RunNotResumableError('run-meta-gone-404');
  }
  if (response.status === 401) {
    throw new HttpError(401, '会话已失效');
  }
  if (!response.ok) {
    throw new HttpError(response.status, response.statusText);
  }
  if (response.body === null) {
    throw new SseTransportError('事件流响应没有可读流');
  }

  yield* parseSseFrames(decodeChunks(response.body, options.signal), { onDiagnostic: options.onDiagnostic });
}

/**
 * 订阅一条运行的事件流（含断线续传）。
 *
 * 前置: runId 非空；signal 未中止
 * 后置: 逐条 yield 该运行的事件；收到终态事件后正常结束（服务端随后关闭流）
 * 异常:
 *   - RunNotResumableError：409 / 404，调用方改走历史水合
 *   - HttpError：401/422/503 等确定性失败，不重连（404 已归入不可续传，见上）
 *   - RunStreamExhaustedError：网络类中断且重连次数耗尽（契约第 8 节）
 *
 * 取消（signal 中止）不是异常：直接结束生成器，不发终态（契约第 4.3 节）。
 */
export async function* subscribeRunEvents(
  options: SubscribeRunEventsOptions,
): AsyncGenerator<RunEvent, void> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const maxReconnects = Math.max(0, Math.trunc(options.maxReconnects ?? DEFAULT_MAX_RECONNECTS));
  const baseMs = options.backoffBaseMs ?? DEFAULT_BACKOFF_BASE_MS;
  const wait = options.wait ?? defaultWait;

  let attempt = 0;
  let lastEventId = options.lastEventId;
  let lastError: unknown = null;

  while (!options.signal.aborted) {
    try {
      for await (const frame of requestRunFrames(fetchImpl, options, lastEventId)) {
        lastEventId = frame.id;
        yield frame.data;
        if (TERMINAL_EVENTS.has(frame.data.type)) {
          // 终态：本次订阅的终点（服务端随后关闭流）。不再重连。
          return;
        }
      }
      // 流被服务端关掉但没有终态：运行可能仍在继续（代理超时、连接被切）。
      // 按可恢复中断处理，走退避重连；不下「运行已结束」的结论。
      lastError = new SseTransportError('事件流在没有终态事件的情况下结束');
    } catch (error) {
      if (options.signal.aborted) return;
      if (error instanceof RunNotResumableError || error instanceof HttpError) throw error;
      lastError = error;
    }

    if (options.signal.aborted) return;

    if (attempt >= maxReconnects) {
      options.onDiagnostic?.({
        reason: 'reconnect-exhausted',
        detail: `attempts=${attempt}`,
      });
      throw new RunStreamExhaustedError(attempt, lastError);
    }

    attempt += 1;
    const delay = backoffDelay(attempt, baseMs);
    options.onDiagnostic?.({ reason: 'reconnect', detail: `attempt=${attempt} delayMs=${delay}`, attempt });
    await wait(delay, options.signal);
  }
}
