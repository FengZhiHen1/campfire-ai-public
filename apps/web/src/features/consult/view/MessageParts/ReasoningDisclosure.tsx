/**
 * 模块: features/consult/view/MessageParts/ReasoningDisclosure
 * 职责: 思考过程的折叠行——默认收起，应急场景收为一行
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 6.3 节（呈现纪律：中间态、区隔于正文、不作依据）
 *   - docs/design/pages/对话页.md: MUST — 契约修订 6（.reasoning-row）
 *   - docs/design/DESIGN.md: MUST — 反模式（思考过程渲染为正文或当作依据引用）
 * 边界:
 *   - 依赖: 无框架依赖（纯展示组件）
 *   - 被依赖: view/MessageParts/parts
 * 禁止行为:
 *   - 禁止把思考文本渲染成正文段落（必须留在折叠区内）
 *   - 禁止给它加引用语义（思考不参与 citation）
 */

/** 思考折叠行 props。 */
export interface ReasoningDisclosureProps {
  /** 思考文本（中间态）。 */
  text: string;
  /** 是否仍在流式输出（决定行内文案）。 */
  streaming: boolean;
  /** 应急场景：收为一行「正在分析…」。 */
  emergency: boolean;
}

/**
 * 渲染思考折叠行。
 *
 * 前置: text 非空（空思考段不渲染）
 * 后置: 输出默认收起的 .reasoning-row；内容区标注「中间状态，不作为结论或依据」
 * 异常: 无
 *
 * 为什么默认收起而不是自动展开：技术设计 6.3 节要求思考与正文视觉区隔，
 * 应急场景更是「慌乱中不需要看思维链」；展开与否由使用者决定。
 */
export function ReasoningDisclosure({ text, streaming, emergency }: ReasoningDisclosureProps) {
  if (text.trim() === '') return null;

  const label = emergency ? (streaming ? '正在分析…' : '分析说明 · 已结束') : '思考过程';

  return (
    <details className="reasoning-row">
      <summary>
        <span>{label}</span>
        <span className="toggle-label">
          <span className="when-closed">展开</span>
          <span className="when-open">收起</span>
        </span>
      </summary>
      <div className="process-body">
        {text}
        <p className="hint">分析说明是中间状态，不作为结论或依据。</p>
      </div>
    </details>
  );
}
