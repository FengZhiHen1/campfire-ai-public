/**
 * 模块: features/consult/viewModel/chatAdapter
 * 职责: assistant-ui 的 ChatModelAdapter 实现——SSE 两段式发送订阅与事件到 chunk 的纯映射
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 3 节（映射表与三条不变量）、
 *     第 6.2 节（卡片之后可继续输出，多 part 并存）、第 7 节（失败语义）
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 4.1 节（两段式）、第 4.3 节（取消）
 * 边界:
 *   - 依赖: features/consult/application（用例）、domain（part 契约与失败类型）
 *   - 被依赖: viewModel 的运行时装配 hook
 * 禁止行为:
 *   - 禁止把 reasoning 渲染成正文或把它当依据（DESIGN.md 反模式、技术设计 6.3 节）
 *   - 禁止解析正文猜结构（卡片与提问只认事件载荷）
 *   - 禁止在 run_finished 之后继续把事件写进消息（不变量 3：忽略并留一条诊断）
 */

import type { ChatModelAdapter, ChatModelRunResult, ThreadMessage } from '@assistant-ui/react';

import type { PostMessageResponse } from '../../../shared/types/consult';
import type { RunEvent } from '../../../shared/types/sse';
import type { ConsultPort, StreamNotice } from '../application/ports';
import { CancelRunUseCase, SendMessageUseCase } from '../application/usecases';
import { ConsultError, ConsultRunFailure } from '../domain/errors';
import type { AnswerSubmission } from '../domain/questionBatch';
import { createPartAccumulator } from './partAccumulator';
import type { ConnectionStatus } from '../domain/types';

/** 适配器依赖（由页面装配注入；测试用替身）。 */
export interface ConsultChatAdapterDeps {
  consult: ConsultPort;
  /** 当前对话 id。 */
  sessionId: string;
  /** 读待用技能选择（不改变状态）。 */
  peekPendingSkill(): string | null;
  /** 发送被受理后清空技能选择（发送即消费）。 */
  clearPendingSkill(): void;
  /** 读待发送的整组回答提交件（answers + 产出它那一组的 batchId；不改变状态）。 */
  peekPendingSubmission(): AnswerSubmission | null;
  /** 发送被受理后清空整组回答提交件。 */
  clearPendingSubmission(): void;
  /** 事件回流（会话级状态归 viewModel/store）。 */
  onEvent(event: RunEvent): void;
  /** 连接状态回流（重连期间状态条与输入区要变）。 */
  onConnection(connection: ConnectionStatus): void;
  /** 失败回流：错误卡与重试入口需要标题/说明/可否重试（呈现文案由 domain 决定）。 */
  onFailure(error: unknown): void;
  /**
   * 探查「已在服务端启动、等待订阅」的运行 id（应急入口：HTTP/SSE 契约第 5 节
   * 「一次调用完成建会话 → 落第一条消息 → 启动运行，前端拿 run_id 直接跳对话页订阅」）。
   * 只读，不消费：存在与否决定「要不要清过期交接」，认领与否由 consumeAttachIntent 决定。
   */
  peekAttachedRunId?(): string | null;
  /**
   * 认领本次运行的意图（由触发 startRun 的装配点声明，取走即消费）。
   *
   * 为什么不能用「本次有没有新输入」推断：应急会话的历史里，最后一条使用者消息**就是**那份
   * 八项采集，按输入推断会把它当成新消息再发一遍（把采集内容重复落进对话真源）。
   */
  consumeAttachIntent?(): boolean;
  /** 认领的这次运行已到终态（成功或失败）：清掉交接，避免后续装配重复订阅同一运行。 */
  clearAttachedRun?(): void;
  /**
   * 请求上层「改走历史水合」（契约第 4.2 节续传行、第 8 节重连耗尽）。
   *
   * 为什么由适配器发这个请求、而不是让错误卡自己带一个重试按钮：传输已经不可续，
   * 但**答案已经在会话真源里**（服务端把运行结果落了库）。这时唯一有意义的动作是重新读
   * 历史，而不是让使用者面对「找不到这条内容」却没有出口——2026-10-28 实测到的正是这一张卡。
   */
  onNeedsResync?(): void;
  /** 诊断（丢弃的事件、取消失败等，不静默吞）。 */
  onDiagnostic?(message: string): void;
  /** 幂等键生成器；测试注入固定值。 */
  newId?: () => string;
}

/** 从消息列表里取最后一条使用者消息的正文（普通消息路径）。 */
export function lastUserText(messages: readonly ThreadMessage[]): string {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message === undefined || message.role !== 'user') continue;
    const text = message.content
      .filter((part): part is { type: 'text'; text: string } => part.type === 'text')
      .map((part) => part.text)
      .join('');
    return text.trim();
  }
  return '';
}

/**
 * 创建咨询对话适配器。
 *
 * @param deps 端口与状态回流（见 ConsultChatAdapterDeps）
 * @returns 可作为 useLocalRuntime 的 chatModel 使用的适配器
 */
