/**
 * 模块: features/consult/domain/types
 * 职责: 咨询面的业务类型与纯规则——运行状态、失败呈现、候选、连接态
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 3 节（事件到 UI 状态的映射与三条不变量）、第 7 节（失败语义表）
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 2 节错误码、第 4.2 节事件表
 * 边界:
 *   - 依赖: shared/types/sse（线格式事件）、shared/types/consult（载荷类型）
 *   - 被依赖: features/consult 的 application / viewModel / view
 * 禁止行为:
 *   - 禁止 import 任何框架模块（Domain 层无框架依赖，FE-03）
 *   - 禁止在此发起请求或持有 UI 状态（状态归 viewModel）
 *   - 禁止出现「未找到相关内容 / 没有资料」这类把检索失败读成「本来就没有」的文案（技术设计不变量 2）
 */

import type { CandidatePayload, RunFailedEvent, RunFailureCode } from '../../../shared/types/sse';

/** 技能目录项：SkillPicker 的一枚 chip。 */
export interface SkillSummary {
  /** 技能标识；即发消息载荷的 `skill` 字段取值（null 表示自动匹配）。 */
  id: string;
  /** 显示名（中文）。 */
  label: string;
}

/**
 * 连接的显式状态（判别联合的简化：取值互斥且带文案）。
 *
 * 为什么不是几个布尔量：`isReconnecting` 与 `isStreaming` 同时为真时无法判断该显示
 * 哪个文案；技术设计第 7 节对「重连中」与「运行中」给了不同文案与不同输入区行为。
 */
export type ConnectionStatus = 'idle' | 'subscribing' | 'streaming' | 'reconnecting' | 'failed';

/** 运行失败的呈现：错误码 + 用户可读标题与说明。 */
export interface RunFailureView {
  code: RunFailureCode;
  /** 一句话标题：哪件事没成功。 */
  title: string;
  /** 一句说明与可行的下一步。 */
  message: string;
  /** 是否值得给「重试」入口（不可重试的失败给重试按钮只会让人白点）。 */
  retryable: boolean;
}

/**
 * 错误码 → 呈现文案。
 *
 * 关键判断：契约与基座的 `RunFailureCode` 里没有检索专属错误码
 * （agent/runtime/events.py:33-48 只有 model_unavailable / injection_failed /
 * session_write_failed / context_overflow / internal）。检索结果与档案预取都走注入通道，
 * 因此「检索类失败」的载体是 `injection_failed`（该码的定义就是「注入项渲染/索引写入失败，
 * 不得当作没有注入继续」）——标题逐字取设计固定文案「检索暂时不可用」（对话页设计数据与文案节、
 * HTTP/SSE 契约第 8 节），说明句承担「资料或档案」的覆盖面，从而满足技术设计
 * 不变量 2（不得把检索失败读成「没有资料」）。真实后端联调时若出现独立检索码，在此补充。
 */
export const RUN_FAILURE_VIEWS: Readonly<Record<RunFailureCode, RunFailureView>> = {
  model_unavailable: {
    code: 'model_unavailable',
    title: '模型暂时不可用',
    message: '本次回答没有完成。稍后可以重试。',
    retryable: true,
  },
  injection_failed: {
    code: 'injection_failed',
    title: '检索暂时不可用',
    message: '这次没能取到资料或档案，回答可能缺少依据。可以重试。',
    retryable: true,
  },
  session_write_failed: {
    code: 'session_write_failed',
    title: '这次对话没有保存成功',
    message: '刚才的内容可能不在历史记录里。请重试一次。',
    retryable: true,
  },
  context_overflow: {
    code: 'context_overflow',
    title: '对话内容过长',
    message: '本次回答未能完成。可以新开一段对话继续说。',
    // 重试同一个请求只会再次溢出：入口是「新开对话」，不是重试。
    retryable: false,
  },
  internal: {
    code: 'internal',
    title: '回答没有生成成功',
    message: '服务端出现未预期的错误。可以重试。',
    retryable: true,
  },
};

/** 由 run_failed 事件取呈现文案。 */
export function runFailureView(event: RunFailedEvent): RunFailureView {
  return RUN_FAILURE_VIEWS[event.code];
}

/** 候选预览用的短摘要：一条候选一句话 + 来源。 */
export interface CandidateView {
  summary: string;
  source: string;
}

/** candidate 事件 → 预览条目（候选不进消息流，只进 store 的候选列表）。 */
export function candidateView(candidate: CandidatePayload): CandidateView {
  return { summary: candidate.summary, source: candidate.reference };
}

/** 状态条文案（progress 与降级提示共用）。 */
export const PROGRESS_TEXT = {
  /** 断线重连期间的输入区提示（技术设计第 7 节）。 */
  reconnecting: '连接中断，正在重连',
  /** 重连耗尽的错误标题。 */
  exhaustedTitle: '连接中断',
  exhaustedMessage: '没能恢复这次连接。可以手动重试。',
  /** 应急首字超过 10 秒的降级提示（技术设计第 7 节、RQ-EMG-03）。 */
  emergencySlow: '正在生成…建议先按通用安全措施行动',
  /** 提交后进入对话页、首字未到时的等待文案（应急表单页设计第 66 行）。 */
  emergencyAnalysing: '正在分析现场情况…',
  /** 取消后的中断标注（技术设计第 7 节「发送中途取消」行）。 */
  interrupted: '本次回答中断',
  /** 取消与重连共用的手动重试文案。 */
  retry: '重试',
} as const;

/** 应急首字降级提示的阈值（RQ-EMG-03：首个可读输出 ≤10 秒）。 */
export const EMERGENCY_FIRST_TOKEN_BUDGET_MS = 10_000;
