"""B 组：受控 RAG 基线（同底座 + 产品真实检索链 + 基本引用约定，无业务编排）。

职责：每轮先用**产品自己的检索链**（`modules/library.search`：向量路 + 字面路 + RRF 融合 +
条目聚合）取回材料，把它们作为证据块放进 system 提示，然后一次完成调用。

边界：不接 Skill、不接工具池、不做多轮工具编排——那是 C 组的处理。B 组要验证的是
「知识增强本身」能带来多少，因此它的全部增量必须可追溯到「检索到的这些材料」。

为什么直接调 `modules/library` 而不是调 `tools.search_knowledge`：
后者是**给模型用的工具**（含 ToolContext、引用写入端与面向模型的降级话术）。
B 组的检索由本工具在调用模型之前发起，没有工具上下文；复用检索链本身才是「同一检索能力」，
复用工具包装层反而要多造一份假上下文。装配细节（引擎、嵌入器、会话）与
`tools/library.py::_run_search` 逐项一致，理由见该函数的 docstring。

公平性：B 与 A 的 system 提示只差「证据使用纪律」一段（协议 05 第 4 节把「基本引用约定」
列为 B 组的允许增量）。两组的使用者文本逐字节相同，见 `prompts.render_user_turn`。
"""

from __future__ import annotations

from typing import Any

from campfire.core.config import Settings

from .. import prompts
from ..cases import Case
from ..faults import FaultPlan
from .base import TurnInput
from .chat import ChatSystem

#: 单条证据进提示的字符上界。与产品的 `SNIPPET_MAX_CHARS` 同值：B 组看到的是产品检索链会
#: 返回的同一批材料，长度口径不一致会让「同样的检索结果」在两组间呈现不同体量。
SNIPPET_MAX_CHARS = 1200

#: 检索词的长度上界（对齐 `SearchKnowledgeArgs.query` 的契约上限）。
QUERY_MAX_CHARS = 500


def build_retrieval_query(case: Case, turn: int) -> str:
    """用「背景 + 本轮问题」拼检索词（截到契约上限）。

    只取问题会丢掉情境关键词（例如「商场里捂耳朵哭闹」），只取背景会丢掉这一轮真正在问
    什么。两者拼接是 RAG 的常规做法，且对三组都是**同一份**输入——它不影响公平性，
    因为 A/C 都不使用检索词。
    """
    merged = f"{case.shared_context.strip()}\n{case.message_for_turn(turn).strip()}"
    return merged[:QUERY_MAX_CHARS]


def evidence_sha256(text: str) -> str:
    """证据块正文的 hash（进轨迹：事后可复算「模型当时看到的那段证据」）。"""
    from ..hashing import sha256_text

    return sha256_text(text)


def render_evidence(items: list[Any], degraded: tuple[str, ...]) -> str:
    """把检索结果渲染成证据块（含出处与适用范围，缺信息如实写明）。"""
    lines: list[str] = [prompts.EVIDENCE_HEADING]
    if degraded:
        lines.append(
            "（注意：本次检索有一路不可用（" + "、".join(degraded) + "），结果不完整。不得据此声称「没有相关资料」。）"
        )
    if not items:
        lines.append(prompts.EVIDENCE_EMPTY)
        return "\n".join(lines)

    for index, item in enumerate(items, start=1):
        snippet = item.snippet if len(item.snippet) <= SNIPPET_MAX_CHARS else item.snippet[:SNIPPET_MAX_CHARS]
        truncated = "（已截断）" if len(item.snippet) > SNIPPET_MAX_CHARS else ""
        lines.append(
            f"[{index}] 标题：{item.title}\n"
            f"    出处：{item.source}\n"
            f"    适用范围：{item.applicable_scope}\n"
            f"    摘要：{snippet}{truncated}"
        )
    return "\n".join(lines)