export function createConsultChatAdapter(deps: ConsultChatAdapterDeps): ChatModelAdapter {
  const sendUseCase = new SendMessageUseCase(deps.consult);
  const cancelUseCase = new CancelRunUseCase(deps.consult);

  return {
    async *run({ messages, abortSignal }): AsyncGenerator<ChatModelRunResult, void> {
      // 拼载荷：有整组回答走 answers 形态，否则取最后一条使用者消息的正文（契约第 4.1 节）。
      const submission = deps.peekPendingSubmission();
      const answers = submission?.answers ?? null;
      const skill = deps.peekPendingSkill();
      const content = answers === null || answers.length === 0 ? lastUserText(messages) : '';

      let accepted: PostMessageResponse;

      // 应急入口交接：运行已在服务端启动，这里只订阅、**不再发一条消息**——再发一次会把八项
      // 采集重复落进对话真源并把运行跑第二遍（契约第 1 节「为什么分两段」的同一条理由）。
      // 认领与否看触发点声明的意图（startRun 装配点置位），不看「有没有新输入」：
      // 应急会话的最后一条使用者消息就是采集本身，按输入推断必然误判。
      const pendingAttachedRunId = deps.peekAttachedRunId?.() ?? null;
      const attachIntent = deps.consumeAttachIntent?.() ?? false;
      // 有意图却没有交接 = 装配错位（例如交接被别处清掉）：不发消息也不订阅，留一条诊断。
      if (attachIntent && pendingAttachedRunId === null) {
        deps.onDiagnostic?.('认领意图没有对应的运行交接：本次不发送也不订阅');
        return;
      }
      const attaching = attachIntent && pendingAttachedRunId !== null;
      // 过期的交接（上一次认领中途离开页面留下、这次是普通发送）：发送取代它，顺手清掉。
      if (!attaching && pendingAttachedRunId !== null) deps.clearAttachedRun?.();
      deps.onDiagnostic?.(
        `本次运行来源：${attaching ? '认领既有运行' : '新发送'}（交接${pendingAttachedRunId === null ? '无' : '有'}，意图=${String(attachIntent)}）`,
      );

      if (attaching && pendingAttachedRunId !== null) {
        accepted = { run_id: pendingAttachedRunId, session_id: deps.sessionId };
      } else {
        try {
          accepted = await sendUseCase.execute({
            sessionId: deps.sessionId,
            content,
            // ★ 提交件整个透传（answers 与 batchId 同在 `submission` 里），不在这一层拆开再拼——
            // 拆开就又多一个「A 组 answers + B 组 batchId」可被组成的点，而那样传错的 batch_id
            // 会触发服务端排他层，比不传更坏（本包关键决策清单第 2 条）。
            ...(submission === null ? {} : { submission }),
            skill,
            ...(deps.newId === undefined ? {} : { newId: deps.newId }),
          });
        } catch (error) {
          // 发送没被受理：不消费技能选择与整组回答，重试仍能用（发送即消费只在受理后成立）。
          deps.onFailure(error);
          deps.onConnection('failed');
          // 发送阶段的 `run_not_resumable`（契约第 4.1 节）：这次提问**已经**在更早的一次
          // 请求里被受理过，而那条运行的传输态已过期（幂等键 24 小时 ≫ 运行元数据 600 秒）。
          // 处置与订阅路径完全相同——改走历史水合，因为回答若真的跑完过就在会话真源里。
          // **不得自动重发**：同一个幂等键重发会再落一条使用者消息，而那正是给这条
          // 409 存在的原因（服务端拒绝交出失效的 run_id 而不是让调用方重新起一轮）。
          if (error instanceof ConsultError && error.kind === 'not-resumable') {
            deps.onDiagnostic?.('发送阶段不可续传：改走历史水合，不重发');
            deps.onNeedsResync?.();
          }
          // 为什么不抛：本版 assistant-ui 的 thread.append 是同步 API，运行时在
          // performRoundtrip 里把消息标成 incomplete(error) 之后仍会把异常再抛给调用方
          // （core/dist/runtimes/local/local-thread-runtime-core.js 的 catch 分支），
          // 而 append 不返回 promise，于是抛出的异常变成未捕获拒绝（浏览器控制台报错 +
          // 测试进程报错）。改为「产出未完成状态」：消息同样不会伪装成完整回答，
          // 原因与重试入口由状态层的错误卡承担（不变量 1）。
          yield { content: [], status: { type: 'incomplete', reason: 'error' } };
          return;
        }

        // 受理后才消费：发送即消费的语义点是「这条消息已经发出去了」。
        deps.clearPendingSkill();
        deps.clearPendingSubmission();
      }

      const accumulator = createPartAccumulator();
      let terminal = false;
      /** run_failed 到达：先记下，等 yield 出未完成状态后结束本次生成。 */
      let runFailure: ConsultRunFailure | null = null;
      /** 事件流本身失败（传输/续传耗尽）：同样以未完成状态收尾。 */
      let transportFailure: unknown = null;

      /**
       * 取消：POST cancel，并把已渲染的 partial text 标为中断（契约第 4.3 节）。
       *
       * 认领路径**不取消**：那次运行是应急入口启动的，结果会落进会话历史；本地中断
       * （离开页面、以及 StrictMode 的模拟卸载）去取消它，等于把使用者的应急回答毁掉——
       * 这不是推断：修复的第一版正是在这里把服务端运行取消了，随后第二次订阅只能拿到
       * 一个已经死掉的流（页面显示「连接中断」，刷新后历史里也没有回答）。
       * 代价：认领路径上的停止按钮只停本地渲染，服务端运行继续跑到终态。
       */
      const requestCancel = (): void => {
        if (attaching) {
          deps.onDiagnostic?.(`本地中断，不取消服务端运行（认领路径）`);
          return;
        }
        deps.onDiagnostic?.(`用户取消运行 ${accepted.run_id}`);
        void cancelUseCase.execute(accepted.run_id).catch((error: unknown) => {
          // 已终结的运行返回 409，这是「已经停了」而不是失败；其余异常记一条诊断。
          deps.onDiagnostic?.(`取消失败：${error instanceof Error ? error.message : String(error)}`);
        });
      };

      if (abortSignal.aborted) {
        requestCancel();
        return;
      }
      abortSignal.addEventListener('abort', requestCancel, { once: true });

      try {
        for await (const event of deps.consult.streamRun({
          runId: accepted.run_id,
          signal: abortSignal,
          onNotice: (notice: StreamNotice) => {
            deps.onConnection(notice.kind === 'reconnecting' ? 'reconnecting' : 'streaming');
          },
        })) {
          if (terminal) {
            // 不变量 3：run_finished 之后到达的事件忽略，并留一条诊断（不静默吞）。
            deps.onDiagnostic?.(`run_finished 之后到达 ${event.type}：已忽略`);
            continue;
          }

          deps.onEvent(event);

          // 事件 → part 的映射全在累积器里（单一职责，另有独立单测覆盖）。
          switch (event.type) {
            case 'run_started':
              deps.onConnection('streaming');
              break;
            case 'text_delta':
              accumulator.addText(event.delta);
              break;
            case 'reasoning_delta':
              accumulator.addReasoning(event.delta);
              break;
            case 'tool_call_started':
              accumulator.startToolCall(event);
              break;
            case 'tool_call_finished':
              accumulator.finishToolCall(event);
              break;
            case 'citation':
              accumulator.addCitation(event.citation);
              break;
            case 'question':
              accumulator.addQuestion(event);
              break;
            case 'action_card':
              accumulator.addActionCard(event);
              break;
            case 'progress':
            case 'candidate':
              // 只进会话级状态（状态条文案与候选计数），不进消息内容。
              break;
            case 'run_finished':
              terminal = true;
              break;
            case 'run_failed':
              terminal = true;
              runFailure = new ConsultRunFailure(event);
              break;
          }

          yield { content: accumulator.snapshot() };
          if (runFailure !== null) break;
        }
      } catch (error) {
        // 运行期间的传输失败（重连耗尽、401、连接被切）：回流给状态层渲染错误卡。
        transportFailure = error;
      } finally {
        abortSignal.removeEventListener('abort', requestCancel);
      }

      // 只在**终态**清交接：中途 abort（离开页面，以及 StrictMode 的模拟卸载）不算认领完毕——
      // 在这里清掉会让重新装配后的页面看不到交接，运行期间的输出又变成不刷新就不显示。
      if (attaching && (terminal || transportFailure !== null)) deps.clearAttachedRun?.();

      if (runFailure !== null) deps.onFailure(runFailure);
      if (transportFailure !== null) {
        deps.onFailure(transportFailure);
        deps.onConnection('failed');
        // 不可续传（409 / 404）：本地这份 partial 已经不可能再长完整，重新读一次历史
        // 才能把服务端已保存的回答显示出来。其他失败（401/网络/服务不可用）不触发重读：
        // 那些情形历史里本来就没有新东西，重读只会闪一下屏。
        if (transportFailure instanceof ConsultError && transportFailure.kind === 'not-resumable') {
          deps.onDiagnostic?.('本次订阅不可续传：改走历史水合');
          deps.onNeedsResync?.();
        }
      }

      if (runFailure !== null || transportFailure !== null) {
        // 用「未完成 + 错误」结束而不是抛出：原因见上方发送失败分支的说明。
        // 已 yield 的 partial text 全部保留，消息状态是 incomplete，不会伪装成完整回答（不变量 1）。
        yield {
          content: accumulator.snapshot(),
          status: {
            type: 'incomplete',
            reason: 'error',
            ...(runFailure === null ? {} : { error: { code: runFailure.event.code, detail: runFailure.event.detail } }),
          },
        };
      }
    },
  };
}
