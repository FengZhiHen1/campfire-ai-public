"""检索链：两路检索、RRF 融合、条目聚合与检索用例。

归属（见 docs/技术设计/decisions/检索链归入library模块.md）：整条链在本模块。

**对外行为**与**内部机制**的权威划分（改代码前先读）：

- 对外行为（两库边界、返回契约、撤下传播、失败语义）→
  ``docs/技术设计/technical-details/资料与案例检索.md``
- 内部机制与参数（合并规则、候选数、中文约束、投影清单）→
  ``docs/技术设计/technical-details/RAG策略.md``

**实现期实测得到的四条约束**（2026-09-29，都有对应测试）：

1. ``QueryFusionRetriever`` 的 RRF 按 **``node.hash``（内容哈希）** 融合，不是按
   node_id——因此字面路展开出的节点必须与向量路**内容一致**才能合并。
2. 字面路必须用 ``LIKE``/``ILIKE``；``~``/``~*`` 走顺序扫描（实测 EXPLAIN）。
   查询词需 ≥3 个连续汉字才有可用三元组。
3. 过滤必须在 SQL 内完成；``MetadataFilter.value`` 的类型联合**不含 bool**，
   因此 ``withdrawn`` 以字符串 ``"true"``/``"false"`` 存与查。
4. 一期不建向量索引：几万节点内精确检索既够快又保证召回 100%。
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.core.vector_stores.types import (
    MetadataFilter,
    MetadataFilters,
    VectorStoreQuery,
)
from llama_index.vector_stores.postgres import PGVectorStore
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.modules.library.models import LIBRARY_KNOWLEDGE, KnowledgeItem

#: 候选数（RAG 策略第 4、10 节）：向量路按节点计，字面路按条目计。
#: 两项在文档中标「待确认」——一期语料量小，先用初始取值，评测后校准。
VECTOR_TOP_K = 30
LITERAL_TOP_K = 30
#: 融合后取回的条目数。
FUSED_TOP_K = 8

#: 中文三元组的可用下限：≥3 个连续汉字才走字面路（RAG 策略第 3.1 节）。
MIN_CJK_FOR_TRIGRAM = 3

_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")

#: SQL 里只允许这两种形态的字面匹配（不得用 ~ / ~*：中文不走索引，实测）。
_LIKE_SEPARATOR = " "


class RetrievalError(Exception):
    """检索失败：两路都不可用。

    失败语义（资料与案例检索第 5 节）：**模型不得据此声称「没有相关资料」**——
    因此这里抛错，由调用方转成明确的失败信号，绝不返回空列表冒充「未找到」。
    """


@dataclass
class RetrievedItem:
    """聚合后的检索结果（返回契约见资料与案例检索第 3 节）。"""

    item_id: str
    library: str
    title: str
    snippet: str
    source: str
    applicable_scope: str
    status: str
    locator: str
    #: 融合后的名次与命中来源，供排序与调试（`ranking` 字段的契约形状）。
    ranking: dict[str, str | float] = field(default_factory=dict)


def _count_cjk(text_value: str) -> int:
    """最长连续汉字数——决定字面路是否可用。"""
    longest = 0
    current = 0
    for ch in text_value:
        if _CJK_PATTERN.match(ch):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def literal_path_is_usable(query: str) -> bool:
    """字面路是否可用：查询词需 ≥3 个连续汉字。

    1–2 字的查询走字面路会退化为顺序扫描且几乎无召回（RAG 策略第 3.1 节），
    因此直接跳过该路——只走向量路与元数据过滤。
    """
    return _count_cjk(query) >= MIN_CJK_FOR_TRIGRAM


async def literal_search(session: AsyncSession, query: str, top_k: int = LITERAL_TOP_K) -> list[tuple[str, int]]:
    """字面路：在条目表的 `title`/`keywords`/`aliases` 上做 trigram 匹配。

    返回 ``[(item_id, rank)]``——**检索单位是条目**（RAG 策略第 4 节），
    参与融合前由调用方展开为该条目的节点。

    **不用 `~`/`~*`**：中文正则不走 GIN 索引（实测 EXPLAIN 为 Seq Scan）。
    用 ``ILIKE '%词%'`` 才走 trigram GIN。查询词被拆成词元后逐个匹配，任一命中即算。

    Raises:
        RetrievalError: 数据库查询失败。
    """
    if not literal_path_is_usable(query):
        return []

    terms = [t for t in query.split() if t]
    if not terms:
        return []

    # 用参数占位而非字符串拼接：查询词来自模型，拼接即注入风险。
    conditions = " OR ".join(
        f"title ILIKE :t{i} OR keywords ILIKE :t{i} OR aliases ILIKE :t{i}" for i in range(len(terms))
    )
    params = {f"t{i}": f"%{term}%" for i, term in enumerate(terms)}

    sql = text(
        f"""
        SELECT id::text AS item_id
        FROM campfire_knowledge_item
        WHERE withdrawn IS FALSE
          AND status = 'published'
          AND ({conditions})
        ORDER BY id
        LIMIT :limit
        """  # noqa: S608 —— conditions 由上面的位置参数拼出，值全部走绑定参数
    )
    params["limit"] = top_k

    try:
        rows = (await session.execute(sql, params)).all()
    except Exception as exc:  # noqa: BLE001 —— 转译成领域错误
        raise RetrievalError(f"字面路查询失败：{type(exc).__name__}") from exc

    return [(row.item_id, rank) for rank, row in enumerate(rows)]


async def expand_items_to_nodes(session: AsyncSession, item_ids: list[str]) -> dict[str, list[tuple[str, str]]]:
    """把字面路命中的条目展开为节点：``{item_id: [(node_id, text)]}``。

    RAG 策略第 4 节要求字面路「按条目检索、参与融合前展开为该条目的节点」，
    同一条目的节点共享名次——融合在节点粒度进行（框架 RRF 按内容哈希合并）。

    Raises:
        RetrievalError: 节点查询失败时——由调用方按单路失败降级处理。
    """
    if not item_ids:
        return {}

    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT node_id, text, metadata_->>'item_id' AS item_id
                    FROM data_campfire_node
                    WHERE metadata_->>'item_id' = ANY(:ids)
                    ORDER BY node_id
                    """
                ),
                {"ids": item_ids},
            )
        ).all()
    except Exception as exc:  # noqa: BLE001
        raise RetrievalError(f"展开节点失败：{type(exc).__name__}") from exc

    grouped: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row.item_id, []).append((row.node_id, row.text))
    return grouped


