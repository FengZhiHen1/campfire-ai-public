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
  QuestionAnswer,
} from '../../../shared/types/consult';
import { validateEmergencyItems } from '../domain/emergency';
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

/** 前端生成的幂等键；同一会话内重复提交同一键值不会二次追加使用者消息（契约第 2 节）。 */
export function newClientMessageId(): string {
  return globalThis.crypto.randomUUID();
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
  /** 一组提问的回答（整组一次提交）。 */
  answers?: QuestionAnswer[];
  /** 技能选择（发送即消费；null = 自动匹配）。 */
  skill?: string | null;
  /** 幂等键生成器；默认 crypto.randomUUID（测试注入固定值）。 */
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
    const answers = input.answers ?? [];
    if (content === '' && answers.length === 0) {
      throw new ConsultRequestError('消息内容与回答不能同时为空');
    }
    if (content !== '' && answers.length > 0) {
      throw new ConsultRequestError('普通消息与一组回答只能提交其一');
    }

    const clientMessageId = (input.newId ?? newClientMessageId)();
    const payload: PostMessageRequest =
      answers.length > 0
        ? { answers, skill: input.skill ?? null, client_message_id: clientMessageId }
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
