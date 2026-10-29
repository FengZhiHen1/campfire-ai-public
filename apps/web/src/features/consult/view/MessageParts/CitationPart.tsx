/**
 * 模块: features/consult/view/MessageParts/CitationPart
 * 职责: 依据区渲染——默认收起，展开显示来源、适用范围、状态徽章与撤下标注
 * 数据来源:
 *   - docs/design/pages/对话页.md: MUST — 契约修订 5（依据区默认收起、标题 deep-link、状态徽章、撤下标注）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 5 节（citation 跟消息走）
 *   - docs/技术设计/technical-details/资料与案例检索.md: MUST — 第 3 节（status/applicable_scope 随结果传递）、
 *     第 4 节（历史引用保留但标注「该来源已撤下」）
 * 边界:
 *   - 依赖: shared/types/sse（CitationRecord）、react-router 的 Link
 *   - 被依赖: view/MessageParts/parts
 * 禁止行为:
 *   - 禁止把 citation 当成正文的一部分渲染（它是消息尾的依据区）
 *   - 禁止在载荷缺少条目标识时编造 deep-link 目标（指不到就不跳转）
 *   - 禁止把 `<库别>:<标识>` 的前缀丢掉再拼链接：判别库别正是这条线格式存在的理由
 *   - 禁止把缺失状态渲染成「已发表」，也禁止把缺失状态默认成任何确定状态
 *   - 禁止把 `withdrawn === null`（核不出来）渲染成「已撤下」或「在库」：那是在替服务端编造事实
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
 * 状态词表：后端契约第 3 节的三个取值 → 界面文案（`RQ-KB-02`：真实与虚构必须可辨）。
 *
 * 刻意只映射这三个已知值：**不在表里的一律原样显示**后端给的那个词（不猜含义），
 * 空值显示「状态未知」。绝不把落空当成「已发表」——那正是 DEMO-03 要修的缺陷形态。
 */
export const CITATION_STATUS_LABELS: Readonly<Record<string, string>> = {
  published: '已发表',
  internal: '内部',
  fictional: '虚构样例',
};

/** 状态徽章文案。`null`/空白 = 未提供 ⇒ 「状态未知」。 */
export function citationStatusLabel(citation: CitationRecord): string {
  const raw = typeof citation.status === 'string' ? citation.status.trim() : '';
  if (raw === '') return '状态未知';
  return CITATION_STATUS_LABELS[raw] ?? raw;
}

/**
 * 适用范围文案。`null`/空白 = 未提供 ⇒ 「适用范围未知」。
 *
 * 这一项是 `RQ-CON-03` 的界面落点（输出要能说明适用条件与局限）：条目没带就不写，
 * 但**要说出来**——留白会让使用者以为这条依据没有适用条件。
 */
export function citationScopeText(citation: CitationRecord): string {
  const raw = typeof citation.applicable_scope === 'string' ? citation.applicable_scope.trim() : '';
  return raw === '' ? '适用范围未知' : raw;
}

/**
 * 该来源是否已被撤下（`RQ-KB-04`／检索文档第 4 节）。
 *
 * 只认严格的 `true`：`false` 是「在库」，`null`/缺省是「无法核对」。后两种情形都**不**
 * 渲染撤下标注——把「核不出来」画成「已撤下」等于替服务端编造一条撤下说明
 * （服务端侧同理：`refresh_citation_freshness` 核对不出来时回 `null`，不回 `true`）。
 */
export function citationIsWithdrawn(citation: CitationRecord): boolean {
  return citation.withdrawn === true;
}

/**
 * 渲染依据区。
 *
 * 前置: items 非空（空数组返回 null，不渲染空折叠头）
 * 后置: 默认收起的折叠区；展开后逐条显示标题（可跳转时）、来源、适用范围与状态徽章；
 *       已撤下的条目不跳转、灰调呈现并标注「该来源已撤下」
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
          const withdrawn = citationIsWithdrawn(citation);
          // 已撤下 ⇒ 不给 deep-link：设计契约修订 5「目标已撤下时标题不跳转」，
          // 与检索文档第 4 节「历史引用保留，但不得再作为当前依据分发」同一取向。
          const link = withdrawn ? null : citationDeepLink(citation);
          return (
            <article className={withdrawn ? 'citation-item is-withdrawn' : 'citation-item'} key={citation.citation_id}>
              {link === null ? (
                <strong className="citation-title">{citationTitle(citation)}</strong>
              ) : (
                <Link className="citation-title" to={link} state={{ returnTo: location.pathname + location.search }}>
                  {citationTitle(citation)}
                </Link>
              )}
              {/* 状态徽章（写入时的快照）与撤下标注（当前事实）分开渲染：两者回答的是
                  不同的问题，合成一句会让人分不清「当时是什么状态」与「现在还能不能用」。 */}
              <p className="meta citation-badges">
                <span className="tag meta">{citationStatusLabel(citation)}</span>
                {withdrawn ? <span className="status off">该来源已撤下</span> : null}
              </p>
              <p className="meta citation-source">
                来源：{citation.source} · 适用范围：{citationScopeText(citation)}
                {withdrawn ? ' · 不再作为当前依据' : link === null ? ' · 本条暂不能跳转到来源条目' : ''}
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
