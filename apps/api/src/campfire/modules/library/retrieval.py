"""检索链：两路检索、RRF 融合、条目聚合与检索用例（按库别参数化）。

职责：实现检索用例——向量路与字面路检索、RRF 融合、按条目聚合后返回；两库（资料/案例）共用本链，由 `library` 分流。
边界：只读，不写入条目或节点；不把检索失败伪装成「未找到」；模型可控值绝不进 MetadataFilter。
参考：docs/技术设计/technical-details/资料与案例检索.md；docs/技术设计/technical-details/RAG策略.md 第 1.3、2、4 节；docs/技术设计/technical-details/公共案例库.md 第 3、4、8 节；细节见 `search` 的 docstring。
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime

from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.core.vector_stores.types import (
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
    VectorStoreQuery,
)
from llama_index.vector_stores.postgres import PGVectorStore
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.modules.library.models import (
    ITEM_MODELS,
    ITEM_TABLES,
    LIBRARIES,
    LIBRARY_CASE,
    LIBRARY_KNOWLEDGE,
    NODE_TABLE,
    CaseItem,
    KnowledgeItem,
    as_case_item,
)

#: 候选数（RAG 策略第 4、10 节）：向量路按节点计，字面路按条目计。
#: 两项在文档中标「待确认」——一期语料量小，先用初始取值，评测后校准。
VECTOR_TOP_K = 30
LITERAL_TOP_K = 30
#: 融合后取回的条目数。
FUSED_TOP_K = 8

#: 中文三元组的可用下限：≥3 个连续汉字才走字面路（RAG 策略第 3.1 节）。
#: 中文查询走字面路所需的最长连续汉字数。实测 3 是对 `asd` 一类 3 字符
#: 查询的分界（见 `literal_path_is_usable` 的实测表）。
MIN_CJK_FOR_TRIGRAM = 3

#: 非中文查询走字面路所需的最长连续字母/数字段长度（同一实测依据）。
MIN_CHARS_FOR_TRIGRAM = 3

_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")


class RetrievalError(Exception):
    """检索失败：两路都不可用，或调用方给了非法参数。

    失败语义（资料与案例检索第 5 节）：模型不得据此声称「没有相关资料」——
    因此这里抛错，由调用方转成明确的失败信号，绝不返回空列表冒充「未找到」。

    非法 `library` 同样走这个异常而不是静默退回资料库：静默兜底会让
    `search_cases` 拿到资料条目并当成案例呈现（CORE-07：边界显式，无静默兜底）。
    """


@dataclass
class RetrievedItem:
    """聚合后的检索结果（返回契约见资料与案例检索第 3 节）。

    案例专属字段全部可选并默认 `None`——资料侧不产生它们，而两个检索工具都消费
    同一个聚合结果（第 6 节：两个工具的参数与返回形状一致，差别只在库别与状态字段）。
    用可选字段而不是两个类型：聚合逻辑、名次上提与「缺字段不返回」不变量在两侧
    完全相同，为它们各写一份才是真的漂移源。
    """

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
    # --- 案例专属（第 3 节的案例必带项；资料侧为 None）---
    #: 素材授权状态（`RQ-KB-02`：真实案例与虚构样例必须可辨）。
    authorization: str | None = None
    #: 来源类型（谁说的）。
    source_type: str | None = None
    #: 循证等级（多可信）。
    evidence_level: str | None = None
    #: 审阅状态（多可信）；`owner` 不等于专业审阅。
    review_status: str | None = None
    #: 访谈时间（什么时候）。
    interview_at: datetime | None = None
    #: 是否含高风险内容，供 skill 决定呈现方式。
    makes_claims_high_risk: bool | None = None
    #: 本结果 snippet 所属卡片的被推断字段清单（第 3 节）。
    inferred_fields: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """检索结果连同降级事实（失败语义第 5 节）。

    为什么不能只返回 `list[RetrievedItem]`：

    契约第 5 节要求单路失败时「在结果中标注」哪一路不可用。两路都失败已经抛
    `RetrievalError`，但只有一路失败且没有命中时，裸空列表无法区分：

    - 「确实没找到」——模型可以说「未找到」；
    - 「语义检索坏了、而字面路恰好没命中」——契约明令模型不得据此声称
      「没有相关资料」。

    这两种情形的对外处置完全不同，因此降级必须与结果同路返回，不能靠调用方
    自己判断（它看不到两路各自的成败）。
    """

    items: list[RetrievedItem]
    #: 不可用的检索路：`"vector"` / `"literal"` 的子集；空表示两路都正常。
    #: 两路都失败不会走到这里——`search` 直接抛 `RetrievalError`。
    degraded_paths: tuple[str, ...]

    @property
    def is_degraded(self) -> bool:
        """是否有某一路不可用。"""
        return bool(self.degraded_paths)


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


def _longest_word_run(text_value: str) -> int:
    """最长连续字母/数字段（非中文查询的判据）。

    用"最长单段"而不是"总长度"：`"a b"` 总长 3 但两段各 1 字符，各自产生的
    三元组选择性极差——用总长会让这类噪声查询通过闸门。
    """
    longest = 0
    current = 0
    for ch in text_value:
        if ch.isalnum() and not _CJK_PATTERN.match(ch):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def literal_path_is_usable(query: str) -> bool:
    """字面路是否可用：中文需 ≥3 连续汉字，非中文需 ≥3 个连续字母/数字。

    实测依据（2026-09-29，2 万行临时表 + 与生产一致的三列 trigram 索引，
    两张计划都测：规划器自选与 `SET enable_seqscan=off` 强制）：

    查询 → 规划器自选 → 强制走索引
    - `autism`（6 字符） → Bitmap Index Scan → 走索引
    - `asd`（3 字符） → Bitmap Index Scan → 走索引
    - `ab`（2 字符） → Seq Scan → 走索引
    - `孤独症`（3 汉字） → Bitmap Index Scan → 走索引
    - `筛查`/`干预`（2 汉字） → Seq Scan → 走索引

    因此阈值是选择性而非"有无三元组"——实测 `ab` 这类 2 字符串同样
    产生 3 个三元组（pg_trgm 会填充边界），但那些三元组太常见，规划器宁可
    全表扫描。3 字符是分界点（`asd` 恰好走索引），故非中文取 ≥3。

    1–2 字符的查询走字面路会退化为顺序扫描且几乎无召回（RAG 策略第 3.1 节），
    因此直接跳过该路——只走向量路与元数据过滤。

    放宽的缘由（2026-09-29）：此前的闸门只数汉字，导致英文查询永远走不了
    字面路（实测 `"autism"` 被判不可用）。语料加入英文文献后这条开始有
    实际影响，而 pg_trgm 对英文同样有效。
    """
    return _count_cjk(query) >= MIN_CJK_FOR_TRIGRAM or _longest_word_run(query) >= MIN_CHARS_FOR_TRIGRAM


# ---------------------------------------------------------------------------
# 库别 → 检索期判据（每个库的判据仍是硬编码常量）
# ---------------------------------------------------------------------------
#
# quality-floor: ignore todo-residue 此处引用的是待办登记文档本身，不是未处理的代码残留
# 为什么每个库的过滤器必须是常量而不是可配置项（注入面待办条，登记在 docs/TODO.md 第五节）：
# 框架的 `PGVectorStore._build_filter_clause` 用 f-string 拼 SQL，没有绑定参数
# （实测 `params: {}`）。一旦有外部输入（模型给的 scope/authorization，或运维改的
# 配置）流进 `MetadataFilter.value`，就是 SQL 注入，且 `OR` 会逃逸整个 AND 链、
# 连带绕过库别/撤下/状态三个过滤。因此这里只允许字面量，模型可控值一律走
# 「先在自己的条目表上用绑定参数算出 item_id，再按 item_id 做 IN 过滤」的既有做法
# （见 `_allowed_item_ids` 与 `literal_search`）。
#
# 两库的状态判据不同，这是有意的：
#
# - 资料侧状态恒定 `published`（`KnowledgeItem` 的注释），过滤它就是过滤掉异常数据；
# - 案例侧状态是 `published | internal | fictional` 三值且三者都要可检索——
#   `fictional` 是虚构样例，[公共案例库] 第 8 节与 `AC-06` 要求它与真实案例
#   「混列但可辨」，把它挡在检索之外会让 `AC-06` 无从落地。因此案例侧只过滤
#   「状态缺失或为空」，不锁定具体取值。

#: 资料侧的字面路状态条件（硬编码常量，值来自 `KnowledgeItem.status` 的既定语义）。
_KNOWLEDGE_STATUS_SQL = "status = 'published'"
#: 案例侧的字面路状态条件：只要求状态存在且非空（理由见上方说明）。
#: 空串在库里等价于「没写状态」，而「缺来源或状态的条目不进入结果」是不变量。
_CASE_STATUS_SQL = "status <> ''"

#: 资料库的向量路过滤器（硬编码常量，不得改成可配置）。
_KNOWLEDGE_ACTIVE_FILTERS: tuple[MetadataFilter, ...] = (
    MetadataFilter(key="library", value=LIBRARY_KNOWLEDGE),
    MetadataFilter(key="withdrawn", value="false"),
    MetadataFilter(key="status", value="published"),
)

#: 案例库的向量路过滤器（硬编码常量）。`status` 用「非空」而不是某个取值，
#: 理由见上方注释：三种状态都必须可检索，否则 `AC-06` 的虚构可辨无从落地。
_CASE_ACTIVE_FILTERS: tuple[MetadataFilter, ...] = (
    MetadataFilter(key="library", value=LIBRARY_CASE),
    MetadataFilter(key="withdrawn", value="false"),
    MetadataFilter(key="status", value="", operator=FilterOperator.NE),
)

#: 库别 → 向量路过滤器。
_ACTIVE_FILTERS_BY_LIBRARY: dict[str, tuple[MetadataFilter, ...]] = {
    LIBRARY_KNOWLEDGE: _KNOWLEDGE_ACTIVE_FILTERS,
    LIBRARY_CASE: _CASE_ACTIVE_FILTERS,
}

#: 库别 → 字面路状态条件（SQL 常量片段，不可拼接外部输入）。
_STATUS_SQL_BY_LIBRARY: dict[str, str] = {
    LIBRARY_KNOWLEDGE: _KNOWLEDGE_STATUS_SQL,
    LIBRARY_CASE: _CASE_STATUS_SQL,
}


def _require_library(library: str) -> str:
    """校验库别取值，返回原值。

    Raises:
        RetrievalError: 取值不在 `LIBRARIES` 内。不静默退回资料库——那会让
            案例检索拿到资料条目，比明确失败更危险（CORE-07）。
    """
    if library not in LIBRARIES:
        raise RetrievalError(f"非法库别：{library!r}，合法取值：{sorted(LIBRARIES)}")
    return library


def _active_filters(library: str) -> tuple[MetadataFilter, ...]:
    """取该库的向量路过滤器（常量，见上方注入面说明）。"""
    return _ACTIVE_FILTERS_BY_LIBRARY[_require_library(library)]


def _item_filters_sql(*, scope: str | None, authorization: str | None) -> tuple[list[str], dict[str, str]]:
    """构造字面路与「允许集查询」共用的 SQL 条件片段与绑定参数。

    为什么抽成一处：`scope` 与 `authorization` 都是模型可控值，
    [资料与案例检索] 第 5 节与既有 `scope` 用例都要求它们在两条路上都生效。
    两条路各写一份条件，迟早会漂移成「向量路过滤了、字面路没过滤」——那会把
    范围外或未授权的条目从字面路漏进结果，而且功能测试照常通过。

    Returns:
        `(条件片段列表, 绑定参数)`；条件为空时返回 `([], {})`。
    """
    clauses: list[str] = []
    params: dict[str, str] = {}
    if scope is not None:
        # 子串匹配：applicable_scope 是「适用人群与情境」的自由文本，
        # 精确匹配会漏掉「学龄前儿童（3-6 岁）」一类写法（契约未定精确/子串）。
        clauses.append("applicable_scope ILIKE :scope")
        params["scope"] = f"%{scope}%"
    if authorization is not None:
        # 授权状态是枚举式短值（`search_cases` 的可选过滤参数），精确匹配。
        #
        # 列名必须加双引号：`authorization` 是 PostgreSQL 的保留字
        # （实测 `pg_get_keywords()` 报 catcode=T "reserved"），不加引号直接
        # `SELECT authorization ...` 会报 `syntax error at or near "from"`。
        # ORM 侧由 SQLAlchemy 自动加引号，只有这里的原生 SQL 需要手写。
        # 列名是常量（非外部输入），加引号不引入注入面。
        clauses.append('"authorization" = :authorization')
        params["authorization"] = authorization
    return clauses, params


async def literal_search(
    session: AsyncSession,
    query: str,
    top_k: int = LITERAL_TOP_K,
    *,
    library: str = LIBRARY_KNOWLEDGE,
    scope: str | None = None,
    authorization: str | None = None,
) -> list[tuple[str, int]]:
    """字面路：在条目表的 `title`/`keywords`/`aliases` 上做 trigram 匹配。

    返回 `[(item_id, rank)]`——检索单位是条目（RAG 策略第 4 节），
    参与融合前由调用方展开为该条目的节点。

    不用 `~`/`~*`：中文正则不走 GIN 索引（实测 EXPLAIN 为 Seq Scan）。
    用 `ILIKE '%词%'` 才走 trigram GIN。查询词被拆成词元后逐个匹配，任一命中即算。

    表名按库别取自 `ITEM_TABLES`（由模型声明派生，不是外部输入），
    因此本函数不再写死资料库表——此前写死的后果是案例检索永远查不到案例，
    而失败形态是「返回空集」，会被读成「没有相关案例」。

    Args:
        library: 库别；非法取值抛 `RetrievalError`。
        scope: 适用范围过滤（子串匹配），值走绑定参数。
        authorization: 授权状态过滤（案例侧精确匹配），值走绑定参数。

    Raises:
        RetrievalError: 库别非法，或数据库查询失败。
    """
    if not literal_path_is_usable(query):
        return []

    terms = [t for t in query.split() if t]
    if not terms:
        return []

    table = ITEM_TABLES[_require_library(library)]
    status_sql = _STATUS_SQL_BY_LIBRARY[library]

    # 用参数占位而非字符串拼接：查询词来自模型，拼接即注入风险。
    conditions = " OR ".join(
        f"title ILIKE :t{i} OR keywords ILIKE :t{i} OR aliases ILIKE :t{i}" for i in range(len(terms))
    )
    params: dict[str, object] = {f"t{i}": f"%{term}%" for i, term in enumerate(terms)}

    # scope 与 authorization 同样走绑定参数——它们来自模型，绝不可拼进 SQL 文本。
    filter_clauses, filter_params = _item_filters_sql(scope=scope, authorization=authorization)
    params.update(filter_params)
    extra_conditions = "".join(f"\n          AND {clause}" for clause in filter_clauses)

    sql = text(
        f"""
        SELECT id::text AS item_id
        FROM {table}
        WHERE withdrawn IS FALSE
          AND {status_sql}
          AND ({conditions}){extra_conditions}
        ORDER BY id
        LIMIT :limit
        """  # noqa: S608 —— table/status_sql 是模块级常量；conditions 是固定片段，值全部走绑定参数
    )
    params["limit"] = top_k

    try:
        rows = (await session.execute(sql, params)).all()
    except Exception as exc:  # noqa: BLE001 —— 转译成领域错误
        raise RetrievalError(f"字面路查询失败：{type(exc).__name__}") from exc

    return [(row.item_id, rank) for rank, row in enumerate(rows)]


async def expand_items_to_nodes(
    session: AsyncSession, item_ids: list[str]
) -> dict[str, list[tuple[str, str, dict[str, str]]]]:
    """把字面路命中的条目展开为节点：`{item_id: [(node_id, text, metadata)]}`。

    RAG 策略第 4 节要求字面路「按条目检索、参与融合前展开为该条目的节点」，
    同一条目的节点共享名次——融合在节点粒度进行。

    节点表两库共用（库别写在 metadata 上），因此本函数不需要 `library` 参数：
    `item_id` 是 UUID，跨两库不会撞。

    metadata 必须一并取出（2026-09-29 实测教训）：框架 `TextNode.hash`
    由文本 + metadata 共同决定，不是只看文本。只带文本构造的字面路节点与
    向量路节点即便 text 完全一致，哈希也不同，RRF 因此永远无法把它们判为
    「两路都命中」（实测：23 个节点 text 全同、hash 全不同，`hit_paths` 恒为
    `vector`）。这里取回与写入时一致的 metadata，让两路哈希可对齐。

    Raises:
        RetrievalError: 节点查询失败时——由调用方按单路失败降级处理。
    """
    if not item_ids:
        return {}

    try:
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT node_id, text, metadata_ AS metadata
                    FROM {NODE_TABLE}
                    WHERE metadata_->>'item_id' = ANY(:ids)
                    ORDER BY node_id
                    """  # noqa: S608 —— NODE_TABLE 是模块级常量
                ),
                {"ids": item_ids},
            )
        ).all()
    except Exception as exc:  # noqa: BLE001
        raise RetrievalError(f"展开节点失败：{type(exc).__name__}") from exc

    grouped: dict[str, list[tuple[str, str, dict[str, str]]]] = {}
    for row in rows:
        metadata = dict(row.metadata or {})
        grouped.setdefault(str(metadata.get("item_id", "")), []).append((row.node_id, row.text, metadata))
    return grouped


