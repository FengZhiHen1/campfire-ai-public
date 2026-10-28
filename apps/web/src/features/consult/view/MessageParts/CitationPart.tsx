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
 *   - 禁止把 `<库别>:<标识>` 的前缀丢掉再拼链接：判别库别正是这条线格式存在的理由
 */

import { Link, useLocation } from 'react-router';

import type { CitationRecord } from '../../../../shared/types/sse';
import { caseItemPath } from '../consultRoutes';

/** 依据区 props。 */
export interface CitationPartProps {
  items: readonly CitationRecord[];
}

/**
 * 从 `reference` 里取出条目 id。
 *
 * 线格式的 `reference` 形如 `knowledge:<uuid>` / `case:<uuid>`：库别前缀是刻意带的
 * （见 `apps/api/src/campfire/tools/library.py` 的说明——条目 id 在两库之间不保证全局唯一，
 * 只给裸 uuid 时拿到它的人不知道该去哪个库查）。因此「前缀:标识」是本模块唯一认的形状，
 * 前缀不在已知集合里就不给链接：猜错库比不跳转更糟。
 */
const REFERENCE_NAMESPACE = /^(knowledge|case):(.+)$/u;

/** 已知库别；用于判断前缀是不是我们认识的（与后端 `tools/library.py` 的 `source` 取值一致）。 */
const KNOWN_NAMESPACES: ReadonlySet<string> = new Set(['knowledge', 'case']);

/**
 * 依据条目的 deep-link。
 *
 * 目标形如 `/cases?item=<item_id>`（对话页设计契约修订 5）；案例库浏览页按条目自己的
 * `library` 字段落到案例或资料分区，所以两个库共用同一条路径。
 *
 * 取值优先级（前向兼容）：载荷里显式带 `item_id` 就用它（设计第 5 节的完整载荷会带），
 * 否则从 `reference` 的 `<库别>:<标识>` 前缀里取。两者都拿不到 ⇒ `null`（不猜目标）。
 */
export function citationDeepLink(citation: CitationRecord): string | null {
  const explicit: unknown = (citation as { item_id?: unknown }).item_id;
  if (typeof explicit === 'string' && explicit !== '') return caseItemPath(explicit);

  const matched = REFERENCE_NAMESPACE.exec(citation.reference);
  if (matched === null) return null;
  const [, namespace, itemId] = matched;
  if (namespace === undefined || itemId === undefined) return null;
  if (!KNOWN_NAMESPACES.has(namespace) || itemId === '') return null;
  // 标识里不该有分隔符；有就说明这不是我们认得的形状（宁可不出链接）。
  if (/[/?#\s]/u.test(itemId)) return null;
  return caseItemPath(itemId);
}

/**
 * 依据条目的显示标题。
 *
 * 优先用 `summary`：调用方写入摘要时取的是条目标题（见后端 `tools/library.py`：
 * 「摘要取标题：它是使用者能在依据区一眼认出那条来源的最短信息」）。没有摘要才退回
 * `reference`——它是可回指键，但对人不可读，只在缺标题时兜底。
 */
export function citationTitle(citation: CitationRecord): string {
  const summary = citation.summary;
  return summary === null || summary.trim() === '' ? citation.reference : summary.trim();
}

/**
 * 渲染依据区。
 *
 * 前置: items 非空（空数组返回 null，不渲染空折叠头）
 * 后置: 默认收起的折叠区；展开后逐条显示标题（可跳转时）、来源与摘要
 * 异常: 无
 */
export function CitationPart({ items }: CitationPartProps) {
  const location = useLocation();
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
                <strong className="citation-title">{citationTitle(citation)}</strong>
              ) : (
                <Link className="citation-title" to={link} state={{ returnTo: location.pathname + location.search }}>
                  {citationTitle(citation)}
                </Link>
              )}
              <p className="meta">
                来源：{citation.source}
                {link === null ? ' · 本条暂不能跳转到来源条目' : ''}
              </p>
              {/* 摘要就是标题时不再重复渲染一次（两行同样的字看着像 bug）。 */}
              {citation.summary === null || citation.summary.trim() === citationTitle(citation) ? null : (
                <p className="hint">{citation.summary}</p>
              )}
            </article>
          );
        })}
      </div>
    </details>
  );
}
