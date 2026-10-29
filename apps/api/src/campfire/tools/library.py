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
from typing import cast

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


async def _result_for(
    context: ToolContext,
    items: list[dict[str, object]],
    degraded_paths: tuple[str, ...],
    *,
    empty_notice: str,
    source: str,
) -> ToolResult:
    """两个检索工具共用的返回打包：发引用凭据 → 拼结果文本 → 交 `ToolResult`。

    抽成一处是因为这几条对外说法（含措辞纪律、引用凭据的两个出口）是同一份契约：
    两处各写一遍，改一处忘另一处就会让其中一个工具悄悄丢掉降级提示或丢掉引用
    ——而「不得把检索不完整说成没有资料」正是靠那句话成立的。

    Args:
        context: 工具上下文；`citations` 是引用写入端。
        items: 本次命中的已渲染条目。
        degraded_paths: 降级事实（哪几路检索不可用）。
        empty_notice: 空结果时给模型的那句话（两库措辞不同）。
        source: 库别标识（`knowledge` / `case`）。

    Returns:
        `ToolResult`：文本 = 契约 JSON（**不含引用载荷**）；`citations` = 本次发出的凭据。
    """
    citations = await _mint_citations(context, items, source=source)
    return ToolResult(
        text=_result_text(
            items,
            degraded_paths,
            empty_notice=empty_notice,
        ),
        citations=citations,
    )