def build_literal_nodes(
    item_ids: list[str],
    nodes_by_item: dict[str, list[tuple[str, str, dict[str, str]]]],
) -> list[NodeWithScore]:
    """把字面路结果构造成框架节点，名次按条目名次、同条目节点共享名次。

    分数用 `1/(rank+k)`（RRF 的同一形式）：框架会按分数排序后再算 RRF，
    因此这里给出一致的单调分数即可，避免依赖具体量纲。

    metadata 照搬库中存的那份——两路哈希要对齐才能合并（见
    :func:`expand_items_to_nodes`）。
    """
    k = 60.0
    results: list[NodeWithScore] = []
    for rank, item_id in enumerate(item_ids):
        score = 1.0 / (rank + k)
        for node_id, node_text, metadata in nodes_by_item.get(item_id, []):
            results.append(
                NodeWithScore(node=TextNode(text=node_text, id_=node_id, metadata=dict(metadata)), score=score)
            )
    return results


# quality-floor: ignore docstring-promise 异常由 _require_library 与 as_uuid 抛出（间接 raise）
async def load_items(
    session: AsyncSession,
    item_ids: list[str],
    *,
    library: str = LIBRARY_KNOWLEDGE,
) -> dict[str, KnowledgeItem | CaseItem]:
    """批量取条目（用于填充返回契约字段），按库别取对应的条目表。

    Raises:
        RetrievalError: 库别非法，或 item_id 不是合法 UUID。
    """
    if not item_ids:
        return {}

    model = ITEM_MODELS[_require_library(library)]
    rows = (await session.execute(select(model).where(model.id.in_([as_uuid(i) for i in item_ids])))).scalars()
    return {str(item.id): item for item in rows}


