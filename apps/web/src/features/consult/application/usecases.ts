/**
 * 模块: features/consult/application/usecases
 * 职责: 咨询面用例——建会话、列会话、水合、技能目录、发消息、取消与应急入口的编排与前置校验
 * 数据来源:
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 3.1/3.2/3.3/4.1/4.3/5 节
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 1 节（application 只做用例编排）
 *   - docs/项目结构设计.md: MUST — 第 9 节（application 无框架、无 HTTP 依赖）
 * 边界:
 *   - 依赖: application/ports、domain
 *   - 被依赖: features/consult 的 viewModel
 * 禁止行为:
 *   - 禁止在用例里持有 UI 状态（无状态类，每次调用新建；FE-01）
 *   - 禁止跳过前置校验直接调用端口（FE-04 / 质量地板）
 *   - 禁止把端口异常改写为成功（失败必须是失败）
 */

import type {
  CreateSessionResponse,
  EmergencyRequest,
  EmergencyResponse,
  ListMessagesResponse,
  ListSessionsResponse,
  PostMessageRequest,
  PostMessageResponse,
} from '../../../shared/types/consult';
import { validateEmergencyItems } from '../domain/emergency';
import type { AnswerSubmission } from '../domain/questionBatch';
import type { SkillSummary } from '../domain/types';
import type { ConsultPort, CreateSessionInput, ListSessionsInput } from './ports';

/** 会话列表的默认与上限页大小（契约第 3.2 节：默认 20、上限 50）。 */
export const DEFAULT_SESSION_PAGE_SIZE = 20;
export const MAX_SESSION_PAGE_SIZE = 50;

/** 用例的前置校验失败（载荷不合法）；与端口失败（网络/状态码）区分开。 */
export class ConsultRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ConsultRequestError';
  }
}

/**
 * 前端生成的幂等键；同一会话内重复提交同一键值不会二次追加使用者消息（契约第 2 节）。
 *
 * ⚠️ 不能直接用 `crypto.randomUUID()`（2026-10-01 真机抓到的缺陷）。
 *
 * `crypto.randomUUID` 是 secure context 专有 API：只在 HTTPS（或 localhost）
 * 下存在，明文 HTTP 下它是 `undefined`。直接调用会抛
 * `TypeError: crypto.randomUUID is not a function`。
 *
 * 实测证据（真实浏览器，`http://campfire.wenran.me`）：
 *     window.isSecureContext       = false
 *     typeof crypto.randomUUID     = "undefined"
 *     typeof crypto.getRandomValues = "function"
 *     crypto.randomUUID()          -> TypeError
 *
 * 症状之所以难查：异常发生在发请求之前，因此服务端日志与浏览器网络面板里
 * 什么都看不到，界面上只出现一条笼统的「出现了未预期的错误」；而同一份代码在
 * 本地 `localhost` 开发时又完全正常（localhost 属 secure context）——
 * 典型的「只在生产暴露」。
 *
 * 兜底用 `crypto.getRandomValues`（在非安全上下文也可用，已实测）自行拼 UUIDv4。
 * 不降级成 `Math.random`：那会让幂等键的随机性变弱——幂等键碰撞会导致
 * 「两条不同的消息被当成同一条」，是数据正确性问题，而不只是概率问题。
 */