async def _mint_citations(
    context: ToolContext,
    items: list[dict[str, object]],
    *,
    source: str,
):
    """给本次检索命中的条目各发一条引用凭据，返回凭据元组。

    **为什么生产侧必须做这件事**（编号：这不是可选的附赠品）：

    设计《通用基座》第 4 节有两条同时成立的要求——①「每条注入消息在引用索引表里留一条
    对应记录（来源、时间、指向的业务标识），因为输出里的引用要靠它回指」；②不变量
    「没有索引记录的注入消息不得成为『可引用依据』」。而《咨询对话界面》第 5 节要求
    「citation part 与所属消息**同生命周期**……因为它是消息 content 的一部分，
    **不是外部索引**」。

    实测缺口（本包开工前的现状）：整个生产代码里**没有任何一处**调用
    `CitationRecorder.record(...)`——唯一那一处在 `agent/context/injection.py`，
    被 `if item.reference is not None` 守住，而生产侧的 `InjectionItem(...)`
    从不传 `reference`。⇒ 检索是以**工具**形式返回 JSON 文本的，
    第 4 节那条链**整条没接线**：表里不落行、会话里也没有可重建 citation part 的载荷。

    因此本次调用做三件**同一个动作的三个半边**（缺任一半都会造出不一致）：

    1. 经基座的写入端（`context.citations`，即 `CitationRecorder`）发凭据——
       它**先写索引再发凭据**，「拿着凭据却没写索引」在结构上不可表示（第 4 节①）；
    2. 把返回的凭据放进 `ToolResult.citations` ⇒ 运行编排把它翻成 `CitationEvent`
       进**实时事件流**（`agent/runtime/assembly.py` 的 `_invoke`）；
    3. **把凭据留给本次运行的会话写入**（**不是**放进工具结果文本）⇒ 它随助手正文
       落进会话，刷新时由水合从正文分片的 `annotations` 重建出同一个 part。

    ⚠ **第 3 步曾经的做法（T36，已废弃）**是把凭据编进工具结果 JSON 的 `citations` 键。
    它被换掉的原因**只有一个**：工具结果文本是**模型读得到的输入**，而依据区是给使用者
    看的、不是给模型读的（载荷对模型可见会白占上下文，也让模型有机会照抄内部标识）。
    现在由 `agent/runtime/session_annotations.py` 在 `add_items` **落库之前**把凭据挂到
    助手正文分片的 `annotations` 上——「是消息 content 的一部分」由此字面成立，
    且对模型不可见。

    **第 2 与第 3 步缺任一个都会造出「刷新前后不一致」**：只做 3 则实时看不到依据区、
    刷新后才出现；只做 2 则实时可见、刷新后消失（那正是本包要修的现状缺陷）。
    设计第 5 节要的正是「滚动、重放、历史水合都不错位」。

    **来源标识取库别**（`knowledge` / `case`），因为凭据的 `source` 语义是
    「哪个数据通道」，而两个工具各查一个库（契约第 6 节）。

    **回指取 `item_id` 前缀库别**（形如 `knowledge:<uuid>`）：`reference` 的语义是
    「指向的业务标识，权威在业务条目本身」。条目 id 在两库之间不保证全局唯一
    （两张表各有自己的 uuid），因此必须带库别才是**可解析的**回指——
    只给裸 uuid 时，拿到它的人无法知道该去资料库还是案例库查。

    **凭据还要带得出「这条来源是什么状态、适用于谁」**（2026-10-29 补，DEMO-03）：

    依据区要能显示状态徽章（已发表／内部／虚构样例，`RQ-KB-02`）与适用范围
    （`RQ-CON-03`：输出要能说明适用条件与局限），而这两项**只有检索结果里才有**——
    凭据一旦只带 `source`/`reference`/`summary`，界面就永远拿不到它们（缺陷现场：
    载荷六字段、依据区只有一行「来源：knowledge」，状态与适用范围整项缺席）。
    因此这里把条目原值转给凭据：`status` 与 `applicable_scope` **原样透传，缺失即 `None`**
    （呈现方显示「未知」；补默认值等于给查不到状态的来源背书）。

    `withdrawn=False` 与上面两项**性质不同**：它不是快照，而是此刻的核对结论——
    检索链在查询时过滤撤下（第 4 节），所以「能引用」本身就意味着「查到的那一刻未撤下」。
    事后被撤下的情形由读回侧按当前真源重判（面层 `surfaces/consult/citations.py`
    的批量核对），**不是**由这里预判。

    **发往索引失败必须让整次调用失败**（不吞异常）：第 4 节的不变量是
    「没有索引记录的注入消息不得成为可引用依据」。若在这里降级成「无引用」继续返回，
    模型就会看到可以引用的条目、而索引里没有对应行——正是那条不变量要禁止的状态。
    异常照旧由 `ToolSpec.invoke` 转成 `tool_failed` 回给模型（失败语义第 5 节）。

    **为什么返回值不写注解**（这是刻意的，不是漏写）：凭据类型
    `CitationRecord` 定义在 `agent/context/citations.py`，而 `tools/*` 的依赖白名单
    只放行 `campfire.agent.tools`（docs/项目结构设计.md 第 7 节）⇒ **写不出那个类型名**。
    省略返回注解时 mypy 由 `record(...)` 的返回值**推断**出
    `tuple[CitationRecord, ...]`，于是调用方仍然拿到完整类型、且不必 `Any`
    （`ToolResult.citations` 接受的正是这个类型，实测通过）。
    给列表写空字面量注解或 `# type: ignore` 都是更差的选项：前者要写出类型名，
    后者会把真实的类型错误一起吞掉。

    Args:
        context: 工具上下文；`citations` 是引用写入端。
        items: 本次命中的已渲染条目（含 `item_id`）。
        source: 库别标识（`knowledge` / `case`）。

    Returns:
        发出的凭据（按命中顺序）；没有可回指条目时为空元组。
    """
    # 先算出「可回指的条目」，再统一发凭据：`record` 是异步的，推导式里 await 要求
    # 列表推导（3.12 起支持）——但那样会把「缺 id ⇒ 跳过」的警告埋进表达式里，
    # 因此先过滤成 `targets` 再做映射，判据与告警都在一眼可见的地方。
    targets: list[dict[str, object]] = []
    for item in items:
        item_id = item.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            # 没有条目 id 就无法回指（契约第 3 节把 `item_id` 列为必带）。
            # 不猜、不编造回指：跳过这一条，而不是产出一条指不到东西的依据。
            logger.warning("检索结果缺少条目标识，跳过它的引用：%s", sorted(item))
            continue
        targets.append(
            {
                "item_id": item_id,
                # 摘要取标题：它是使用者能在「依据」区一眼认出那条来源的最短信息。
                "summary": _text_or_none(item.get("title")),
                # 状态与适用范围**照条目原值透传**（`RQ-KB-02`、`RQ-CON-03`）：
                # 缺就留 `None`，由呈现方显示「未知」，不补默认值——补成 published
                # 等于替一条查不到状态的来源背书。
                "status": _text_or_none(item.get("status")),
                "applicable_scope": _text_or_none(item.get("applicable_scope")),
            }
        )

    records = [
        await context.citations.record(
            source=source,
            # 回指带库别前缀（形如 `knowledge:<uuid>`）：条目 id 在两库之间不保证全局
            # 唯一（两张表各有自己的 uuid），只给裸 uuid 时拿到它的人无法知道该去哪个
            # 库查——那就不再是「可解析的回指」。
            reference=f"{source}:{target['item_id']}",
            summary=cast(str | None, target["summary"]),
            status=cast(str | None, target["status"]),
            applicable_scope=cast(str | None, target["applicable_scope"]),
            # 这一次能引用它，说明检索链刚刚按「未撤下」查到了它（第 4 节：检索在查询时
            # 过滤撤下）。因此 `False` 是**当下核对过的事实**，不是默认值；
            # 事后是否被撤下由读回侧（面层）按当前真源重判，见 `surfaces/consult/citations.py`。
            withdrawn=False,
        )
        for target in targets
    ]
    return tuple(records)