def as_uuid(value: str) -> uuid.UUID:
    """把字符串转成 UUID。

    公开（非下划线）的原因：`withdrawal` 也要解析条目 id，两处各写一份解析就会
    出现「一处抛领域错误、一处让驱动抛裸 `DBAPIError`」的漂移。

    Raises:
        RetrievalError: 不是合法 UUID——转成领域错误，不让驱动抛底层异常。
    """
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise RetrievalError(f"非法条目 id：{value!r}") from exc


def _case_fields(item: CaseItem, node: NodeWithScore) -> dict[str, object]:
    """案例条目的专属返回字段（资料与案例检索第 3 节）。

    `inferred_fields` 的取值规则（第 3 节）：该结果 snippet 所属卡片的被推断
    字段清单。命中 narrative 小节时为空——narrative 不是卡片，逐节内容不带卡片级
    推断标记，用案例级的并集会让「这一节里有推断」变成猜。

    节点 metadata 里的 `inferred_fields` 是列表，直接从库里读出的 JSONB 反序列化
    而来；这里做一次类型收窄，防止历史数据里的畸形值（字符串）被打包进返回契约。
    """
    raw = node.node.metadata.get("inferred_fields")
    if isinstance(raw, list):
        inferred = [str(entry) for entry in raw]
    elif isinstance(raw, str) and raw:
        # 历史/手工数据的容错：单个字符串按单元素清单处理，不静默丢弃。
        inferred = [raw]
    else:
        inferred = []

    return {
        "authorization": item.authorization,
        "source_type": item.source_type,
        "evidence_level": item.evidence_level,
        "review_status": item.review_status,
        "interview_at": item.interview_at,
        "makes_claims_high_risk": item.makes_claims_high_risk,
        "inferred_fields": inferred,
    }