class RagBaseline(ChatSystem):
    """B 组适配器。"""

    system_id = "B"

    def __init__(self, *, settings: Settings, config: Any, gateway: Any, faults: FaultPlan) -> None:
        """绑定配置、网关与注入计划。"""
        super().__init__(settings=settings, config=config, gateway=gateway)
        self._faults = faults

    @property
    def assembly_note(self) -> str:
        """装配说明（进 manifest）。"""
        return (
            "同一模型客户端 + 产品检索链（modules/library.search，向量路+字面路+RRF，"
            "知识库单库、同一快照）+ 基本引用约定；无 Skill、无工具池、无多轮编排"
        )

    def system_prompt(self, *, evidence: str | None) -> str:
        """共同任务边界 + 证据使用纪律 +（本轮）证据块。"""
        base = f"{prompts.COMMON_TASK_INSTRUCTIONS}\n{prompts.RAG_EVIDENCE_INSTRUCTIONS}"
        if evidence:
            return f"{base}\n{evidence}"
        return base

    async def build_evidence(self, request: TurnInput) -> tuple[str | None, dict[str, Any]]:
        """跑一次真实检索并渲染证据块；同时给出可审计的检索轨迹。

        三种结局都如实记录在轨迹里：`ok` / `degraded`（一路不可用）/ `unavailable`（两路都失败）。
        注入的故障（`retrieval_empty` / `retrieval_unavailable`）在这里**真实生效**：
        前者跳过检索，后者跳过并声明不可用。
        """
        case = request.case
        if self._faults.active(case.id, "B", "retrieval_unavailable"):
            text = render_evidence([], ()).replace(prompts.EVIDENCE_EMPTY, "（本次检索服务不可用，没有取到任何材料。）")
            return (
                text,
                {
                    "status": "unavailable",
                    "injected": "retrieval_unavailable",
                    "query": None,
                    "items": [],
                    "citations": [],
                    "evidence_text_sha256": evidence_sha256(text),
                    "evidence_text_chars": len(text),
                },
            )
        if self._faults.active(case.id, "B", "retrieval_empty"):
            text = render_evidence([], ())
            return (
                text,
                {
                    "status": "injected_empty",
                    "injected": "retrieval_empty",
                    "query": None,
                    "items": [],
                    "citations": [],
                    "evidence_text_sha256": evidence_sha256(text),
                    "evidence_text_chars": len(text),
                },
            )

        query = build_retrieval_query(case, request.turn)
        try:
            outcome = await run_product_search(self._settings, query=query, limit=self._config.retrieval_top_k)
        except Exception as exc:  # noqa: BLE001 —— 检索失败必须显式标注，不得冒充「未找到」
            return (
                render_evidence([], ()).replace(prompts.EVIDENCE_EMPTY, "（本次检索失败，没有取到任何材料。）"),
                {
                    "status": "unavailable",
                    "error_type": type(exc).__name__,
                    "query": query,
                    "items": [],
                    "citations": [],
                },
            )

        citations = [
            {"source": "retrieval", "reference": f"knowledge:{item.item_id}", "summary": item.title}
            for item in outcome.items
        ]
        rendered = render_evidence(outcome.items, outcome.degraded_paths)
        trace = {
            "status": "degraded" if outcome.degraded_paths else "ok",
            "degraded_paths": list(outcome.degraded_paths),
            "query": query,
            "items": [
                {
                    "item_id": item.item_id,
                    "title": item.title,
                    "source": item.source,
                    "applicable_scope": item.applicable_scope,
                    "status": item.status,
                    "locator": item.locator,
                    "ranking": dict(item.ranking),
                    "snippet_chars": len(item.snippet),
                }
                for item in outcome.items
            ],
            "citations": citations,
            "evidence_text_sha256": evidence_sha256(rendered),
            "evidence_text_chars": len(rendered),
        }
        return rendered, trace


async def run_product_search(settings: Settings, *, query: str, limit: int) -> Any:
    """跑一次产品检索链（装配方式与 `tools/library.py::_run_search` 逐项一致）。

    为什么逐项照抄装配而不抽一个共享函数：产品侧那个函数是模块内私有函数，跨包引用它
    会把评测工具绑到产品私有实现上（一次重构就让评测炸）。这里保留同一套步骤，
    并用集成测试（真实库）核对两边的检索结果一致。
    """
    from campfire.core.db import create_sync_engine, get_engine, session_scope
    from campfire.modules.library.embedding import build_embedding
    from campfire.modules.library.ingestion import build_vector_store
    from campfire.modules.library.models import LIBRARY_KNOWLEDGE
    from campfire.modules.library.retrieval import search

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
                library=LIBRARY_KNOWLEDGE,
                embed_query=embedder.aget_query_embedding,
                limit=limit,
            )
    finally:
        sync_engine.dispose()


__all__ = ["QUERY_MAX_CHARS", "SNIPPET_MAX_CHARS", "RagBaseline", "build_retrieval_query", "render_evidence"]
