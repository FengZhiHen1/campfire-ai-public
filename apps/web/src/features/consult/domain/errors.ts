/**
 * 模块: features/consult/domain/errors
 * 职责: 咨询面失败的类型化与呈现文案——把传输/校验失败收敛成显式种类
 * 数据来源:
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 2 节错误码表、第 8 节失败语义
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 7 节失败语义与降级
 * 边界:
 *   - 依赖: 无（纯 Domain 规则，不认识 HTTP 类型）
 *   - 被依赖: application 用例、viewModel、view
 * 禁止行为:
 *   - 禁止把失败呈现成成功（不变量 1：partial text 保留但必须标注中断）
 *   - 禁止出现「未找到相关内容 / 没有资料」这类把检索失败读成「本来就没有」的文案（不变量 2）
 */

import type { RunFailedEvent } from '../../../shared/types/sse';
import { runFailureView } from './types';

/**
 * 失败种类。
 *
 * 为什么在 Domain 定义种类、由 infrastructure 翻译：状态码与 SDK 异常属于传输细节，
 * 而「能不能重试、要不要跳登录」是业务判定；两者分层后，view 只按种类渲染文案。
 */
export type ConsultFailureKind =
  | 'unauthorized'
  | 'not-found'
  | 'busy'
  | 'invalid'
  | 'unavailable'
  | 'network'
  | 'not-resumable'
  | 'stream-exhausted'
  | 'invalid-request'
  | 'unexpected';

/** 咨询面失败；kind 是调用方唯一需要分支的字段。 */
export class ConsultError extends Error {
  constructor(
    readonly kind: ConsultFailureKind,
    message: string,
    options?: { cause?: unknown },
  ) {
    super(message, options);
    this.name = 'ConsultError';
  }
}

/**
 * 本次运行以失败告终（run_failed）。
 *
 * 适配器抛它：runtime 会把这条助手消息置为错误态，已 yield 的 partial text 因此保留
 * 并显示失败原因与重试入口——这正是「失败不得伪装成完整回答」（不变量 1）的落法。
 */
export class ConsultRunFailure extends Error {
  constructor(readonly event: RunFailedEvent) {
    super(runFailureView(event).title);
    this.name = 'ConsultRunFailure';
  }
}

/** 失败的用户可读呈现。 */
export interface ConsultFailureView {
  title: string;
  message: string;
  /** 是否值得给「重试」入口（不可重试的失败给重试按钮只会让人白点）。 */
  retryable: boolean;
}

/** 失败种类 → 呈现文案。 */
export const CONSULT_FAILURE_VIEWS: Readonly<Record<ConsultFailureKind, ConsultFailureView>> = {  unauthorized: { title: '会话已过期', message: '请重新登录后再继续。', retryable: false },
  'not-found': { title: '找不到这条内容', message: '它可能已被删除，或不属于当前账号。', retryable: false },
  busy: { title: '这个会话正在处理上一条消息', message: '等当前回答结束后再发送。', retryable: true },
  invalid: { title: '提交的内容不合要求', message: '请检查后重试。', retryable: false },
  unavailable: { title: '服务暂时不可用', message: '稍后可以重试。', retryable: true },
  network: { title: '网络不可用', message: '请检查连接后重试。', retryable: true },
  'not-resumable': {
    title: '这次回答无法继续接收',
    message: '已改为显示服务端保存下来的内容。',
    retryable: false,
  },
  'stream-exhausted': { title: '连接中断', message: '没能恢复这次连接。可以手动重试。', retryable: true },
  'invalid-request': { title: '无法发送这条消息', message: '请修改后重试。', retryable: false },
  unexpected: { title: '出现了未预期的错误', message: '可以重试一次。', retryable: true },
};

/** 取失败呈现；未知异常按 unexpected 呈现（不静默吞，也不假装成功）。 */
export function failureViewFor(error: unknown): ConsultFailureView {
  if (error instanceof ConsultError) {
    const view = CONSULT_FAILURE_VIEWS[error.kind];
    // invalid-request 的 message 用具体原因（哪个字段不合法），通用文案会丢信息。
    return error.kind === 'invalid-request' ? { ...view, message: error.message } : view;
  }
  if (error instanceof ConsultRunFailure) return runFailureView(error.event);
  return CONSULT_FAILURE_VIEWS.unexpected;
}