def build_literal_nodes(
    item_ids: list[str],
    nodes_by_item: dict[str, list[tuple[str, str]]],
) -> list[NodeWithScore]:
    """把字面路结果构造成框架节点，名次按条目名次、同条目节点共享名次。

    分数用 ``1/(rank+k)``（RRF 的同一形式）：框架会按分数排序后再算 RRF，
    因此这里给出一致的单调分数即可，避免依赖具体量纲。
    """
    k = 60.0
    results: list[NodeWithScore] = []
    for rank, item_id in enumerate(item_ids):
        score = 1.0 / (rank + k)
        for node_id, node_text in nodes_by_item.get(item_id, []):
            results.append(NodeWithScore(node=TextNode(text=node_text, id_=node_id), score=score))
    return results


async def load_items(session: AsyncSession, item_ids: list[str]) -> dict[str, KnowledgeItem]:
    """批量取条目（用于填充返回契约字段）。"""
    if not item_ids:
        return {}

    rows = (
        await session.execute(select(KnowledgeItem).where(KnowledgeItem.id.in_([_as_uuid(i) for i in item_ids])))
    ).scalars()
    return {str(item.id): item for item in rows}


def _as_uuid(value: str) -> uuid.UUID:
    """把字符串转成 UUID；非法值抛 RetrievalError 而不是让驱动抛底层错误。"""
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise RetrievalError(f"非法条目 id：{value!r}") from exc


def aggregate_to_items(
    fused_nodes: list[NodeWithScore],
    items: dict[str, KnowledgeItem],
    *,
    top_k: int = FUSED_TOP_K,
) -> list[RetrievedItem]:
    """把融合后的节点**聚合为条目**（RAG 策略第 4 节，我们自己写、框架不做）。

    规则：

    - 同一 ``item_id`` 的多个节点归为一条条目；
    - 只保留**名次最高的节点**作为 snippet（避免同一内容重复注入）；
    - 条目名次按最佳节点上提；
    - 缺来源或状态的条目**不返回**（不变量：不补默认值）；
    - **同一轮不重复注入同一条目**。
    """
    best: dict[str, tuple[float, NodeWithScore]] = {}
    for nws in fused_nodes:
        item_id = str(nws.node.metadata.get("item_id", "") or "")
        if not item_id:
            continue
        score = nws.score or 0.0
        current = best.get(item_id)
        if current is None or score > current[0]:
            best[item_id] = (score, nws)

    ordered = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)

    results: list[RetrievedItem] = []
    for item_id, (score, node) in ordered:
        item = items.get(item_id)
        if item is None:
            continue
        # 不变量：缺来源或状态的条目不进入结果，不补默认值。
        if not item.source or not item.status or item.withdrawn:
            continue

        results.append(
            RetrievedItem(
                item_id=item_id,
                library=LIBRARY_KNOWLEDGE,
                title=item.title,
                snippet=node.node.text,
                source=item.source,
                applicable_scope=item.applicable_scope,
                status=item.status,
                locator=str(node.node.metadata.get("locator", "") or ""),
                ranking={"fused_score": score, "node_id": node.node_id},
            )
        )
        if len(results) >= top_k:
            break

    return results


#: 检索时一律带上的过滤条件（RAG 策略第 4 节：过滤在 SQL 内完成）。
#: 只查资料库、只查未撤下、只查已发布——**在 SQL 层过滤，不在应用层筛**。
_ACTIVE_FILTERS = (
    MetadataFilter(key="library", value=LIBRARY_KNOWLEDGE),
    MetadataFilter(key="withdrawn", value="false"),
    MetadataFilter(key="status", value="published"),
)


