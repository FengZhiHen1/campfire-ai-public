"""检索侧产品工具：``search_knowledge``。

归属（[项目结构设计](../../../../../../docs/项目结构设计.md)第 6 节）：``tools/`` 把
``modules/`` 的能力包装成基座可调用的工具。本模块**只做包装**——两路检索、RRF 融合、
条目聚合、撤下过滤、降级判定都在 `modules/library`，此处不重复实现，也不直接碰表。

## 契约真源

- [search_knowledge](../../../../../../docs/技术设计/面/consult/tools/search_knowledge.md)
- 检索链的对外行为（返回契约字段、撤下传播、失败语义）：
  [资料与案例检索](../../../../../../docs/技术设计/technical-details/资料与案例检索.md)

## 为什么只有 ``search_knowledge``（2026-09-30 实测）

``search_cases`` 在**当前代码库里不可实现**，因此本模块没有它——不是遗漏，是依赖不存在：

1. **案例条目表不存在**。`modules/library/models.py` 只有 ``campfire_knowledge_item``
   （`LIBRARY_CASE` 常量被定义却**没有任何使用点**，实测全库 grep 只有它自己的定义行），
   迁移 `113a04901d24` 也只建了资料条目表与节点表。
2. **7 个案例专属返回字段在表里不存在**：`authorization`、`source_type`、
   `evidence_level`、`review_status`、`interview_at`、`makes_claims_high_risk`、
   `inferred_fields`。这些不是可选装饰——[资料与案例检索] 第 3 节明说前五个是
   [公共案例库] 第 8 节呈现规则能落地的前提（缺任一个，输出就无法如实回答
   「谁说的、多可信、什么时候」），`inferred_fields` 是「被推断的字段必须标为推断」
   的前提。**缺字段就返回**（同文第 1 节不变量）意味着现在只能返回空集，
   那比不实现更糟：模型会把它读成「没有相关案例」。
3. **检索链只查资料库**：`retrieval._ACTIVE_FILTERS` 硬编码
   ``MetadataFilter(key="library", value=LIBRARY_KNOWLEDGE)``，字面路的 SQL 也写死
   查 `campfire_knowledge_item`——因此按现状直接调用 `search()` 永远得不到案例。

落地前置因此是：案例条目表与迁移（含上述7字段）→ 检索链按库别参数化 →
`search_cases`。这三步属 `modules/library` 的独立工作，不在记忆模块批次内。

## 依赖白名单

``tools/*`` 允许依赖 ``agent/tools``、``modules/*``、``core/*``；**禁止 import
``surfaces/*``，禁止绕过用例服务直接写表**（第 7 节）。因此本模块调
`modules.library.retrieval.search`，**没有一条直接构造 SQL**。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from campfire.agent.tools import ToolContext, ToolFailure, ToolResult
from campfire.core.config import Settings, get_settings
from campfire.core.db import create_sync_engine, get_engine, session_scope
from campfire.modules.library.ingestion import build_vector_store
from campfire.modules.library.retrieval import (
    FUSED_TOP_K,
    RetrievalError,
    RetrievedItem,
    SearchOutcome,
    search,
)

logger = logging.getLogger(__name__)

#: 返回条目数的服务端上界。与 `retrieval.FUSED_TOP_K` 的关系：前者是**契约层**的
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


def _render_item(item: RetrievedItem) -> dict[str, Any]:
    """把检索结果映射为**返回契约**（资料与案例检索第 3 节）的字段。

    字段名与契约逐字一致：``item_id`` / ``library`` / ``title`` / ``snippet`` /
    ``source`` / ``applicable_scope`` / ``status`` / ``locator`` / ``ranking``。
    **`source` 与 `applicable_scope` 必须带回**（`RQ-CON-03`：输出要能说明适用条件与
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


def _degradation_note(degraded: tuple[str, ...]) -> str | None:
    """把降级事实转成**给模型看的**一句说明（失败语义第 5 节）。

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

    只查资料库，**不混入案例**（契约第 4 节）。撤下、状态、库别三个过滤在
    `modules.library` 的 SQL 层完成，本函数不重复做。

    Returns:
        `ToolResult`：命中条目的 JSON；空结果时**明确写「未找到」**并附
        「不得解释为该做法不存在或没有风险」的提示（契约第 5 节第 4 行）。
        `ToolFailure`：两路都失败时——**绝不返回空列表冒充「未找到」**。
    """
    settings = get_settings()
    limit = args.limit or DEFAULT_RESULT_LIMIT
    # 服务端上界（CORE-11）：契约层已用 `le=MAX_RESULT_LIMIT` 拦住，这里再收一次，
    # 覆盖「绕过参数模型直接调用本函数」的情形（与 store 侧同一纪律）。
    limit = max(1, min(limit, MAX_RESULT_LIMIT))

    try:
        outcome = await _run_search(settings, query=args.query, limit=limit, scope=args.scope)
    except RetrievalError as exc:
        # 两路都失败：明确失败。**消息只给异常类型**，不复述连接串（安全条款）。
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
    payload: dict[str, Any] = {"results": items, "count": len(items)}
    note = _degradation_note(outcome.degraded_paths)
    if note is not None:
        payload["degraded"] = True
        payload["degraded_paths"] = list(outcome.degraded_paths)
        payload["notice"] = note
    if not items:
        # 契约第 5 节第 4 行：检索为空要**明确「未找到」**，且不得解释为
        # 「该做法不存在或没有风险」。这句必须进返回文本，否则模型只能自己猜。
        payload["notice"] = "未找到相关资料。这**不等于**该做法不存在或没有风险——只能说本资料库当前没有可引用的依据。"
    return ToolResult(text=json.dumps(payload, ensure_ascii=False))


async def _run_search(settings: Settings, *, query: str, limit: int, scope: str | None) -> SearchOutcome:
    """装配检索链的依赖并跑一次 `search()`。

    **装配细节**：`search()` 要求一个 `PGVectorStore` 与一个 `embed_query` 可调用。
    向量存储必须注入我们自己的同步/异步引擎（框架要求成对），否则它会另建一套连接池
    ——「撤下与条目在同一事务」的前提就不成立（RAG 策略第 2 节）。
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
                embed_query=embedder.aget_query_embedding,
                limit=limit,
                scope=scope,
            )
    finally:
        # 同步引擎只服务于框架的写入路径，这里只读，用完即关（避免每次调用泄漏连接池）。
        sync_engine.dispose()


__all__ = [
    "DEFAULT_RESULT_LIMIT",
    "MAX_RESULT_LIMIT",
    "SNIPPET_MAX_CHARS",
    "SearchKnowledgeArgs",
    "search_knowledge",
]