# quality-floor: ignore docstring-promise 异常由 _require_library 抛出（间接 raise），本函数体无 raise
def aggregate_to_items(
    fused_nodes: list[NodeWithScore],
    items: dict[str, KnowledgeItem | CaseItem],
    *,
    library: str = LIBRARY_KNOWLEDGE,
    top_k: int = FUSED_TOP_K,
) -> list[RetrievedItem]:
    """把融合后的节点聚合为条目（RAG 策略第 4 节，我们自己写、框架不做）。

    规则：

    - 同一 `item_id` 的多个节点归为一条条目；
    - 只保留名次最高的节点作为 snippet（避免同一内容重复注入）；
    - 条目名次按最佳节点上提；
    - 缺来源或状态的条目不返回（不变量：不补默认值）；
    - 同一轮不重复注入同一条目；
    - 案例侧另带六字段 + `inferred_fields`（第 3 节）。

    「呈现单位是案例、检索单位是卡片」（[公共案例库] 第 2 节）就落在这里：
    卡片级命中在条目内体现（snippet 是该卡片或该叙事小节），不另出一层列表。

    Raises:
        RetrievalError: 库别非法。
    """
    _require_library(library)

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

        extra: dict[str, object] = {}
        if library == LIBRARY_CASE:
            extra = _case_fields(as_case_item(item), node)

        results.append(
            RetrievedItem(
                item_id=item_id,
                library=library,
                title=item.title,
                snippet=node.node.text,
                source=item.source,
                applicable_scope=item.applicable_scope,
                status=item.status,
                locator=str(node.node.metadata.get("locator", "") or ""),
                ranking={
                    "fused_score": score,
                    "node_id": node.node_id,
                    # 返回契约要求「哪几路命中」（资料与案例检索第 3 节）。
                    "hit_paths": str(node.node.metadata.get("retrieval_hits", "")),
                },
                **extra,
            )
        )
        if len(results) >= top_k:
            break

    return results


