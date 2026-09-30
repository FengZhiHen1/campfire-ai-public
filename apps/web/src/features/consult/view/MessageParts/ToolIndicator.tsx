/**
 * 模块: features/consult/view/MessageParts/ToolIndicator
 * 职责: 工具调用指示行——默认收起，显示工具名与结果摘要
 * 数据来源:
 *   - docs/design/pages/对话页.md: MUST — 契约修订 7（.tool-row：默认收起、名称+摘要）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 3 节（tool_call_* → 可折叠段）
 * 边界:
 *   - 依赖: features/consult/domain/parts（ToolCallView）
 *   - 被依赖: view/MessageParts/parts
 * 禁止行为:
 *   - 禁止把工具结果摘要当正文渲染（它只是调用指示）
 */

import type { ToolCallView } from '../../domain/parts';

/** 工具行 props。 */
export interface ToolIndicatorProps {
  view: ToolCallView;
}

/** 行内文案：工具名是线上标识符，原样显示（不造中文别名）。 */
function summaryText(view: ToolCallView): string {
  if (view.state === 'running') return `${view.toolName} · 进行中`;
  if (view.ok === false) return `${view.toolName} · 未完成`;
  return `${view.toolName} · 已结束`;
}

/**
 * 渲染工具调用行。
 *
 * 前置: 无
 * 后置: 输出默认收起的 .tool-row，内容区是结果摘要（没有摘要时给显式文案）
 * 异常: 无
 */
export function ToolIndicator({ view }: ToolIndicatorProps) {
  return (
    <details className="tool-row" data-state={view.state}>
      <summary>
        <span>{summaryText(view)}</span>
        <span className="toggle-label">
          <span className="when-closed">展开</span>
          <span className="when-open">收起</span>
        </span>
      </summary>
      <div className="process-body">{view.summary === null || view.summary === '' ? '这次调用没有结果摘要。' : view.summary}</div>
    </details>
  );
}
