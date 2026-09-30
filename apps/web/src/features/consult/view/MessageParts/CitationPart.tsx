/**
 * 模块: features/consult/view/MessageParts/CitationPart
 * 职责: 依据区渲染——默认收起，展开显示来源与适用范围
 * 数据来源:
 *   - docs/design/pages/对话页.md: MUST — 契约修订 5（依据区默认收起、标题 deep-link、状态徽章）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 5 节（citation 跟消息走）
 * 边界:
 *   - 依赖: shared/types/sse（CitationRecord）、react-router 的 Link
 *   - 被依赖: view/MessageParts/parts
 * 禁止行为:
 *   - 禁止把 citation 当成正文的一部分渲染（它是消息尾的依据区）
 *   - 禁止在载荷缺少条目标识时编造 deep-link 目标（指不到就不跳转）
 */

import { Link } from 'react-router';

import type { CitationRecord } from '../../../../shared/types/sse';
import { caseItemPath } from '../consultRoutes';

/** 依据区 props。 */
export interface CitationPartProps {
  items: readonly CitationRecord[];
}

/**
 * 依据条目的 deep-link。
 *
 * 目标形如 `/cases?item=<item_id>`（对话页设计契约修订 5）。当前线格式的 CitationRecord
 * （shared/types/sse 的 citation 记录）只有 citation_id/source/reference/recorded_at/summary，
 * 没有 item_id —— 因此这里做前向兼容读取：字段存在才给链接，缺失返回 null（不猜测目标）。
 * 缺口已登记在交付报告未决问题节（citation 载荷缺设计第 5 节的 item_id/library/status 等字段）。
 */
export function citationDeepLink(citation: CitationRecord): string | null {
  const itemId: unknown = (citation as { item_id?: unknown }).item_id;
  if (typeof itemId !== 'string' || itemId === '') return null;
  return caseItemPath(itemId);
}

/**
 * 渲染依据区。
 *
 * 前置: items 非空（空数组返回 null，不渲染空折叠头）
 * 后置: 默认收起的折叠区；展开后逐条显示标题（可跳转时）、来源与摘要
 * 异常: 无
 */
export function CitationPart({ items }: CitationPartProps) {
  if (items.length === 0) return null;

  return (
    <details className="citation-block">
      <summary>
        <span>依据 {items.length} 条</span>
        <span className="toggle-label">
          <span className="when-closed">展开</span>
          <span className="when-open">收起</span>
        </span>
      </summary>
      <div className="citation-list">
        {items.map((citation) => {
          const link = citationDeepLink(citation);
          return (
            <article className="citation-item" key={citation.citation_id}>
              {link === null ? (
                <strong className="citation-title">{citation.reference}</strong>
              ) : (
                <Link className="citation-title" to={link}>
                  {citation.reference}
                </Link>
              )}
              <p className="meta">
                来源：{citation.source}
                {link === null ? ' · 本条暂不能跳转到来源条目' : ''}
              </p>
              {citation.summary === null ? null : <p className="hint">{citation.summary}</p>}
            </article>
          );
        })}
      </div>
    </details>
  );
}