def _reciprocal_rank_fuse(
    vector_nodes: list[NodeWithScore],
    literal_nodes: list[NodeWithScore],
    *,
    top_k: int = VECTOR_TOP_K,
) -> list[NodeWithScore]:
    """RRF 融合两路结果（`QueryFusionRetriever` 的 `reciprocal_rerank` 语义）。

    为什么自己复现这一步（2026-09-29 实测）：框架的 RRF 融合发生在
    `QueryFusionRetriever._retrieve` 内部，它的两路输入必须是同步检索器
    （`retrieve()`），而我们的两路都是异步 SQL；把异步查询塞进同步检索器需要
    线程池包装，既增加复杂度又让失败语义难以表达。融合公式本身只有几行
    （`score = Σ 1/(rank + k)`，k=60，框架同样用 60），因此直接复用公式，
    并把「按内容哈希合并」这一框架行为照搬——同一内容在两路命中时只算一条。

    `k=60` 与框架一致，来源是 RRF 原论文（框架源码注释里给出的同一链接）。

    命中来源记账：返回的每个节点在 `metadata["retrieval_hits"]` 上带
    `"vector"`/`"literal"`/`"both"`——返回契约的 `ranking` 字段要求
    「哪几路命中」，这是它的数据来源（RAG 策略第 9 节的度量也用它判断某一路
    是否在拖后腿）。
    """
    k = 60.0
    fused: dict[str, float] = {}
    node_by_hash: dict[str, NodeWithScore] = {}
    hit_paths: dict[str, set[str]] = {}

    for path_name, nodes in (("vector", vector_nodes), ("literal", literal_nodes)):
        # 框架先按分数降序再按名次计分；这里保持一致。
        for rank, nws in enumerate(sorted(nodes, key=lambda x: x.score or 0.0, reverse=True)):
            node_hash = nws.node.hash
            node_by_hash[node_hash] = nws
            fused[node_hash] = fused.get(node_hash, 0.0) + 1.0 / (rank + k)
            hit_paths.setdefault(node_hash, set()).add(path_name)

    ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    results: list[NodeWithScore] = []
    for node_hash, score in ordered:
        source = node_by_hash[node_hash]
        paths = hit_paths[node_hash]
        source.node.metadata["retrieval_hits"] = "both" if len(paths) == 2 else next(iter(paths))
        results.append(NodeWithScore(node=source.node, score=score))
    return results


