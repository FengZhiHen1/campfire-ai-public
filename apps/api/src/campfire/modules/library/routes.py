"""资料库面的 HTTP 路由：两库浏览与检索、条目就地展开、deep-link 三态。

职责：把 `modules/library` 的检索链（`retrieval.search` / `retrieval.browse`）与节点投影
暴露成资料库面契约的 HTTP 形状，并实现 deep-link 的在库/撤下/不存在三态。
边界：只做 HTTP 形状、参数校验、展开内容的组装与错误码映射——两路检索、RRF 融合、
      条目聚合、撤下与状态过滤都在检索链里；本模块不直接构造 SQL、不写入任何东西。
参考：docs/技术设计/面/profile/资料库面HTTP契约.md 第 2～6 节；
      docs/技术设计/technical-details/资料与案例检索.md 第 3、4、5 节；
      docs/技术设计/technical-details/公共案例库.md 第 4、5、8 节。

为什么路由放在本模块而不是 `surfaces/`（本包裁决 1）：项目的「面」指产品入口与
Agent 运行装配（docs/项目结构设计.md 第 5 节），而资料库面不装配 skill 与工具池，
它只是本模块用例的 HTTP 皮肤——与认证不建面同构。

为什么本面只有读端点（契约第 1 节）：`RQ-KB-03` 与 `AC-29` 已定资料与案例的导入、
审核与知识库管理**只能**经应用内 CLI，不存在对应的 HTTP 端点与产品内界面。
撤下由 CLI 打 `withdrawn` 标记，本面只负责「撤下后不再返回」。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from supertokens_python.recipe.session import SessionContainer

from campfire.core.auth.supertokens import require_session
from campfire.core.config import get_settings
from campfire.core.db import create_sync_engine, get_engine, session_scope
from campfire.modules.library.case_schema import (
    OPTIONAL_CARD_STRINGS,
    REQUIRED_CARD_ARRAYS,
    REQUIRED_CARD_BOOLS,
    REQUIRED_CARD_STRINGS,
)
from campfire.modules.library.ingestion import build_vector_store
from campfire.modules.library.models import ITEM_MODELS, LIBRARIES, LIBRARY_CASE, LIBRARY_KNOWLEDGE, CaseItem
from campfire.modules.library.retrieval import (
    RetrievalError,
    RetrievedItem,
    SearchOutcome,
    browse,
    expand_items_to_nodes,
    load_items,
    search,
)

router = APIRouter(prefix="/library", tags=["library"])

#: 单页条数的默认值与上界（本包裁决 8：资料库取与会话列表一致的 50 档）。
#:
#: 契约只写「`limit` 未传时服务端必须有上界」，未给数值。上限存在的理由是
#: CORE-11：无界拉取会随语料增长；默认 20 与会话列表同档（HTTP/SSE 契约第 3.2 节），
#: 避免同一产品里出现两套分页尺度。
ITEMS_DEFAULT_LIMIT = 20
ITEMS_MAX_LIMIT = 50

#: 浏览路可翻页的总窗口（CORE-11）。游标是本面自定的偏移量：检索链只接 `limit`
#: （不接「从某条之后」的谓词），面层无法把键集条件下推到 SQL；硬做只会得到
#: 「看起来是键集、实际是全量重排」的分页。代价是深翻页要多读若干行，因此配上
#: 硬上界，超过它之后 `next_cursor` 为 null。
PAGE_WINDOW_MAX = 500

#: 卡片里被推断字段的键名（公共案例库第 4 节）。`_inferred` 的**内容**不参与
#: 检索注入，因此它不在节点文本里；被推断字段的**清单**在 metadata 上。
_INFERRED_METADATA_KEY = "inferred_fields"

#: 卡片节点文本里「字段名：值」的分隔符（`case_schema.build_card_embedding_text`）。
_FIELD_SEPARATOR = "："

#: 卡片上不参与嵌入的字段（`case_schema.CARD_NON_EMBEDDED_FIELDS` 的子集）：
#: 标识字段无检索语义，`_inferred` 不参与注入，因此它们不出现在节点文本里。
#: 展开时这些字段分别从 metadata（`card_id`/`inferred_fields`）补回。
_NON_EMBEDDED_CARD_KEYS: frozenset[str] = frozenset({"card_id", "case_id", "raw_id", "_inferred"})

#: 可从节点文本恢复的卡片字段（＝嵌入字段减去不可嵌入键）。
#: 由 `case_schema` 的字段清单派生而不是另写一份：少写一个字段会让它静默缺失。
PARSABLE_CARD_KEYS: tuple[str, ...] = tuple(
    key
    for key in (*REQUIRED_CARD_STRINGS, *REQUIRED_CARD_ARRAYS, *REQUIRED_CARD_BOOLS, *OPTIONAL_CARD_STRINGS)
    if key not in _NON_EMBEDDED_CARD_KEYS
)


# ---------------------------------------------------------------------------
# 会话依赖
# ---------------------------------------------------------------------------


async def current_account(session: SessionContainer | None = Depends(require_session())) -> str:
    """从登录态取得当前账号标识。

    本面的数据是公共语料（两库对所有登录使用者一致），因此账号**不参与取数**；
    它的作用是「必须登录」这一条（契约第 2 节：全部端点须登录，`RQ-ACC-01`）。
    保留依赖而不是省略，是为了让「这条路径确实要求登录」在代码里可见——
    省略它会让端点变成匿名可达，而那与 `RQ-ACC-01` 冲突。

    Args:
        session: SDK 注入的会话容器；`session_required=True` 时必不为 None。

    Returns:
        账号标识。

    Raises:
        RuntimeError: 会话容器缺失（`session_required=True` 下不可达）。
    """
    if session is None:  # pragma: no cover —— session_required=True 时不可达
        raise RuntimeError("require_session 返回了空会话：拒绝按无账号处理请求")
    return session.get_user_id()


# ---------------------------------------------------------------------------
# 错误映射
# ---------------------------------------------------------------------------


def _error(status_code: int, message: str, code: str) -> JSONResponse:
    """构造带机器可读 code 的错误响应（与档案面、记忆面同一形状）。"""
    return JSONResponse(status_code=status_code, content={"detail": message, "code": code})


def _unavailable() -> JSONResponse:
    """检索不可用 → 503（契约第 6 节）。

    关键区分：**两路检索都失败**才走这里，返回 503；检索为空是 200 空数组。
    两者不得混同——把失败报成「没有找到相关内容」会让使用者以为库里没有依据，
    而真相是检索坏了（契约第 6 节的硬性区分）。文案只给类别，不复述连接串与凭据。
    """
    return _error(503, "检索暂时不可用", "retrieval_unavailable")


def _parse_cursor(cursor: str | None) -> int | None:
    """把游标解析成偏移量；None 表示非法（由调用方转 422）。"""
    if cursor is None:
        return 0
    if not cursor.isdigit():
        return None
    return int(cursor)


# ---------------------------------------------------------------------------
# 载荷模型
# ---------------------------------------------------------------------------


class NarrativeSectionPayload(BaseModel):
    """叙事小节（契约第 4 节：`{ key, heading, text }`）。"""

    key: str
    heading: str
    text: str


class NarrativePayload(BaseModel):
    """条目展开时的 narrative（五节，见公共案例库第 3 节）。"""

    sections: list[NarrativeSectionPayload]


class CaseCardPayload(BaseModel):
    """展开时的一张卡片（契约第 4 节）。

    高风险字段（`immediate_action`、`medical_criteria`、`contraindications`、
    `caution_notes`）照旧返回，但呈现纪律不在本面：它们只能以转述语呈现、
    涉及医疗处置须引导求助，该纪律在 skill 与页面呈现层执行，本契约不拦截
    （契约第 4 节，与 `RQ-LIM-05` 同源：提示词层不构成安全边界）。
    """

    card_id: str
    title: str | None = None
    scenario: str | None = None
    immediate_action: str | None = None
    inferred_fields: list[str]
    risk_class: str
    behavior_type: str | None = None
    severity_level: str | None = None
    setting: str | None = None
    parent_category: str | None = None
    age_range: str | None = None
    ebp_tags: str | None = None
    comforting_phrase: str | None = None
    observation_metrics: str | None = None
    medical_criteria: str | None = None
    contraindications: str | None = None
    caution_notes: str | None = None
    is_template: str | None = None


class LibraryItemPayload(BaseModel):
    """列表里的一个条目（契约第 3.1 节）。

    共有八项恒在场；案例的六项必带字段与 `inferred_fields` 只在 `library = case`
    时填充（资料侧为 `None`）。六项必带**不是可选装饰**：缺任一个，页面就无法
    如实回答「谁说的、多可信、什么时候」，列表就退化为无法核对的读物（`AC-06`）。

    `narrative` 与 `cards` 只在 `expand` 命中该条目时出现——展开内容随列表一并返回
    （页面无详情页，契约第 4 节），因此不另发一次请求。
    """

    item_id: str
    library: str
    title: str
    snippet: str
    source: str
    applicable_scope: str
    status: str
    locator: str
    ranking: dict[str, Any]
    authorization: str | None = None
    source_type: str | None = None
    evidence_level: str | None = None
    review_status: str | None = None
    interview_at: datetime | None = None
    makes_claims_high_risk: bool | None = None
    inferred_fields: list[str] | None = None
    narrative: NarrativePayload | None = None
    cards: list[CaseCardPayload] | None = None


class LibraryItemsPayload(BaseModel):
    """浏览与检索响应（契约第 3 节）。

    `degraded_paths` 是契约未点名但必需的一个字段：契约第 6 节要求「单路失败 →
    200，结果内标注降级」，而检索链把降级事实放在 `SearchOutcome`（不放在条目里）——
    响应体若不带上它，调用方拿到 200 就无从知道结果是不完整的。取值为不可用的
    检索路（`vector` / `literal`）的子集，空表示两路都正常。
    """

    library: str
    items: list[LibraryItemPayload]
    next_cursor: str | None
    degraded_paths: list[str]


class GetLibraryItemPayload(BaseModel):
    """deep-link 单条查询响应（契约第 5 节）。

    三态：
    - 在库：`item` 为完整条目，`withdrawn` 为假；
    - 已撤下：`item` 为 `null`、`withdrawn` 为真、只带 `title`（不带正文与其他字段）；
    - 不存在或非法 id：**404**（不是本模型能表达的，走 `_error`）。

    已撤下返回 200 而不是 404，且只带标题：页面据此渲染单条撤下卡（标题 +
    「该来源已撤下」），不显示正文。撤下条目不进列表，只在这种定向查询下以
    一种克制形态出现（`RQ-KB-04`：撤下即消失，无「已撤下」幽灵条目）。
    """

    item: LibraryItemPayload | None = None
    withdrawn: bool = False
    title: str | None = None


# ---------------------------------------------------------------------------
# 卡片与叙事：从节点投影恢复展开内容
# ---------------------------------------------------------------------------


def _parse_card_fields(text: str) -> dict[str, str]:
    """把卡片的嵌入文本还原成 `{字段名: 值}`。

    为什么可以从节点文本还原：卡片整卡是一个节点，它的 `text` 就是
    `case_schema.build_card_embedding_text(card)` 的产物——逐字段
    「字段名：值」拼接，字段边界被刻意保留（RAG 策略第 1.3 节）。因此
    `scenario` / `immediate_action` / `medical_criteria` 一类字段的**原文**
    在节点里是可得的；条目表只存了案例级字段，不存卡片级字段。

    解析按**已知字段名**起新行，而不是按换行无条件切：卡片字段的值可能本身
    含换行，按换行切会把一个字段拆成两半、并把后半段丢成「未知键」，那是静默
    丢内容。已知字段名来自 `case_schema` 的字段清单（`PARSABLE_CARD_KEYS`）。

    Returns:
        字段名 → 值（字符串形式，列表值以「、」相连、布尔值为「是」/「否」，
        与写入时同一渲染规则）。未出现在文本里的字段不出现在结果里。
    """
    fields: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []

    def _flush() -> None:
        if current is not None:
            fields[current] = "\n".join(buffer).strip()

    for line in text.splitlines():
        matched = next(
            (key for key in PARSABLE_CARD_KEYS if line.startswith(f"{key}{_FIELD_SEPARATOR}")),
            None,
        )
        if matched is not None:
            _flush()
            current = matched
            buffer = [line[len(matched) + len(_FIELD_SEPARATOR) :]]
        elif current is not None:
            buffer.append(line)
    _flush()
    return fields


def _card_risk_class(fields: dict[str, str]) -> str:
    """按字段级默认档判卡片的风险档：`high` / `low`。

    这是对契约 `risk_class`（`low | mixed | high`）的**面层派生**，不是存储值
    ——`case_ingestion._card_metadata` 未把 `risk_class` 写进节点 metadata，
    条目表也没有该列，因此库里查不到它。派生的判据取该模块自己已发布的规则：
    `medical_criteria` 或 `contraindications` 非空即视为高风险（
    `_card_is_high_risk` 的判据，其 docstring 明确 `caution_notes` 单独出现
    不抬高整卡等级）。

    只产出 `low` / `high` 两档：`mixed` 在设计中没有任何判据（公共案例库第 5 节
    只说最终逐条判断在 skill 层完成），编一个「混合」的判据就是在发明规则。
    该缺口登记在交付报告的未决问题节。`risk_class` 本身只是提示与过滤维度，
    不是安全边界（同节：真实闸门是 `EVID-A` 与 `EVID-B`）。
    """
    for key in ("medical_criteria", "contraindications"):
        value = fields.get(key, "")
        if value.strip() and value.strip() != "无":
            return "high"
    return "low"


def _cards_from_nodes(nodes: list[tuple[str, str, dict[str, str]]]) -> list[CaseCardPayload]:
    """把卡片节点投影还原成展开用的卡片清单。

    只取 `node_kind = card` 的节点：同一节点表也装叙事小节，混进来会让展开区
    出现两条一模一样的「场景背景」。
    """
    cards: list[CaseCardPayload] = []
    for _node_id, text, metadata in nodes:
        if metadata.get("node_kind") != "card":
            continue
        fields = _parse_card_fields(text)
        raw_inferred = metadata.get(_INFERRED_METADATA_KEY)
        inferred = [str(entry) for entry in raw_inferred] if isinstance(raw_inferred, list) else []
        cards.append(
            CaseCardPayload(
                card_id=str(metadata.get("card_id") or ""),
                title=metadata.get("title") or fields.get("title"),
                scenario=fields.get("scenario"),
                immediate_action=fields.get("immediate_action"),
                inferred_fields=inferred,
                risk_class=_card_risk_class(fields),
                behavior_type=fields.get("behavior_type"),
                severity_level=fields.get("severity_level"),
                setting=fields.get("setting"),
                parent_category=fields.get("parent_category"),
                age_range=fields.get("age_range"),
                ebp_tags=fields.get("ebp_tags"),
                comforting_phrase=fields.get("comforting_phrase"),
                observation_metrics=fields.get("observation_metrics"),
                medical_criteria=fields.get("medical_criteria"),
                contraindications=fields.get("contraindications"),
                caution_notes=fields.get("caution_notes"),
                is_template=fields.get("is_template"),
            )
        )
    return cards


def _narrative_from_nodes(nodes: list[tuple[str, str, dict[str, str]]]) -> NarrativePayload:
    """把叙事节点投影还原成展开用的五节。

    `key` 取节名本身：契约只给 `{ key, heading, text }` 三键、未定命名规则，
    而节名是唯一稳定且可读的标识（叙事五节由 `case_ingestion.NARRATIVE_SECTIONS`
    固定，`locator` 也是按它拼的）。前端把它当折叠区的稳定键即可。
    `heading` 从 `locator`（形如 `/场景背景/`）剥出。
    """
    sections: list[NarrativeSectionPayload] = []
    for _node_id, text, metadata in nodes:
        if metadata.get("node_kind") != "narrative":
            continue
        locator = str(metadata.get("locator") or "")
        heading = locator.strip("/").split("/")[-1] if locator.strip("/") else ""
        sections.append(NarrativeSectionPayload(key=heading, heading=heading, text=text))
    return NarrativePayload(sections=sections)


# ---------------------------------------------------------------------------
# 条目装配
# ---------------------------------------------------------------------------


def _item_payload(item: RetrievedItem) -> LibraryItemPayload:
    """把聚合后的条目转成对外形状（契约第 3.1 节）。

    逐字段透传，不裁剪、不补默认值：缺来源或状态的条目在检索链里就不进结果
    （不变量），因此走到这里的条目一定有来源与状态——若此处出现空值，那是
    检索链的缺陷，不是本面该兜的。

    案例专属字段按**库别**判定在场，不按取值真假：`inferred_fields` 在
    「案例但没有卡片级推断」时是一个**空列表**，而资料侧根本不是案例。
    若用 `if item.inferred_fields else None`，空列表会被静默转成 `None`，
    于是「这条案例没有推断字段」与「这条不是案例」在响应里变得无法区分——
    而前端要据此决定是否渲染推断标注。
    """
    is_case = item.library == LIBRARY_CASE
    return LibraryItemPayload(
        item_id=item.item_id,
        library=item.library,
        title=item.title,
        snippet=item.snippet,
        source=item.source,
        applicable_scope=item.applicable_scope,
        status=item.status,
        locator=item.locator,
        ranking=dict(item.ranking),
        authorization=item.authorization,
        source_type=item.source_type,
        evidence_level=item.evidence_level,
        review_status=item.review_status,
        interview_at=item.interview_at,
        makes_claims_high_risk=item.makes_claims_high_risk,
        inferred_fields=list(item.inferred_fields) if is_case else None,
    )


async def _attach_expansion(
    session: Any,  # noqa: ANN401 —— AsyncSession；避免为一个内部签名引入类型导入
    payloads: list[LibraryItemPayload],
    *,
    expand: str,
) -> None:
    """把 `expand` 指向的那一条的展开内容附上（原地修改）。

    一次只展开一条（页面是单条就地展开，契约第 4 节）。`expand` 命中本页的
    条目时附上 narrative 与 cards；未命中（例如它在下一页）不附任何内容——
    这不是错误：调用方刷新列表时目标可能不在当前页。
    """
    target = next((payload for payload in payloads if payload.item_id == expand), None)
    if target is None:
        return
    nodes = await expand_items_to_nodes(session, [expand])
    rows = nodes.get(expand, [])
    target.narrative = _narrative_from_nodes(rows)
    target.cards = _cards_from_nodes(rows)


async def _run_retrieval(
    *,
    library: str,
    query: str,
    limit: int,
) -> SearchOutcome:
    """跑一次浏览或检索。

    空查询走全量浏览路（按最近入库排序），非空查询走两路检索 —— 由
    `retrieval.search` 自己分流，但它要求一个 `vector_store` 参数；浏览路
    根本不用向量存储，因此这里在空查询时直接调 `retrieval.browse`
    （同为公开入口），避免为一次全表浏览装配一套连接池与嵌入客户端。

    Raises:
        RetrievalError: 库别非法，或两路检索都失败。
        EmbeddingConfigurationError: 缺嵌入凭据（非空查询才可能）。
        RuntimeError: 未配置 `DATABASE_URL`。
    """
    settings = get_settings()
    if not query.strip():
        async with session_scope(settings) as session:
            return await browse(session, library=library, limit=limit)

    # 非空查询才装配向量存储与嵌入器：两者都要建连接池与 http 客户端。
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
            )
    finally:
        # 同步引擎只服务于框架的组件构造，这里只读，用完即关（否则每次调用泄漏连接池）。
        sync_engine.dispose()


# ---------------------------------------------------------------------------
# 浏览与检索（契约第 3、4 节）
# ---------------------------------------------------------------------------


@router.get("/items", response_model=LibraryItemsPayload)
async def list_items(
    _account_id: Annotated[str, Depends(current_account)],
    library: Annotated[str, Query(description="库别：case | knowledge")] = LIBRARY_CASE,
    query: Annotated[str, Query(description="检索词；空即全量浏览流")] = "",
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=ITEMS_MAX_LIMIT)] = ITEMS_DEFAULT_LIMIT,
    expand: Annotated[str | None, Query(description="就地展开的条目标识，一次一条")] = None,
) -> LibraryItemsPayload | JSONResponse:
    """浏览或检索两库之一（契约第 3 节）。

    三件事由检索链保证，本函数不重复做：两库分开取数（`RQ-KB-01`）、撤下与状态
    在 SQL 内过滤、缺来源或状态的条目不进入结果（不补默认值）。

    `library` 缺省为 `case`：页面默认落在案例分区（契约第 3 节）。非法取值 →
    422，不静默退回资料库——那会让案例检索拿到资料条目并当成案例呈现。

    `query` 为空即全量浏览流，按最近入库排序：不编造「热门」排序（案例库浏览页
    第 40 行：无真实行为数据支撑排序策略前只用时间序）。

    Args:
        library: 库别，取值见 `LIBRARIES`。
        query: 检索词；空即浏览。
        cursor: 上一页返回的游标。
        limit: 单页条数，上界 `ITEMS_MAX_LIMIT`。
        expand: 要就地展开的条目标识（一次一条）。

    Returns:
        `LibraryItemsPayload`；`degraded_paths` 非空时结果不完整（契约第 6 节）。

    Raises（对外映射）:
        422: `library` 未知、`cursor` 非法、`limit` 越界（由 FastAPI 的查询校验拒绝），
            或 `expand` 不是合法标识、或它属于另一个库。
        503: 检索不可用（两路都失败、缺嵌入凭据），或未配置数据库。
    """
    if library not in LIBRARIES:
        return _error(422, f"未知的库别：{library!r}，合法取值：{sorted(LIBRARIES)}", "invalid_payload")

    offset = _parse_cursor(cursor)
    if offset is None:
        return _error(422, "cursor 不是本面发出的游标", "invalid_payload")

    if expand is not None:
        problem = await _check_expand_target(expand, library=library)
        if problem is not None:
            return problem

    window = min(offset + limit + 1, PAGE_WINDOW_MAX)
    try:
        outcome = await _run_retrieval(library=library, query=query, limit=window)
    except RetrievalError:
        return _unavailable()
    except RuntimeError:
        return _unavailable()
    except Exception as exc:  # noqa: BLE001 —— 嵌入配置与装配失败同样不得冒充「未找到」
        # 只把已知的「未配置凭据」这一类转成 503；其余异常继续冒泡
        # ——把未知缺陷报成「检索暂时不可用」会掩盖真实的程序错误。
        from campfire.modules.library.embedding import EmbeddingConfigurationError

        if isinstance(exc, EmbeddingConfigurationError):
            return _unavailable()
        raise

    # 浏览路是可按游标翻页的流；检索路是融合后的 top-K 名次列表——它没有
    # 「第 K 名之后」的谓词（检索链只接 limit），因此不假装能翻页。
    is_browse = not query.strip()
    page = outcome.items[offset : offset + limit] if is_browse else outcome.items
    has_more = is_browse and len(outcome.items) > offset + limit

    payloads = [_item_payload(item) for item in page]
    if expand is not None:
        try:
            async with session_scope(get_settings()) as session:
                await _attach_expansion(session, payloads, expand=expand)
        except RetrievalError:
            # 展开失败不改变「列表已取到」这一事实：这是单条附加内容缺失，
            # 不是检索失败。返回列表（不带展开）比 503 更如实。
            pass

    return LibraryItemsPayload(
        library=library,
        items=payloads,
        next_cursor=str(offset + limit) if has_more else None,
        degraded_paths=list(outcome.degraded_paths),
    )


async def _check_expand_target(expand: str, *, library: str) -> JSONResponse | None:
    """校验 `expand` 指向的条目属于本次请求的库。

    非法标识 → 422；属于**另一个库** → 422（该库的列表里永远不会出现它，
    静默忽略会让调用方以为「展开没生效」是渲染问题）。属于本库但不在当前页
    → 返回 None（由 `_attach_expansion` 安静跳过，那是正常的翻页情形）。

    Returns:
        需要拒绝时返回错误响应；可以继续时返回 `None`。
    """
    try:
        item_uuid = uuid.UUID(expand)
    except ValueError:
        return _error(422, "expand 不是合法的条目标识", "invalid_payload")

    other = LIBRARY_KNOWLEDGE if library == LIBRARY_CASE else LIBRARY_CASE
    model = ITEM_MODELS[other]
    async with session_scope(get_settings()) as session:
        found = (await session.execute(select(model.id).where(model.id == item_uuid))).scalar_one_or_none()
    if found is not None:
        return _error(422, f"该条目属于 {other} 库，不能在 {library} 库的列表里展开", "invalid_payload")
    return None


# ---------------------------------------------------------------------------
# deep-link（契约第 5 节）
# ---------------------------------------------------------------------------


@router.get("/items/{item_id}", response_model=GetLibraryItemPayload)
async def get_item(
    item_id: str,
    _account_id: Annotated[str, Depends(current_account)],
) -> GetLibraryItemPayload | JSONResponse:
    """deep-link 单条查询：在库 / 已撤下 / 不存在三态（契约第 5 节）。

    这条路径没有 `library` 参数（对话页的引用跳转只带 `item_id`），因此两库都查：
    `item_id` 是 UUID，跨两库不会撞。

    **撤下判定来自服务端现查**：历史引用是否仍可跳转，取决于这次查询的结果，
    而不是前端缓存的旧载荷（契约第 5 节）。因此本函数必须查到行本身
    （不能只查「未撤下的」），否则已撤下的目标会被报成 404，页面就渲染不出
    那张克制的撤下卡。

    Returns:
        在库：`{item: {...}}`；已撤下：`{item: null, withdrawn: true, title}`。

    Raises（对外映射）:
        404: 条目不存在，或 `item_id` 不是合法标识——页面按普通进入处理
            （不报错、不留在空页）。
        503: 取数失败。
    """
    try:
        item_uuid = uuid.UUID(item_id)
    except ValueError:
        return _error(404, "条目不存在", "not_found")

    found: tuple[str, CaseItem | Any] | None = None
    try:
        async with session_scope(get_settings()) as session:
            for library, model in ITEM_MODELS.items():
                row = (await session.execute(select(model).where(model.id == item_uuid))).scalar_one_or_none()
                if row is not None:
                    found = (library, row)
                    break
    except Exception:  # noqa: BLE001 —— 取数失败不得被呈现成「条目不存在」
        return _unavailable()

    if found is None:
        return _error(404, "条目不存在", "not_found")

    library, row = found
    if getattr(row, "withdrawn", False):
        # 只带标题、不带正文与其他字段：页面渲染单条撤下卡，不显示正文。
        return GetLibraryItemPayload(item=None, withdrawn=True, title=str(row.title))

    # 在库：组装成与列表同形的完整条目。snippet 与 locator 取该条目的**首个**节点
    # ——与浏览路 `retrieval._first_node_per_item` 同一条取值规则（按 `node_id`
    # 排序取第一个，因而同一条目每次取到同一个节点、`snippet` 不会抖动）。
    # 不用聚合路取回条目是因为它要求一次「检索」或「浏览」，而 deep-link 的语义
    # 是**按标识取一条**，借道浏览会让结果受该库的排序与分页影响。
    try:
        async with session_scope(get_settings()) as session:
            loaded = await load_items(session, [item_id], library=library)
            item = loaded.get(str(item_uuid))
            if item is None or not item.source or not item.status:
                # 不变量：缺来源或状态的条目不进入结果，不补默认值。
                return _error(404, "条目不存在", "not_found")
            nodes = await expand_items_to_nodes(session, [item_id])
    except RetrievalError:
        return _unavailable()
    except Exception:  # noqa: BLE001 —— 取数失败不得被呈现成「条目不存在」
        return _unavailable()

    rows = nodes.get(item_id, [])
    snippet, locator = ("", "")
    for _node_id, text, metadata in rows:
        snippet, locator = text, str(metadata.get("locator") or "")
        break

    payload = LibraryItemPayload(
        item_id=item_id,
        library=library,
        title=item.title,
        snippet=snippet,
        source=item.source,
        applicable_scope=item.applicable_scope,
        status=item.status,
        locator=locator,
        ranking={"order": "deep_link"},
        **(_case_payload_fields(item) if library == LIBRARY_CASE else {}),
    )
    return GetLibraryItemPayload(item=payload, withdrawn=False, title=None)


def _case_payload_fields(item: object) -> dict[str, Any]:
    """案例条目专属字段的透传（契约第 3.1 节的六项必带 + `inferred_fields`）。

    `inferred_fields` 取条目表上那一列（案例级并集）：deep-link 是单条查询、
    没有「命中的是哪张卡片」，因此与浏览路的取值规则同源（没有卡片就没有
    卡片级推断标注，不拿案例级并集冒充——见 `retrieval._case_fields_for_browse`
    的说明）。展开出的卡片各自带自己的卡片级清单。
    """
    if not isinstance(item, CaseItem):
        # 库别与模型必须一致（`ITEM_MODELS` 的映射保证）。走到这里说明映射与
        # 取数逻辑不一致，属编程错误——显式失败，不静默少给六个必带字段。
        raise TypeError(f"期望案例条目，实际 {type(item).__name__}")
    return {
        "authorization": item.authorization,
        "source_type": item.source_type,
        "evidence_level": item.evidence_level,
        "review_status": item.review_status,
        "interview_at": item.interview_at,
        "makes_claims_high_risk": item.makes_claims_high_risk,
        "inferred_fields": list(item.inferred_fields or []),
    }


__all__ = [
    "ITEMS_DEFAULT_LIMIT",
    "ITEMS_MAX_LIMIT",
    "PAGE_WINDOW_MAX",
    "PARSABLE_CARD_KEYS",
    "current_account",
    "router",
]
