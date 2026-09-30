"""检索侧产品工具：`search_knowledge` 与 `search_cases`。

职责：把 `modules/library` 的检索链包装成基座可调用的两个检索工具。
边界：只做包装——两路检索、RRF 融合、条目聚合、撤下过滤、降级判定都在 `modules/library`，
此处不重复实现，也不直接碰表；禁止 import `surfaces/*`。
参考：docs/技术设计/面/consult/tools/search_knowledge.md、
docs/技术设计/面/consult/tools/search_cases.md；
docs/技术设计/technical-details/资料与案例检索.md；docs/项目结构设计.md 第 6、7 节。

为什么两个工具在同一个模块（2026-09-30，随 T03 落地更新）：

此前本模块只有 `search_knowledge`，理由是「`search_cases` 不可实现」——案例条目表与
7 个案例专属字段不存在，且检索链硬编码只查资料库。该前置已由 `modules/library` 的
案例批次补齐（案例条目表、迁移、`search(library=...)` 按库别参数化）。因此这里补上
`search_cases`，两份工具共用同一个 `_run_search` 装配与同一套返回契约字段：

- 共用的部分（条目聚合、撤下过滤、降级判定、`source`/`applicable_scope`/`status`）
  只写一处，改一处两个工具同时生效——抄两份必然漂移；
- 不共用的部分只有一个：库别（`library=`）与案例专属字段的渲染。

两库不互相混入：库别由各自的工具写死传入，模型无法改（契约第 4 节「只查案例库」
对 `search_cases` 与「只查资料库」对 `search_knowledge` 是同一件事的两种说法）。
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from campfire.agent.tools import ToolContext, ToolFailure, ToolResult
from campfire.core.config import Settings, get_settings
from campfire.core.db import create_sync_engine, get_engine, session_scope
from campfire.modules.library.ingestion import build_vector_store
from campfire.modules.library.retrieval import (
    FUSED_TOP_K,
    LIBRARY_CASE,
    LIBRARY_KNOWLEDGE,
    RetrievalError,
    RetrievedItem,
    SearchOutcome,
    search,
)

logger = logging.getLogger(__name__)

#: 返回条目数的服务端上界。与 `retrieval.FUSED_TOP_K` 的关系：前者是契约层的
#: 默认值，后者是检索链的默认值；上界取两者较大值再收窄到 20，避免调用方用
#: `limit=10**9` 让一次注入吃掉整个上下文预算（CORE-11 有界性）。
#: 为什么不是 `FUSED_TOP_K` 本身：契约写「默认值待确认」，此处不改动检索链默认值，
#: 只在工具层设上界。
MAX_RESULT_LIMIT = 20

#: 未给 `limit` 时用的默认条数。取检索链默认值，让「不给 limit」与「直接调检索链」一致。
DEFAULT_RESULT_LIMIT = FUSED_TOP_K

#: 单条 snippet 进模型上下文的字符上界。检索节点文本可能很长（实测语料里有 2248 字符
#: 的 section），一次 8 条就可能挤占整个上下文——截断并在结果里标明，比静默超预算好。
SNIPPET_MAX_CHARS = 1200


class SearchKnowledgeArgs(BaseModel):
    """`search_knowledge` 的参数（契约第 2 节）。"""

    query: str = Field(
        min_length=1,
        max_length=500,
        description="检索词。中文至少 3 个连续汉字或非中文至少 3 个连续字母数字才会走字面路。",
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        le=MAX_RESULT_LIMIT,
        description=f"返回条数，默认 {DEFAULT_RESULT_LIMIT}，最多 {MAX_RESULT_LIMIT}。",
    )
    scope: str | None = Field(
        default=None,
        max_length=200,
        description="按适用人群或情境过滤（子串匹配，例如「学龄前」）。省略则不按范围过滤。",
    )


class SearchCasesArgs(BaseModel):
    """`search_cases` 的参数（契约第 2 节）。"""

    query: str = Field(
        min_length=1,
        max_length=500,
        description="检索词。中文至少 3 个连续汉字或非中文至少 3 个连续字母数字才会走字面路。",
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        le=MAX_RESULT_LIMIT,
        description=f"返回条数，默认 {DEFAULT_RESULT_LIMIT}，最多 {MAX_RESULT_LIMIT}。",
    )
    authorization: str | None = Field(
        default=None,
        max_length=200,
        description="按素材授权状态过滤（精确匹配，例如「已授权」）。省略则不按授权过滤。",
    )


def _render_item(item: RetrievedItem) -> dict[str, object]:
    """把检索结果映射为返回契约（资料与案例检索第 3 节）的字段。

    字段名与契约逐字一致：`item_id` / `library` / `title` / `snippet` /
    `source` / `applicable_scope` / `status` / `locator` / `ranking`。
    `source` 与 `applicable_scope` 必须带回（`RQ-CON-03`：输出要能说明适用条件与
    局限），因此这里不做任何删减。
    """
    snippet = item.snippet
    truncated = len(snippet) > SNIPPET_MAX_CHARS
    return {
        "item_id": item.item_id,
        "library": item.library,
        "title": item.title,
        "snippet": snippet[:SNIPPET_MAX_CHARS],
        "snippet_truncated": truncated,
        "source": item.source,
        "applicable_scope": item.applicable_scope,
        "status": item.status,
        "locator": item.locator,
        "ranking": item.ranking,
    }


def _render_case_item(item: RetrievedItem) -> dict[str, object]:
    """案例条目的返回映射 = 共用字段 + 七个案例专属字段（资料与案例检索第 3 节）。

    为什么这七个字段一个都不能省（契约第 3 节、公共案例库第 8 节）：

    - `status` 与 `authorization` 是「真实案例与虚构样例必须可辨」（`AC-06`）的全部依据；
    - `review_status` 决定这条能否作为专业依据（`owner` 不等于专业审阅）；
    - `evidence_level` 决定信任度；
    - `interview_at` 是「什么时候说的」；
    - `makes_claims_high_risk` 是高风险主张的标注；
    - `inferred_fields` 是「被推断的字段必须标为推断」的前提。

    省掉任一个，模型就无法如实回答「谁说的、多可信、什么时候」——那不是输出干净，
    是让模型只能自己编。因此这里逐字段透传，缺失（`None`）也如实保留为 `None`。
    """
    rendered = _render_item(item)
    rendered.update(
        {
            "authorization": item.authorization,
            "source_type": item.source_type,
            "evidence_level": item.evidence_level,
            "review_status": item.review_status,
            # `interview_at` 是 `datetime`；返回契约第 3 节要求时间可传递，
            # 因此转成 ISO 8601 字符串，而不是让 `json.dumps` 抛错。
            "interview_at": None if item.interview_at is None else item.interview_at.isoformat(),
            "makes_claims_high_risk": item.makes_claims_high_risk,
            "inferred_fields": list(item.inferred_fields),
        }
    )
    return rendered


def _degradation_note(degraded: tuple[str, ...]) -> str | None:
    """把降级事实转成给模型看的一句说明（失败语义第 5 节）。

    必须明确到不允许模型把「检索不完整」说成「没有相关资料」——契约第 5 节的原话是
    「模型不得据此声称『没有相关资料』」，而模型只有看到这句话才能在自然语言里
    如实表达。因此这不是日志，是返回内容的一部分。
    """
    if not degraded:
        return None
    parts = []
    if "vector" in degraded:
        parts.append("语义检索")
    if "literal" in degraded:
        parts.append("关键词检索")
    available = "关键词检索" if "vector" in degraded else "语义检索"
    return (
        f"注意：{'与'.join(parts)}不可用，本次结果不完整（只用了{available}）。"
        "**不得**据此声称「没有相关资料」——应说明检索能力受限。"
    )


async def search_knowledge(context: ToolContext, args: SearchKnowledgeArgs) -> ToolResult | ToolFailure:
    """在专业资料库里检索，为建议找依据（契约第 1 节）。

    归属（docs/项目结构设计.md第 6 节）：`tools/` 把
    `modules/` 的能力包装成基座可调用的工具。本模块只做包装——两路检索、RRF 融合、
    条目聚合、撤下过滤、降级判定都在 `modules/library`，此处不重复实现，也不直接碰表。

    契约真源：

    - docs/技术设计/面/consult/tools/search_knowledge.md
    - 检索链的对外行为（返回契约字段、撤下传播、失败语义）：
      docs/技术设计/technical-details/资料与案例检索.md

    为什么不是「只有 `search_knowledge`」（2026-09-30，随 `modules/library` 案例批次更新）：

    本函数曾附一段「`search_cases` 不可实现」的说明（案例条目表与 7 个案例专属字段不存在、
    检索链硬编码只查资料库）。三项前置已被 `modules/library` 补齐：案例条目表与迁移、
    7 个案例字段落表、`search(library=...)` 按库别参数化。因此那段说明已不成立，
    替换为当前事实：`search_cases` 就在本模块下方，与 `search_knowledge` 共用装配与渲染。

    依赖白名单：

    `tools/*` 允许依赖 `agent/tools`、`modules/*`、`core/*`；禁止 import
    `surfaces/*`，禁止绕过用例服务直接写表（第 7 节）。因此本模块调
    `modules.library.retrieval.search`，没有一条直接构造 SQL。

    只查资料库，不混入案例（契约第 4 节）。撤下、状态、库别三个过滤在
    `modules.library` 的 SQL 层完成，本函数不重复做。

    Returns:
        `ToolResult`：命中条目的 JSON；空结果时明确写「未找到」并附
        「不得解释为该做法不存在或没有风险」的提示（契约第 5 节第 4 行）。
        `ToolFailure`：两路都失败时——绝不返回空列表冒充「未找到」。
    """
    settings = get_settings()
    limit = args.limit or DEFAULT_RESULT_LIMIT
    # 服务端上界（CORE-11）：契约层已用 `le=MAX_RESULT_LIMIT` 拦住，这里再收一次，
    # 覆盖「绕过参数模型直接调用本函数」的情形（与 store 侧同一纪律）。
    limit = max(1, min(limit, MAX_RESULT_LIMIT))

    try:
        outcome = await _run_search(settings, query=args.query, limit=limit, scope=args.scope)
    except RetrievalError as exc:
        # 两路都失败：明确失败。消息只给异常类型，不复述连接串（安全条款）。
        logger.warning("search_knowledge 检索失败：%s", type(exc).__name__)
        return ToolFailure(
            code="tool_failed",
            message=(
                "检索服务暂时不可用，**没有**完成检索。"
                "不得据此声称「没有相关资料」——请向使用者说明检索能力受限，或稍后重试。"
            ),
        )
    except Exception as exc:  # noqa: BLE001 —— 装配/嵌入一类失败同样不得冒充「未找到」
        logger.warning("search_knowledge 失败：%s", type(exc).__name__)
        return ToolFailure(
            code="tool_failed",
            message="检索未能完成，**没有**得到检索结果。不得据此声称「没有相关资料」。",
        )

    items = [_render_item(item) for item in outcome.items]
    return _result_payload(
        items,
        outcome.degraded_paths,
        empty_notice="未找到相关资料。这**不等于**该做法不存在或没有风险——只能说本资料库当前没有可引用的依据。",
    )


async def search_cases(context: ToolContext, args: SearchCasesArgs) -> ToolResult | ToolFailure:
    """在案例库里检索相似情形，供使用者参考「别人遇到过什么、试过什么」（契约第 1 节）。

    归属（docs/项目结构设计.md第 6 节）：`tools/` 把 `modules/` 的能力包装成基座可调用的
    工具。本函数只做包装——两路检索、RRF 融合、条目聚合、撤下过滤、授权过滤、降级判定都在
    `modules/library`，此处不重复实现，也不直接碰表。

    契约真源：

    - docs/技术设计/面/consult/tools/search_cases.md
    - 返回契约字段、授权维度的语义、失败语义：
      docs/技术设计/technical-details/资料与案例检索.md

    硬约束（契约第 4 节）：

    1. 只查案例库，不混入专业资料。库别由本函数写死传 `LIBRARY_CASE`，
       参数模型里没有库别字段——模型无法把这条约束改成「查资料库」。
    2. 结果侧约束（`status` / `authorization` 随结果返回、真实案例与虚构样例可辨、
       撤下即不返回）不在工具层重做：它们在检索链与返回映射里落地
       （`_render_case_item` 逐字段透传，一个不省）。

    为什么 `authorization` 是自由字符串而不是枚举（与 emit 工具的状态词表相反）：

    案例的授权取值域由素材侧（`CaseItem.authorization` 是文本列）拥有，不是本项目
    封闭定义的词表。在工具层写一份枚举就成了第二份定义，素材侧增删取值时会与它漂移，
    而漂移的表现是「合法取值被参数校验拒绝」——比不校验更糟。此处只设长度上界，
    合法取值域由存储与检索侧决定。

    失败语义与 `search_knowledge` 同源（契约第 5 节：不归本文拥有）：
    两路都失败时明确失败，绝不返回空列表冒充「没有相关案例」——那会让模型
    对使用者说「没有类似的案例」，而事实是检索没跑成。

    Returns:
        `ToolResult`：命中案例的 JSON（共用字段 + 七个案例专属字段）；
        空结果时明确写「未找到」。
        `ToolFailure`：检索链失败时。
    """
    settings = get_settings()
    limit = args.limit or DEFAULT_RESULT_LIMIT
    # 服务端上界（CORE-11）：与 `search_knowledge` 同法，覆盖绕过参数模型的调用。
    limit = max(1, min(limit, MAX_RESULT_LIMIT))

    try:
        outcome = await _run_search(
            settings,
            query=args.query,
            limit=limit,
            library=LIBRARY_CASE,
            authorization=args.authorization,
        )
    except RetrievalError as exc:
        logger.warning("search_cases 检索失败：%s", type(exc).__name__)
        return ToolFailure(
            code="tool_failed",
            message=(
                "检索服务暂时不可用，**没有**完成检索。"
                "不得据此声称「没有相关案例」——请向使用者说明检索能力受限，或稍后重试。"
            ),
        )
    except Exception as exc:  # noqa: BLE001 —— 装配/嵌入一类失败同样不得冒充「未找到」
        logger.warning("search_cases 失败：%s", type(exc).__name__)
        return ToolFailure(
            code="tool_failed",
            message="检索未能完成，**没有**得到检索结果。不得据此声称「没有相关案例」。",
        )

    items = [_render_case_item(item) for item in outcome.items]
    # 空结果的措辞针对案例侧：不得让模型把「案例库没有命中」说成「没有这种情形」。
    return _result_payload(
        items,
        outcome.degraded_paths,
        empty_notice=("未找到相关案例。这**不等于**没有其他家庭遇到过类似情形——只能说本案例库当前没有可引用的记录。"),
    )


def _result_payload(
    items: list[dict[str, object]],
    degraded_paths: tuple[str, ...],
    *,
    empty_notice: str,
) -> ToolResult:
    """两个检索工具共用的返回打包：条目、条数、降级说明、空结果提示。

    抽出一处是因为这四条对外说法（含措辞纪律）是同一份契约：两处各写一遍，
    改一处忘另一处就会让其中一个工具悄悄丢掉降级提示——而「不得把检索不完整
    说成没有资料」正是靠那句话成立的。
    """
    payload: dict[str, object] = {"results": items, "count": len(items)}
    note = _degradation_note(degraded_paths)
    if note is not None:
        payload["degraded"] = True
        payload["degraded_paths"] = list(degraded_paths)
        payload["notice"] = note
    if not items:
        # 契约第 5 节第 4 行：检索为空要明确「未找到」，且不得解释为
        # 「该做法不存在或没有风险」。这句必须进返回文本，否则模型只能自己猜。
        payload["notice"] = empty_notice
    return ToolResult(text=json.dumps(payload, ensure_ascii=False))


async def _run_search(
    settings: Settings,
    *,
    query: str,
    limit: int,
    scope: str | None = None,
    library: str = LIBRARY_KNOWLEDGE,
    authorization: str | None = None,
) -> SearchOutcome:
    """装配检索链的依赖并跑一次 `search()`。

    装配细节：`search()` 要求一个 `PGVectorStore` 与一个 `embed_query` 可调用。
    向量存储必须注入我们自己的同步/异步引擎（框架要求成对），否则它会另建一套连接池
    ——「撤下与条目在同一事务」的前提就不成立（RAG 策略第 2 节）。

    两个工具共用本函数，各传自己的库别与过滤参数：装配细节（引擎、嵌入器、
    会话）只有一份，库别与过滤是参数——这样 `search_cases` 不必复制一遍装配。
    """
    from campfire.modules.library.embedding import build_embedding

    embedder = build_embedding(settings)
    async_engine = get_engine(settings)
    sync_engine = create_sync_engine(settings)
    try:
        vector_store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine)
        async with session_scope(settings) as session:
            return await search(
                session,
                vector_store,
                query,
                library=library,
                embed_query=embedder.aget_query_embedding,
                limit=limit,
                scope=scope,
                authorization=authorization,
            )
    finally:
        # 同步引擎只服务于框架的写入路径，这里只读，用完即关（避免每次调用泄漏连接池）。
        sync_engine.dispose()


__all__ = [
    "DEFAULT_RESULT_LIMIT",
    "MAX_RESULT_LIMIT",
    "SNIPPET_MAX_CHARS",
    "SearchCasesArgs",
    "SearchKnowledgeArgs",
    "search_cases",
    "search_knowledge",
]