async def _allowed_item_ids(
    session: AsyncSession,
    *,
    library: str,
    scope: str | None,
    authorization: str | None,
) -> list[str]:
    """按 `scope`/`authorization` 取允许的条目 id（绑定参数）。

    为什么不让这些值直接进 `MetadataFilter`：框架的 `_build_filter_clause` 用
    f-string 拼 SQL（`f"'%{filter_.value}%'"`），不是绑定参数。实测把
    `x' OR '1'='1` 当 scope 会生成
    `... ILIKE '%%x' OR '1'='1%%'`，且 `OR` 的优先级会逃逸整个 AND 链、
    连带绕过库别/撤下/状态三个过滤。既存过滤器全是硬编码常量，所以现状安全；
    这两个值来自模型，一旦走那条通道就是注入。

    因此：用我们自己的条目表 + 绑定参数算出允许的 item_id，向量路只按 item_id 过滤。

    条件片段与 :func:`literal_search` 共用同一个构造函数，保证两条路的
    过滤语义不会漂移（漂移的后果是范围外条目从字面路漏进来，而测试照常通过）。

    返回空列表表示没有条目匹配——调用方据此直接返回「未找到」，
    不得把空列表送进向量路的 `IN` 过滤（会生成 `IN ()` 语法错误，实测）。

    Raises:
        RetrievalError: 库别非法或查询失败——与字面路同一处置，由调用方按单路失败降级。
    """
    table = ITEM_TABLES[_require_library(library)]
    status_sql = _STATUS_SQL_BY_LIBRARY[library]
    clauses, params = _item_filters_sql(scope=scope, authorization=authorization)
    extra = "".join(f"\n          AND {clause}" for clause in clauses)

    sql = text(
        f"""
        SELECT id::text AS item_id
        FROM {table}
        WHERE withdrawn IS FALSE
          AND {status_sql}{extra}
        ORDER BY id
        """  # noqa: S608 —— table/status_sql 是模块级常量；条件值全走绑定参数
    )
    try:
        rows = (await session.execute(sql, params)).all()
    except Exception as exc:  # noqa: BLE001 —— 转译成领域错误
        raise RetrievalError(f"允许集过滤查询失败：{type(exc).__name__}") from exc
    return [row.item_id for row in rows]


async def browse(
    session: AsyncSession,
    *,
    library: str,
    limit: int = FUSED_TOP_K,
    scope: str | None = None,
    authorization: str | None = None,
) -> SearchOutcome:
    """全量浏览路：空查询时的「最近入库」列表（资料库面第 3 节）。

    为什么空查询要单走一条路而不是把空串送去检索：空串没有语义，
    嵌入它既浪费一次网络往返（应急路径的时延预算吃紧）又会得到一个
    无意义的向量、召回一堆无关条目。契约明说「空 `query` 即全量浏览流，
    按最近入库排序」，且明令不编造「热门」排序（案例库浏览页：无真实行为
    数据支撑排序策略前只用时间序）。

    过滤与检索路同源：撤下、状态、`scope`/`authorization` 都在 SQL 内完成，
    且 `scope`/`authorization` 走绑定参数（与检索路共用 `_item_filters_sql`）。

    Returns:
        `SearchOutcome`；浏览路不走向量/字面两路，因此 `degraded_paths` 恒为空
        （没有「某一路不可用」这回事，不得平白标记降级）。

    Raises:
        RetrievalError: 库别非法或查询失败。
    """
    table = ITEM_TABLES[_require_library(library)]
    status_sql = _STATUS_SQL_BY_LIBRARY[library]
    clauses, params = _item_filters_sql(scope=scope, authorization=authorization)
    extra = "".join(f"\n          AND {clause}" for clause in clauses)
    params["limit"] = limit

    sql = text(
        f"""
        SELECT id::text AS item_id, title, source, applicable_scope, status, created_at
        FROM {table}
        WHERE withdrawn IS FALSE
          AND {status_sql}{extra}
        ORDER BY created_at DESC, id
        LIMIT :limit
        """  # noqa: S608 —— table/status_sql 是模块级常量；条件值全走绑定参数
    )
    try:
        rows = (await session.execute(sql, params)).all()
    except Exception as exc:  # noqa: BLE001 —— 转译成领域错误
        raise RetrievalError(f"浏览查询失败：{type(exc).__name__}") from exc
    if not rows:
        return SearchOutcome(items=[], degraded_paths=())

    item_ids = [row.item_id for row in rows]
    # 条目侧的案例专属字段（授权、循证等级、审阅状态、访谈时间、高风险、被推断字段）
    # 只能从条目表取，上面的列表 SQL 为保持两库同形只选了共有列。
    loaded = await load_items(session, item_ids, library=library)

    snippets = await _first_node_per_item(session, library=library, item_ids=item_ids)

    items: list[RetrievedItem] = []
    for row in rows:
        item = loaded.get(row.item_id)
        if item is None:
            # 列表 SQL 与条目装载之间条目被删（并发撤下）：跳过而不是补默认值。
            continue
        # 不变量：缺来源或状态的条目不进入结果，不补默认值。
        if not item.source or not item.status or item.withdrawn:
            continue
        snippet, locator = snippets.get(row.item_id, ("", ""))
        extra_fields: dict[str, object] = {}
        if isinstance(item, CaseItem):
            extra_fields = _case_fields_for_browse(item)
        items.append(
            RetrievedItem(
                item_id=row.item_id,
                library=library,
                title=item.title,
                snippet=snippet,
                source=item.source,
                applicable_scope=item.applicable_scope,
                status=item.status,
                locator=locator,
                ranking={"order": "recent"},
                **extra_fields,
            )
        )

    return SearchOutcome(items=items, degraded_paths=())


