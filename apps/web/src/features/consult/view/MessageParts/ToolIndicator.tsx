/**
 * 模块: features/consult/view/MessageParts/ToolIndicator
 * 职责: 工具调用指示行——默认收起，显示面向使用者的工具名与结果摘要
 * 数据来源:
 *   - docs/design/pages/对话页.md: MUST — 契约修订 7（.tool-row：默认收起、名称+摘要；
 *     名称取「查阅资料（2 条）」这类**面向使用者**的措辞，不是线上标识符）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 3 节（tool_call_* → 可折叠段）
 *   - apps/web/src/features/consult/view/MessageParts/toolLabels.ts: MUST — 标识符 → 中文名的唯一词表
 * 边界:
 *   - 依赖: features/consult/domain/parts（ToolCallView）、MessageParts/toolLabels
 *   - 被依赖: view/MessageParts/parts
 * 禁止行为:
 *   - 禁止把工具结果摘要当正文渲染（它只是调用指示）
 *   - 禁止把工具标识符直接拼进文案（OBS-01：界面暴露内部名称）
 */

import type { ToolCallView } from '../../domain/parts';
import { toolDisplayName } from './toolLabels';

/** 工具行 props。 */
export interface ToolIndicatorProps {
  view: ToolCallView;
}

/**
 * 行内文案：工具名取面向使用者的中文名（查不到时用中性兜底，**不回退成标识符**）。
 *
 * 状态后缀三个词保持不变（`进行中` / `未完成` / `已结束`）：它们是中文，且已有回归用例与
 * 测试文档引用（`docs/运维/测试人员指南.md`、`docs/运维/上线验收测试流程.md`）。
 * 名称与状态用 `·` 连接，与实现原本的形状一致——变的只是名称的来源。
 */
function summaryText(view: ToolCallView): string {
  const name = toolDisplayName(view.toolName);
  if (view.state === 'running') return `${name} · 进行中`;
  if (view.ok === false) return `${name} · 未完成`;
  return `${name} · 已结束`;
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