export function newClientMessageId(): string {
  const webCrypto = globalThis.crypto;
  if (typeof webCrypto?.randomUUID === 'function') {
    return webCrypto.randomUUID();
  }
  // 按 RFC 4122 的 v4 布局填充：第 7 字节高 4 位固定 0100（版本 4），
  // 第 9 字节高 2 位固定 10（变体）。
  // 用位掩码赋值而不是 `bytes[6]! &= ...`：`noUncheckedIndexedAccess` 下下标访问
  // 的静态类型含 undefined，而 oxlint 禁止非空断言（`!`）。先读进局部变量再写回，
  // 既避开断言，也不依赖「索引一定在界内」的隐含假设。
  const bytes = new Uint8Array(16);
  webCrypto.getRandomValues(bytes);
  const versionByte = bytes[6] ?? 0;
  const variantByte = bytes[8] ?? 0;
  bytes[6] = (versionByte & 0x0f) | 0x40;
  bytes[8] = (variantByte & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * 建会话（日常入口）。
 *
 * @throws ConsultRequestError 支持对象 id 为空串
 * @throws ConsultError 端口失败（会话存储不可用等）
 */
export class CreateSessionUseCase {
  constructor(private readonly consult: ConsultPort) {}

  /**
   * 创建一个新会话。
   *
   * 前置: input.support_object_id 若提供则非空
   * 后置: 返回服务端的 session_id、绑定对象与引导待注入标记
   * 异常: ConsultRequestError（空对象 id）、端口异常（HTTP 失败）
   */
  async execute(input: CreateSessionInput = {}): Promise<CreateSessionResponse> {
    const id = input.support_object_id;
    if (id !== undefined && id.trim() === '') {
      throw new ConsultRequestError('支持对象 id 不能为空串');
    }
    return this.consult.createSession(input);
  }
}

/**
 * 跳过一次性引导（契约第 6 节）。
 *
 * 前置: sessionId 非空
 * 后置: 服务端把该账号的引导状态写成 `skipped`，此后不再注入引导
 * 异常: ConsultRequestError（空 id）、ConsultError（端口失败——失败**不得**被当成已跳过）
 */
export class SkipOnboardingUseCase {
  constructor(private readonly consult: ConsultPort) {}

  async execute(sessionId: string): Promise<void> {
    if (sessionId.trim() === '') throw new ConsultRequestError('会话 id 不能为空串');
    await this.consult.skipOnboarding(sessionId);
  }
}

/**
 * 会话列表（分页）。
 *
 * @throws ConsultRequestError 每页条数越界或游标为空串
 * @throws ConsultError 端口失败（401/404/503 等）
 */
export class ListSessionsUseCase {
  constructor(private readonly consult: ConsultPort) {}

  /**
   * 拉取一页会话。
   *
   * 前置: limit 省略或为 1..50 的整数；cursor 省略或非空串
   * 后置: 返回该页 items 与下一页游标
   * 异常: ConsultRequestError（越界页码/空游标）、端口异常
   */
  async execute(input: ListSessionsInput = {}): Promise<ListSessionsResponse> {
    const limit = input.limit ?? DEFAULT_SESSION_PAGE_SIZE;
    if (!Number.isInteger(limit) || limit < 1 || limit > MAX_SESSION_PAGE_SIZE) {
      throw new ConsultRequestError(`每页条数须为 1..${MAX_SESSION_PAGE_SIZE}，收到 ${String(limit)}`);
    }
    const cursor = input.cursor ?? null;
    if (cursor !== null && cursor === '') {
      throw new ConsultRequestError('分页游标不能为空串（缺省用 null 表示首页）');
    }
    return this.consult.listSessions({ cursor, limit });
  }
}

/**
 * 历史水合。
 *
 * @throws ConsultRequestError 会话 id 为空
 * @throws ConsultError 端口失败（失败必须显式呈现，不得当作空对话）
 */
export class LoadHistoryUseCase {
  constructor(private readonly consult: ConsultPort) {}

  /**
   * 拉取一条会话的全部消息。
   *
   * 前置: sessionId 非空
   * 后置: 返回按真源顺序排列的消息（形状转换归 viewModel/history）
   * 异常: ConsultRequestError（空 id）、端口异常——失败不得呈现为空对话（技术设计第 4.4 节）
   */
  async execute(sessionId: string): Promise<ListMessagesResponse> {
    if (sessionId.trim() === '') throw new ConsultRequestError('会话 id 不能为空');
    return this.consult.loadHistory(sessionId);
  }
}

/** 技能目录。 */
export class ListSkillsUseCase {
  constructor(private readonly consult: ConsultPort) {}

  /**
   * 取技能选择器的可选项。
   *
   * 前置: 无
   * 后置: 返回技能目录（顺序即 chip 顺序）
   * 异常: 端口异常（调用方降级为仅「自动」而不是编造目录）
   */
  async execute(): Promise<SkillSummary[]> {
    return this.consult.listSkills();
  }
}

/** 发消息入参：普通消息与整组回答二选一。 */
export interface SendConsultMessageInput {
  sessionId: string;
  /** 普通消息文本。 */
  content?: string;
  /**
   * 一组提问的提交件（answers + 产出它的那一组的 batchId）。
   *
   * ★ 为什么是一个对象而不是并排的 `answers` + `batchId` 两个字段（本包关键决策）：
   * 两个独立字段让「A 组的 answers + B 组的 batchId」成为可表达的状态，而传错组的
   * `batch_id` 比不传更坏——它会触发服务端的排他层，把本该判 `True` 的组挡掉。
   * `domain/questionBatch` 的 `AnswerSubmission` 把两者绑在同一个对象上，本用例是它的下游。
   */
  submission?: AnswerSubmission;
  /** 技能选择（发送即消费；null = 自动匹配）。 */
  skill?: string | null;
  /** 幂等键生成器；默认 newClientMessageId（测试注入固定值）。 */
  newId?: () => string;
}

/**
 * 发消息。
 *
 * @throws ConsultRequestError 会话 id 为空、内容与回答同时为空或同时有值
 * @throws ConsultError 端口失败（409 session_busy、422 载荷不合法等）
 */
export class SendMessageUseCase {
  constructor(private readonly consult: ConsultPort) {}

  /**
   * 发送一条使用者消息并拿到 run_id。
   *
   * 前置: sessionId 非空；content 与 answers 恰有一个有效（content 非空白，或 answers 非空数组）
   * 后置: 返回受理后的 run_id 与会话 id（202 只表示已受理，落库由服务端负责）
   * 异常: ConsultRequestError（两个都空、都填、或空白内容）、端口异常（409 session_busy 等）
   */
  async execute(input: SendConsultMessageInput): Promise<PostMessageResponse> {
    if (input.sessionId.trim() === '') throw new ConsultRequestError('会话 id 不能为空');

    const content = input.content?.trim() ?? '';
    const answers = input.submission?.answers ?? [];
    if (content === '' && answers.length === 0) {
      throw new ConsultRequestError('消息内容与回答不能同时为空');
    }
    if (content !== '' && answers.length > 0) {
      throw new ConsultRequestError('普通消息与一组回答只能提交其一');
    }

    const clientMessageId = (input.newId ?? newClientMessageId)();
    // 本组批次标识（前端内部名 batchId）；空串/纯空白按「没有」处理，见下方序列化处说明。
    const batchId = input.submission?.batchId.trim() ?? '';
    const payload: PostMessageRequest =
      answers.length > 0
        ? {
            answers,
            // ★ 序列化边界：内部名 `batchId` → 出网键名 `batch_id`。只此一处做这个转换
            // （契约第 4.1 节的键名逐字是 snake_case；前端惯用 camelCase，散落转换必然漂移）。
            //
            // 为什么用条件展开而不是写 `batch_id: input.submission?.batchId`：
            // 后者在缺失时会发一个 `"batch_id": undefined` 的键（`JSON.stringify` 会把它整个
            // 丢掉，但内存里那个键仍在，测试里读到的是「键存在且值为 undefined」）。而契约说的是
            // 「字段可选」= 不带该字段。条件展开保证缺失时这个键根本不存在，与旧客户端逐字同形。
            //
            // ★ 为什么空串也走「不带该字段」而不是原样发 `""`（本包裁决 2 的落点）：
            // `batch_id` 是可选字段 ⇒ 前端不得因它缺失而阻断提交。而服务端对出现但为空的
            // `batch_id` 按非法入参处理（T39 校验点：空串按非法处理）⇒ 发 `""` 会被 422 挡回，
            // 那正好就是「因它缺失而阻断提交」这一被禁止的后果。缺省与空串在语义上是同一件事
            // （「我说不出是哪一组」），因此都折成「不带该字段」，由服务端退回窗口判定。
            ...(batchId === '' ? {} : { batch_id: batchId }),
            skill: input.skill ?? null,
            client_message_id: clientMessageId,
          }
        : { content, skill: input.skill ?? null, client_message_id: clientMessageId };

    return this.consult.sendMessage(input.sessionId, payload);
  }
}

/**
 * 取消运行。
 *
 * @throws ConsultRequestError 运行 id 为空
 * @throws ConsultError 端口失败（已终结的运行由服务端返回 409）
 */
export class CancelRunUseCase {
  constructor(private readonly consult: ConsultPort) {}

  /**
   * 请求服务端取消一条运行。
   *
   * 前置: runId 非空
   * 后置: 服务端已受理取消（202）；已终结的运行由服务端返回 409，由调用方按「已经停了」处置
   * 异常: ConsultRequestError（空 id）、端口异常
   */
  async execute(runId: string): Promise<void> {
    if (runId.trim() === '') throw new ConsultRequestError('运行 id 不能为空');
    await this.consult.cancelRun(runId);
  }
}

/** 应急入口入参。 */
export interface EmergencyStartInput {
  items: EmergencyRequest['items'];
  support_object_id?: string;
}

/** 应急入口。 */
export class EmergencyStartUseCase {
  constructor(private readonly consult: ConsultPort) {}

  /**
   * 提交八项现场采集并启动应急运行。
   *
   * 前置: items 恰为八项、key 在词表内；skipped 项不带值，非 skipped 项带值
   * 后置: 返回 session_id 与 run_id（一次调用完成建会话、落首条消息与启动运行）
   * 异常: Error（validateEmergencyItems 的越界/缺值）、端口异常（422 等）
   */
  async execute(input: EmergencyStartInput): Promise<EmergencyResponse> {
    validateEmergencyItems(input.items);
    const payload: EmergencyRequest =
      input.support_object_id === undefined
        ? { items: input.items }
        : { support_object_id: input.support_object_id, items: input.items };
    return this.consult.emergencyStart(payload);
  }
}