def _text_or_none(value: object) -> str | None:
    """取一个可展示的文本值：非字符串或全空白时返回 `None`。

    为什么不用 `str(value)`：`None` 会被转成字符串 `"None"` 并当成真状态呈现出去，
    那是编造。空白同理——「空字符串」在界面上与「没有这项」无法区分。
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


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
    return await _result_for(
        context,
        items,
        outcome.degraded_paths,
        empty_notice="未找到相关资料。这**不等于**该做法不存在或没有风险——只能说本资料库当前没有可引用的依据。",
        source=LIBRARY_KNOWLEDGE,
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
    return await _result_for(
        context,
        items,
        outcome.degraded_paths,
        empty_notice=("未找到相关案例。这**不等于**没有其他家庭遇到过类似情形——只能说本案例库当前没有可引用的记录。"),
        source=LIBRARY_CASE,
    )


def _result_text(
    items: list[dict[str, object]],
    degraded_paths: tuple[str, ...],
    *,
    empty_notice: str,
) -> str:
    """两个检索工具共用的结果文本打包：条目、条数、降级说明、空结果提示。

    抽出一处是因为这几条对外说法（含措辞纪律）是同一份契约：两处各写一遍，
    改一处忘另一处就会让其中一个工具悄悄丢掉降级提示——而「不得把检索不完整
    说成没有资料」正是靠那句话成立的。

    **降级说明与空结果提示必须并存**（2026-10-29 审查修正）：此前是
    `if note: payload["notice"] = note` 之后再 `if not items: payload["notice"] = empty_notice`
    ——后一句把前一句**覆盖**掉。于是「单路失败 + 没有命中」这最危险的一格，
    模型收到的 notice 只剩「未找到相关资料……只能说本资料库当前没有可引用的依据」，
    而契约第 5 节要求它在此不得声称「没有相关资料」（可能是语义检索坏了）。
    现在两条都在：降级说明在前（说明结果不完整），空结果提示在后（说明不得过度解读）。

    **引用载荷不在这里**（T38 起）：这段文本是**模型读得到**的输入，而依据区是给使用者
    看的。凭据经 `ToolResult.citations` 出去（事件流 + 会话写入），不混进给模型的 JSON。
    这也让工具结果回到「纯粹是检索结果的结构化文档」这一个职责上。
    """
    payload: dict[str, object] = {"results": items, "count": len(items)}
    notices: list[str] = []
    note = _degradation_note(degraded_paths)
    if note is not None:
        payload["degraded"] = True
        payload["degraded_paths"] = list(degraded_paths)
        notices.append(note)
    if not items:
        # 契约第 5 节第 4 行：检索为空要明确「未找到」，且不得解释为
        # 「该做法不存在或没有风险」。这句必须进返回文本，否则模型只能自己猜。
        notices.append(empty_notice)
    if notices:
        payload["notice"] = "\n".join(notices)
    return json.dumps(payload, ensure_ascii=False)


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
