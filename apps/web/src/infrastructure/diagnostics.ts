/**
 * 模块: infrastructure/diagnostics
 * 职责: 前端诊断日志的唯一出口——把被丢弃的事件/帧记成一条 debug 日志（不静默吞）
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 3 节不变量 3
 *     （run_finished 之后到达的事件忽略并计一条 debug 日志）
 * 边界:
 *   - 依赖: 无（只用 console 与 import.meta.env）
 *   - 被依赖: infrastructure/sse、features/consult 的端口实现与适配器
 * 禁止行为:
 *   - 禁止在此记录事件载荷正文、凭据或任何用户内容（只记原因与标识）
 *   - 禁止用 console.log/info/warn 冒充诊断通道（诊断走 debug，测试态静默）
 */

/** 诊断载荷：一条原因的短描述（不含正文）。 */
export type DiagnosticMessage = string | { reason: string; detail?: string };

/**
 * 生产态与测试态静默，开发态打一条 debug。
 *
 * 为什么测试态要静默：诊断的正确性由注入的 onDiagnostic 断言（canary），
 * 不靠 stdout——测试输出里混入日志会让「丢弃了哪些帧」这类断言变得含糊。
 */
const DIAGNOSTICS_ENABLED = import.meta.env.DEV && import.meta.env.MODE !== 'test';

/**
 * 记一条诊断。
 *
 * @param scope 诊断来源（模块短名，如 `sse`、`chatAdapter`）
 * @param message 原因描述；对象形式只取 reason/detail 两个字段
 */
export function logDiagnostic(scope: string, message: DiagnosticMessage): void {
  if (!DIAGNOSTICS_ENABLED) return;
  const text = typeof message === 'string' ? message : `${message.reason}${message.detail === undefined ? '' : ` ${message.detail}`}`;
  // oxlint-disable-next-line no-console -- 诊断是契约要求的可观测通道（技术设计第 3 节不变量 3），只在开发态输出
  console.debug(`[campfire:${scope}] ${text}`);
}