def _case_fields_for_browse(item: CaseItem) -> dict[str, object]:
    """浏览路的案例专属字段。

    与检索路 `_case_fields` 的唯一差别是 `inferred_fields`：浏览路是条目级列表，
    没有「命中的是哪张卡片」，因此为空清单——与检索路「snippet 所属卡片」的规则
    同源（没有卡片就没有卡片级推断标注），不拿案例级并集冒充。
    """
    return {
        "authorization": item.authorization,
        "source_type": item.source_type,
        "evidence_level": item.evidence_level,
        "review_status": item.review_status,
        "interview_at": item.interview_at,
        "makes_claims_high_risk": item.makes_claims_high_risk,
        "inferred_fields": [],
    }


async def _first_node_per_item(
    session: AsyncSession, *, library: str, item_ids: list[str]
) -> dict[str, tuple[str, str]]:
    """每条目取一个节点作为浏览用的 snippet 与 locator：`{item_id: (text, locator)}`。

    用 `DISTINCT ON` 在一句 SQL 里取，而不是逐条目查询：浏览一页几十条，
    逐条查就是几十次往返（N+1）。按 `node_id` 排序让同一条目每次取到同一个节点
    （分页稳定，不会同一页里换 snippet）。

    Raises:
        RetrievalError: 查询失败。
    """
    if not item_ids:
        return {}
    try:
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT DISTINCT ON (metadata_->>'item_id')
                           metadata_->>'item_id' AS item_id,
                           text,
                           metadata_->>'locator' AS locator
                    FROM {NODE_TABLE}
                    WHERE metadata_->>'library' = :library
                      AND metadata_->>'item_id' = ANY(:ids)
                    ORDER BY metadata_->>'item_id', node_id
                    """  # noqa: S608 —— NODE_TABLE 是模块级常量
                ),
                {"library": library, "ids": item_ids},
            )
        ).all()
    except Exception as exc:  # noqa: BLE001 —— 转译成领域错误
        raise RetrievalError(f"浏览节点查询失败：{type(exc).__name__}") from exc

    return {row.item_id: (row.text, str(row.locator or "")) for row in rows}


async def search(
    session: AsyncSession,
    vector_store: PGVectorStore,
    query: str,
    *,
    library: str = LIBRARY_KNOWLEDGE,
    embed_query: Callable[[str], Awaitable[list[float]]],
    limit: int | None = None,
    scope: str | None = None,
    authorization: str | None = None,
) -> SearchOutcome:
    """检索用例：两路检索 → RRF 融合 → 条目聚合，按库别分流。

    设计（资料与案例检索第 6 节）：这是两个检索工具共同调用的用例——工具只做
    契约映射（参数、返回形状），检索链的实现归本模块。`search_knowledge` 与
    `search_cases` 的差别只在 `library` 与状态字段。

    两库分开取数，不合并成一张表加类型标签（`RQ-KB-01`、本包裁决 1）：
    库别决定查哪张条目表、用哪组硬编码过滤器、聚合时补哪些字段。合并成一张表
    加类型标签会让两库的过滤条件再也无法在 SQL 层静态确定。

    归属（见 docs/技术设计/decisions/检索链归入library模块.md）：整条链在本模块。

    对外行为与内部机制的权威划分（改代码前先读）：

    - 对外行为（两库边界、返回契约、撤下传播、失败语义）→
      `docs/技术设计/technical-details/资料与案例检索.md`
    - 内部机制与参数（合并规则、候选数、中文约束、投影清单）→
      `docs/技术设计/technical-details/RAG策略.md`
    - 案例的字段语义与呈现前提 → `docs/技术设计/technical-details/公共案例库.md`

    实现期实测得到的五条约束（2026-09-29，都有对应测试）：

    1. `QueryFusionRetriever` 的 RRF 按 `node.hash`（内容哈希）融合，不是按
       node_id——因此字面路展开出的节点必须与向量路内容一致才能合并。
    2. 字面路必须用 `LIKE`/`ILIKE`；`~`/`~*` 走顺序扫描（实测 EXPLAIN）。
       查询词需 ≥3 个连续汉字才有可用三元组。
    3. 过滤必须在 SQL 内完成；`MetadataFilter.value` 的类型联合不含 bool，
       因此 `withdrawn` 以字符串 `"true"`/`"false"` 存与查。
    4. 一期不建向量索引：几万节点内精确检索既够快又保证召回 100%。
    5. `MetadataFilter` 是字符串拼接、无绑定参数（TODO「注入面」）——因此
       `scope`/`authorization` 一律先在自己的条目表上用绑定参数算出允许集，
       向量路只按该 `item_id` 的 `IN` 过滤（值是自库读出的 UUID，外部不可控）。

    Args:
        library: 库别，`knowledge` 与 `case` 之一；非法取值抛 `RetrievalError`。
        embed_query: 异步可调用，把查询文本转成向量（由调用方注入嵌入器，
            使本函数可测且不与凭据配置耦合）。
        limit: 融合后返回的条目数上限；缺省用 `FUSED_TOP_K`。
        scope: 适用范围过滤（`search_knowledge` 的 `scope` 参数）。
            子串匹配（`ILIKE %scope%`）——`applicable_scope` 是「适用人群与
            情境」的自由文本（如「学龄前儿童」），精确匹配会把「学龄前儿童（3-6 岁）」
            一类写法漏掉。契约只写「按适用人群或情境过滤」未定精确/子串，此处取子串
            并在 `test_library_retrieval.py` 钉住，待契约确认后可改。
            值一律走绑定参数：见 `_allowed_item_ids` 的说明。
        authorization: 授权状态过滤（`search_cases` 的可选参数）。案例侧按
            `authorization` 精确匹配；同样走绑定参数，不进 MetadataFilter。

    Returns:
        `SearchOutcome`——结果加上降级事实（失败语义第 5 节要求「在结果中
        标注」哪一路不可用）。返回裸列表时降级信息无处安放：两路都失败已抛错，但
        只有一路失败且结果为空时，空列表无法区分「没找到」与「语义检索坏了」，
        而契约明令模型不得据此声称「没有相关资料」。
        空查询（`query` 去空白后为空）走 :func:`browse` 的全量浏览路。

    Raises:
        RetrievalError: 库别非法，或两路都失败时——绝不返回空列表冒充「未找到」
            （失败语义：模型不得据此声称「没有相关资料」）。
    """
    _require_library(library)
    top_k = limit or FUSED_TOP_K

    # 空查询 = 全量浏览流（资料库面第 3 节），不走向量/字面两路。
    if not query.strip():
        return await browse(session, library=library, limit=top_k, scope=scope, authorization=authorization)

    # scope/authorization 过滤的允许集（只在这里查一次，两条路共用语义）。
    allowed_ids: list[str] | None = None
    if scope is not None or authorization is not None:
        allowed_ids = await _allowed_item_ids(session, library=library, scope=scope, authorization=authorization)
        if not allowed_ids:
            # 没有任何条目匹配：这就是「未找到」，直接返回。
            # 必须提前返回——空列表进 `IN ()` 是 SQL 语法错误（实测）。
            return SearchOutcome(items=[], degraded_paths=())

    # ---- 向量路 ----
    vector_nodes: list[NodeWithScore] = []
    vector_error: Exception | None = None
    try:
        # 显式标注元素类型：`list()` 会把库过滤器（元素是 `MetadataFilter`）
        # 推断成 `list[MetadataFilter]`，而 `MetadataFilters` 要的是
        # `list[MetadataFilter | MetadataFilters]`——list 不变，故必须标出来。
        filters: list[MetadataFilter | MetadataFilters] = list(_active_filters(library))
        if allowed_ids is not None:
            # 值是我们自己表里读出的 UUID（不是模型输入），因此这条 IN 即使
            # 走框架的拼接通道也无法被外部控制。
            filters.append(MetadataFilter(key="item_id", value=allowed_ids, operator=FilterOperator.IN))
        query_embedding = await embed_query(query)
        result = await vector_store.aquery(
            VectorStoreQuery(
                query_embedding=query_embedding,
                similarity_top_k=VECTOR_TOP_K,
                filters=MetadataFilters(filters=filters),
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
        hits = await literal_search(session, query, library=library, scope=scope, authorization=authorization)
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
    items = await load_items(session, [i for i in item_ids if i], library=library)
    results = aggregate_to_items(fused, items, library=library, top_k=top_k)

    # 降级事实（失败语义第 5 节「在结果中标注」）：哪一路不可用必须随结果带走。
    # 只有某一路失败才算降级；两路都失败已在上面抛出。
    degraded: list[str] = []
    if vector_error is not None:
        degraded.append("vector")
    if literal_error is not None:
        degraded.append("literal")
    return SearchOutcome(items=results, degraded_paths=tuple(degraded))


__all__ = [
    "FUSED_TOP_K",
    "LITERAL_TOP_K",
    "MIN_CJK_FOR_TRIGRAM",
    "MIN_CHARS_FOR_TRIGRAM",
    "VECTOR_TOP_K",
    "RetrievalError",
    "RetrievedItem",
    "SearchOutcome",
    "aggregate_to_items",
    "as_uuid",
    "browse",
    "build_literal_nodes",
    "expand_items_to_nodes",
    "literal_path_is_usable",
    "literal_search",
    "load_items",
    "search",
]
