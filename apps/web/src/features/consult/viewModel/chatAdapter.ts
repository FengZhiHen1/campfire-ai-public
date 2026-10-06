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
import { ConsultRunFailure } from '../domain/errors';
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

      const accumulator = createPartAccumulator();
      let terminal = false;
      /** run_failed 到达：先记下，等 yield 出未完成状态后结束本次生成。 */
      let runFailure: ConsultRunFailure | null = null;
      /** 事件流本身失败（传输/续传耗尽）：同样以未完成状态收尾。 */
      let transportFailure: unknown = null;

      /** 取消：POST cancel，并把已渲染的 partial text 标为中断（契约第 4.3 节）。 */
      const requestCancel = (): void => {
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

      if (runFailure !== null) deps.onFailure(runFailure);
      if (transportFailure !== null) {
        deps.onFailure(transportFailure);
        deps.onConnection('failed');
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