def _reciprocal_rank_fuse(
    vector_nodes: list[NodeWithScore],
    literal_nodes: list[NodeWithScore],
    *,
    top_k: int = VECTOR_TOP_K,
) -> list[NodeWithScore]:
    """RRF 融合两路结果（``QueryFusionRetriever`` 的 ``reciprocal_rerank`` 语义）。

    为什么自己复现这一步（2026-09-29 实测）：框架的 RRF 融合发生在
    ``QueryFusionRetriever._retrieve`` 内部，它的两路输入必须是**同步**检索器
    （``retrieve()``），而我们的两路都是异步 SQL；把异步查询塞进同步检索器需要
    线程池包装，既增加复杂度又让失败语义难以表达。融合公式本身只有几行
    （``score = Σ 1/(rank + k)``，k=60，框架同样用 60），因此直接复用公式，
    并把「按内容哈希合并」这一框架行为照搬——同一内容在两路命中时只算一条。

    ``k=60`` 与框架一致，来源是 RRF 原论文（框架源码注释里给出的同一链接）。
    """
    k = 60.0
    fused: dict[str, float] = {}
    node_by_hash: dict[str, NodeWithScore] = {}

    for nodes in (vector_nodes, literal_nodes):
        # 框架先按分数降序再按名次计分；这里保持一致。
        for rank, nws in enumerate(sorted(nodes, key=lambda x: x.score or 0.0, reverse=True)):
            node_hash = nws.node.hash
            node_by_hash[node_hash] = nws
            fused[node_hash] = fused.get(node_hash, 0.0) + 1.0 / (rank + k)

    ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    results: list[NodeWithScore] = []
    for node_hash, score in ordered:
        source = node_by_hash[node_hash]
        results.append(NodeWithScore(node=source.node, score=score))
    return results


async def search(
    session: AsyncSession,
    vector_store: PGVectorStore,
    query: str,
    *,
    embed_query: Callable[[str], Awaitable[list[float]]],
    limit: int | None = None,
) -> list[RetrievedItem]:
    """检索用例：两路检索 → RRF 融合 → 条目聚合。

    设计（资料与案例检索第 6 节）：这是两个检索工具共同调用的用例——工具只做
    契约映射（参数、返回形状），检索链的实现归本模块。

    Args:
        embed_query: 异步可调用，把查询文本转成向量（由调用方注入嵌入器，
            使本函数可测且不与凭据配置耦合）。
        limit: 融合后返回的条目数上限；缺省用 ``FUSED_TOP_K``。

    Raises:
        RetrievalError: 两路都失败时——**绝不返回空列表冒充「未找到」**
            （失败语义：模型不得据此声称「没有相关资料」）。
    """
    top_k = limit or FUSED_TOP_K

    # ---- 向量路 ----
    vector_nodes: list[NodeWithScore] = []
    vector_error: Exception | None = None
    try:
        query_embedding = await embed_query(query)
        result = await vector_store.aquery(
            VectorStoreQuery(
                query_embedding=query_embedding,
                similarity_top_k=VECTOR_TOP_K,
                filters=MetadataFilters(filters=list(_ACTIVE_FILTERS)),
            )
        )
        vector_nodes = [
            NodeWithScore(node=node, score=getattr(node, "score", None) or 0.0) for node in (result.nodes or [])
        ]
    except Exception as exc:  # noqa: BLE001 —— 单路失败降级，两路都失败才抛
        vector_error = exc

    # ---- 字面路 ----
    literal_nodes: list[NodeWithScore] = []
    literal_error: Exception | None = None
    try:
        hits = await literal_search(session, query)
        if hits:
            nodes_by_item = await expand_items_to_nodes(session, [item_id for item_id, _ in hits])
            literal_nodes = build_literal_nodes([item_id for item_id, _ in hits], nodes_by_item)
    except Exception as exc:  # noqa: BLE001
        literal_error = exc

    # 两路都失败：明确失败，不返回空结果（失败语义）。
    if vector_error is not None and literal_error is not None and not vector_nodes and not literal_nodes:
        raise RetrievalError(
            f"两路检索均失败：向量路 {type(vector_error).__name__}、字面路 {type(literal_error).__name__}"
        )

    fused = _reciprocal_rank_fuse(vector_nodes, literal_nodes)

    item_ids = [str(n.node.metadata.get("item_id", "") or "") for n in fused]
    items = await load_items(session, [i for i in item_ids if i])
    return aggregate_to_items(fused, items, top_k=top_k)


__all__ = [
    "FUSED_TOP_K",
    "LITERAL_TOP_K",
    "MIN_CJK_FOR_TRIGRAM",
    "VECTOR_TOP_K",
    "RetrievalError",
    "RetrievedItem",
    "aggregate_to_items",
    "build_literal_nodes",
    "expand_items_to_nodes",
    "literal_path_is_usable",
    "literal_search",
    "load_items",
    "search",
]
