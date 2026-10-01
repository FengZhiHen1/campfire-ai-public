"""档案侧产品工具：`read_profile_summary` / `read_profile_items` / `propose_profile_item` /
`create_support_object`。

职责：把 `modules/profile` 的用例包装成基座可调用的四个工具。
边界：只做契约映射 + 硬约束校验 + 权限调用——落层分流、稳定层判据、摘要生成、条目形状
都在 `modules/profile`，此处不重复实现，也不直接碰表（项目结构设计第 6、7 节）。
参考：docs/技术设计/面/consult/tools/{read_profile_summary,read_profile_items,
propose_profile_item,create_support_object}.md；
docs/技术设计/technical-details/个性化档案.md 第 3、7、9 节；
docs/技术设计/technical-details/支持对象.md 第 4、5、6 节。

工具是代码，语义在模块（T04 裁决 1）：本模块的每个 handler 只做三件事——
把参数映射成用例参数、把用例结果映射成契约字段、把用例的异常映射成错误码。
没有一条业务判据在这里新写：需要新判据时说明用例层缺能力，属未决问题而不是在此补实现。

为什么账号键与 `tools/memory.py` 各写一份 `ACCOUNT_PAYLOAD_KEY`（不是抄漏）：

`tools/` 的依赖白名单只放行 `campfire.agent.tools` / `campfire.modules` / `campfire.core`
（`tests/test_layer_boundaries.py` 的 `ALLOWED["tools"]`），兄弟工具模块之间不可互相
import——`tools/profile.py` import `tools/memory.py` 会被白名单检查拒绝。因此这个字面量
在 `tools/` 内各模块各有一份，是分层约束的结果而不是疏漏；键的所有者是装配处
（往 `ToolContext.payload` 里放账号的那一侧）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from campfire.agent.tools import ToolContext, ToolFailure, ToolResult
from campfire.core.authz import (
    OBJECT_ARCHIVED_MESSAGE,
    OBJECT_NOT_ACCESSIBLE_MESSAGE,
    AuthorizationError,
    ObjectArchivedError,
    require_writable,
)
from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.core.jobs import dispatch_pending_write
from campfire.core.pending_write import KIND_PROFILE_ITEM, enqueue
from campfire.modules.profile import (
    MAX_DISPLAY_NAME_LENGTH,
    GroupedItems,
    ItemView,
    ProfileDataError,
    ProfileSummary,
    bind_first_object,
    create_object,
    read_items,
    summary,
)
from campfire.modules.profile.consumer import (
    PAYLOAD_CONTEXTS,
    PAYLOAD_DESCRIPTION,
    PAYLOAD_DOMAIN,
    PAYLOAD_HELPFUL_SUPPORT,
    PAYLOAD_MANIFESTATIONS,
    PAYLOAD_PERSON_REPORT,
    PAYLOAD_PROBABLE_NEED,
    PAYLOAD_TOPIC,
    PAYLOAD_UNHELPFUL_SUPPORT,
)
from campfire.modules.profile.repository import ITEMS_DEFAULT_LIMIT, ITEMS_MAX_LIMIT

logger = logging.getLogger(__name__)

#: 从工具上下文里取账号的键。分区键由装配处经 `payload` 放入，模型无法指定——
#: 这是「属主取登录态，不从参数取」在工具层的落点（支持对象第 4 节创建操作的不变量）：
#: 参数模型里没有 `account_id`，模型没有通道把一条写入挂到别人名下。
ACCOUNT_PAYLOAD_KEY = "account_id"

#: 条目读取的默认条数与服务端上界。取自 `modules/profile` 的仓储常量而不是另写数字：
#: 抄一份上界必然漂移（CORE-10），而漂移的表现是「工具层以为收窄了、实际没有」。
DEFAULT_ITEMS_LIMIT = ITEMS_DEFAULT_LIMIT
MAX_ITEMS_LIMIT = ITEMS_MAX_LIMIT

#: 领域取值词表。语义所有者仍是 `modules/profile.DOMAINS`（个性化档案第 6 节），
#: 这里是一份受机械守住的镜像，不是第二处定义。
#:
#: 为什么必须写出来而不能 `Literal[*tuple(sorted(DOMAINS))]` 派生：`Literal` 的参数
#: 只接受字面量表达式，mypy 2.1.0 对 `*tuple(...)` 与 `Final` 常量都判 `valid-type`
#: （实测）。派生写法在运行时确实成立（pydantic 能解析），但静态上等于把整个参数模型
#: 的取值域退化成「类型别名非法」——那正是 CI 把 mypy 当 NewType 与枚举唯一机器通道
#: 时最不该出现的情形。
#:
#: 镜像的漂移由用例机械守住：`test_profile_tools.py` 的
#: `test_domain_enum_mirrors_the_module_vocabulary_exactly` 断言本 Literal 的取值集合
#: 与 `DOMAINS` 双向相等（多一个、少一个都会失败）。这正是原先派生写法想达到的
#: 效果——词表增删时不可能只改一处而不被发现。
Domain = Literal[
    "basic_identity",
    "about_self",
    "communication",
    "sensory_processing",
    "routines_and_change",
    "emotional_regulation",
    "triggers_and_support",
    "executive_function",
    "daily_living",
    "social_relationships",
    "physical_medical",
    "learning_and_work",
    "risk_and_crisis",
    "goals_and_plans",
    "other",
]

#: 生成方式词表。语义所有者是 `core.pending_write.ORIGINS`（写入路径第 3 节），
#: 同样是受守住的镜像，理由与 `Domain` 完全相同。
Origin = Literal[
    "user_statement",
    "guardian_observation",
    "third_party_report",
    "document",
    "system_observation",
    "ai_inference",
]


class _Source(BaseModel):
    """来源定位：这条认识出自哪一次对话的哪条消息（`AC-07`）。

    契约第 2 节把 `source` 写成 `object`（「会话 id、消息定位、工具名、时间；转述者记于
    `relayed_by`」），但开放对象过不了 SDK 的严格模式：`ToolSpec` 在注册期就要求
    `ensure_strict_json_schema` 能接受参数模型，而 `dict[str, object]` 会被它拒
    （见 `agent/tools/spec.py`）。因此这里收窄成具体形状——与 `tools/memory.py` 的
    `_Source` 同一处置，那处也是为同一个理由收窄的。

    收窄的代价如实写明：模型不能再塞任意键进来源。可接受的键只有下面三个，
    多一个都会被 `extra="forbid"` 拒绝——这比让它塞进任意键更好，因为来源是要被
    使用者复核的定位信息，形状固定才能保证它可复核。

    `tool`（工具名）不由模型传入、由本模块自己写进来源：工具名是服务端事实，
    让模型自报会得到一个可以撒谎的来源定位。
    """

    model_config = ConfigDict(extra="forbid")

    session_id: Annotated[str, Field(min_length=1, max_length=128, description="会话标识")]
    message_seq: Annotated[int | None, Field(default=None, ge=0, description="消息序号（可选）")] = None
    relayed_by: Annotated[
        str | None, Field(default=None, max_length=64, description="转述者（本人自述经他人转述时填）")
    ] = None


class ReadProfileSummaryArgs(BaseModel):
    """`read_profile_summary` 的参数（契约第 2 节）。"""

    model_config = ConfigDict(extra="forbid")

    support_object_id: Annotated[str, Field(min_length=1, max_length=64, description="支持对象标识（UUID）")]


class ReadProfileItemsArgs(BaseModel):
    """`read_profile_items` 的参数（契约第 2 节）。"""

    model_config = ConfigDict(extra="forbid")

    support_object_id: Annotated[str, Field(min_length=1, max_length=64, description="支持对象标识（UUID）")]
    domains: Annotated[
        list[Domain] | None,
        Field(default=None, description="按领域过滤；省略则不限。未知领域名会被拒绝，不会静默忽略"),
    ] = None
    include_candidates: Annotated[
        bool, Field(default=False, description="是否一并返回未确认的候选条目（默认不返回）")
    ] = False
    limit: Annotated[
        int | None,
        Field(default=None, ge=1, le=MAX_ITEMS_LIMIT, description=f"条数上限，最多 {MAX_ITEMS_LIMIT}"),
    ] = None


class ProposeProfileItemArgs(BaseModel):
    """`propose_profile_item` 的参数（契约第 2 节）。

    没有 `confirmation` 参数，这是有意的：落层与确认状态由 `origin` 决定
    （个性化档案第 3 节的表、第 7 节「落层判定的位置」）。契约第 4 节硬约束 2 要求
    「推断不得冒充事实」——`system_observation` / `ai_inference` 不许写成 `confirmed`。
    把确认状态做成参数，等于把这个判据降级成一次可以撒谎的输入；不设参数则违规组合
    在参数模型里根本表达不出来，比「接受再拒绝」更强：不存在的通道无法被绕过。
    用例层仍保留 `InferredCannotBeConfirmedError` 作为纵深防御（本模块把它映射成显式失败）。
    """

    model_config = ConfigDict(extra="forbid")

    support_object_id: Annotated[str, Field(min_length=1, max_length=64, description="支持对象标识（UUID）")]
    domain: Annotated[Domain, Field(description="领域：十四个一级模块之一或「其他」；词表外的值被拒绝")]
    topic: Annotated[str, Field(min_length=1, max_length=200, description="该领域下的主题")]
    description: Annotated[str, Field(min_length=1, description="一条可观察的事实描述，不要写成宽泛标签")]
    origin: Annotated[Origin, Field(description="这条认识是怎么来的；落层由它决定，不由调用方指定")]
    source: Annotated[_Source, Field(description="来源定位：会话标识，可带消息序号与转述者")]
    contexts: Annotated[list[str] | None, Field(default=None, description="什么情境下出现（可选）")] = None
    manifestations: Annotated[list[str] | None, Field(default=None, description="具体表现（可选）")] = None
    person_report: Annotated[str | None, Field(default=None, description="本人怎么说（可选，原文）")] = None
    probable_need: Annotated[str | None, Field(default=None, description="可能的需求（可选）")] = None
    helpful_support: Annotated[list[str] | None, Field(default=None, description="哪些支持有效（可选）")] = None
    unhelpful_support: Annotated[list[str] | None, Field(default=None, description="哪些支持无效（可选）")] = None


class CreateSupportObjectArgs(BaseModel):
    """`create_support_object` 的参数（契约第 2 节）。

    不收 `account_id`：属主由登录态决定，不接受调用方传入（支持对象第 4 节
    创建操作的不变量）。忘记传就落到别人名下这类缺陷要由实现层堵掉，而不是靠调用方自觉。
    """

    model_config = ConfigDict(extra="forbid")

    display_name: Annotated[
        str,
        Field(min_length=1, max_length=MAX_DISPLAY_NAME_LENGTH, description="对象名，使用者自起的称呼，不能空白"),
    ]


def _account_from(context: ToolContext) -> str | ToolFailure:
    """从上下文取出并校验账号标识（登录态的承载）。

    拿不到就明确失败，而不是猜一个默认账号：猜默认会把档案写到错误的账号下，
    属于静默错分——使用者看不到任何异常，只是数据不在自己名下。

    只校验「是非空字符串」：档案的账号键是列值（`repository._validate_account_id` 的判据），
    不是 Graphiti 的分区键，因此不套用 `modules/memory/identity.to_account_id` 的
    字符集规则（那条规则的存在理由是 `group_id` 就是图名）。套用它会让一个合法的档案
    账号键被记忆侧的规则拒绝，是把两处不同的边界混成一处。
    """
    payload = context.payload
    raw: object | None = None
    if isinstance(payload, dict):
        raw = payload.get(ACCOUNT_PAYLOAD_KEY)
    if not isinstance(raw, str) or not raw.strip():
        return ToolFailure(
            code="tool_failed",
            message=f"缺少登录账号（装配处应在 payload 里提供 {ACCOUNT_PAYLOAD_KEY!r}）——无法确定档案归属",
        )
    return raw


def _failure_from_authz(exc: AuthorizationError) -> ToolFailure:
    """把授权失败映射成对外文案（支持对象第 5.3 节的两条文案）。

    先判 `ObjectArchivedError` 再判基类：它是 `AuthorizationError` 的子类，顺序写反会把
    「已归档」变成「不存在」，使用者就看不到该去恢复的原因。文案直接取
    `core/authz` 的常量而不是在这里重写一遍——文案是契约的一部分，两处各写一份必然漂移。
    """
    if isinstance(exc, ObjectArchivedError):
        return ToolFailure(code="tool_failed", message=OBJECT_ARCHIVED_MESSAGE)
    return ToolFailure(code="tool_failed", message=OBJECT_NOT_ACCESSIBLE_MESSAGE)


def _isoformat(value: datetime) -> str:
    """时间统一转 ISO 8601：返回要走 `json.dumps`，`datetime` 直接放进去会抛 `TypeError`。

    `.isoformat()` 保留时区偏移，因此时刻不会因序列化而丢失偏移信息。
    """
    return value.isoformat()


# ---------------------------------------------------------------------------
# 取数：摘要与条目
# ---------------------------------------------------------------------------


def _render_summary_text(result: ProfileSummary) -> str:
    """把结构化摘要渲染成契约第 3 节要求的自然语言 `summary` 字符串。

    这不是「在工具层写摘要生成规则」：字段清单、字段顺序与字段标签都由
    `modules/profile.service.SUMMARY_FIELD_DOMAINS` 提供（摘要的生成规则归
    个性化档案第 4 节），本函数只做形状映射——把已经分好组、定好标签的结构铺成文本。
    需要改摘要内容时改的是模块侧那张表，不是这里。

    无档案时返回明确的「无档案」标记而不是空串（契约第 4 节末行、`AC-02`）：
    调用方要据此在输出里标注「本次未使用个性化档案」，而空串会让模型自己猜这是
    「没有档案」还是「取数没成功」。
    """
    if not result.has_profile:
        return (
            "该支持对象当前没有档案内容。"
            "这**不等于**这个人没有任何特征或需求——只能说档案里还没有记录。"
            "请在输出中标注「本次未使用个性化档案」，不要凭此推断。"
        )

    lines: list[str] = []
    for field in result.fields:
        for entry in field.items:
            stamp = entry.last_confirmed_at.date().isoformat()
            lines.append(f"- {field.label}：{entry.description}（来源：{entry.origin}，最近确认：{stamp}）")
    return "\n".join(lines)


async def read_profile_summary(context: ToolContext, args: ReadProfileSummaryArgs) -> ToolResult | ToolFailure:
    """取支持对象的一页档案摘要（契约第 1 节）。

    契约真源：docs/技术设计/面/consult/tools/read_profile_summary.md

    只从稳定层取数、`rejected` 条目不进摘要、候选层不进摘要、无档案返回显式标记——
    四条硬约束（契约第 4 节）全部在 `modules/profile` 的 `summary()` 里成立
    （`read_stable_items_by_domains` 的 SQL 条件 + `SUMMARY_FIELD_DOMAINS` 的分组），
    本模块只做包装。在这里再判一次不会更安全，只会制造第二处判据。

    归档对象不是错误：仍可读取（归档不等于删除），因此读路径用 `require_owned`
    （由 `summary()` 内部调用），不用 `require_writable`。

    Returns:
        `ToolResult`：`summary` / `item_count` / `generated_at` / `possibly_stale`
        四个契约字段（另带 `has_profile` 供调用方标注）。
        `ToolFailure`：对象不存在、不属于当前账号，或取数失败——
        不得返回空摘要冒充「没有档案」（契约第 5 节）。
    """
    account_id = _account_from(context)
    if isinstance(account_id, ToolFailure):
        return account_id

    try:
        async with session_scope(get_settings()) as session:
            result = await summary(session, account_id=account_id, support_object_id=args.support_object_id)
    except AuthorizationError as exc:
        return _failure_from_authz(exc)
    except ProfileDataError as exc:
        return ToolFailure(code="tool_invalid_arguments", message=f"无法读取档案摘要：{exc}")
    except Exception as exc:  # noqa: BLE001 —— 取数失败不得冒充「没有档案」（契约第 5 节末行）
        logger.warning("read_profile_summary 失败：%s", type(exc).__name__)
        return ToolFailure(
            code="tool_failed",
            message=(
                f"档案摘要未能读取（{type(exc).__name__}）——**不得**当作「这个人没有档案」，"
                "请标注「本次未使用个性化档案」。"
            ),
        )

    payload: dict[str, object] = {
        "summary": _render_summary_text(result),
        "item_count": result.item_count,
        "generated_at": _isoformat(result.generated_at),
        "possibly_stale": result.possibly_stale,
        "has_profile": result.has_profile,
    }
    if result.possibly_stale:
        # 契约第 4 节末行：有未完成的待处理记录时 `possibly_stale` 必须为真，
        # 而模型只有看到这句话才知道要标注滞后，光给一个布尔值它未必会用。
        payload["notice"] = "注意：该对象有尚未完成的写入，摘要可能未包含最新内容（写入是异步的）。"
    return ToolResult(text=json.dumps(payload, ensure_ascii=False))


def _render_item_view(view: ItemView, *, layer: str) -> dict[str, object]:
    """把条目视图映射成返回契约字段（契约第 3 节）。

    三个字段不得省：`origin`（谁在什么位置上说的）、`confirmation`（是否被使用者
    确认过）、`freshness`（是否仍是当前认识）——契约第 4 节逐字写着「不得为了『让输出
    干净』而省略来源与确认状态」。省略它们会让模型把候选当成事实，而候选层不得作为事实
    进入对话（`AC-18`）。

    `layer` 是本模块加的显式分层标记：契约第 4 节要求「候选层条目必须自带标记返回，
    调用方与模型都不得把它当作事实」，而 `confirmation = unconfirmed` 这个标记需要
    模型自己推理出来。直接给一个 `stable` / `candidate` 的词，把推理变成读值。
    """
    return {
        "item_id": view.item_id,
        "domain": view.domain,
        "topic": view.topic,
        "description": view.description,
        "origin": view.origin,
        "confirmation": view.confirmation,
        "freshness": view.freshness,
        "layer": layer,
        "contexts": list(view.contexts),
        "manifestations": list(view.manifestations),
        "helpful_support": list(view.helpful_support),
        "unhelpful_support": list(view.unhelpful_support),
        "person_report": view.person_report,
        "probable_need": view.probable_need,
        "source": dict(view.source),
        "first_recorded_at": _isoformat(view.first_recorded_at),
        "last_confirmed_at": _isoformat(view.last_confirmed_at),
        "superseded_by": view.superseded_by,
        "supersedes": view.supersedes,
    }


def _items_payload(grouped: GroupedItems) -> dict[str, object]:
    """把「稳定层 / 候选层」两组铺成返回体（契约第 3 节）。

    候选单独成组而不是混进一个数组：这是候选层视觉不变量（`AC-18`）的服务端侧保证——
    它由返回结构保证，而不是靠调用方自己按 `confirmation` 分。混在一起时，
    一次 `for item in items` 就会把候选当事实用。
    """
    items = [_render_item_view(view, layer="stable") for view in grouped.items]
    candidates = [_render_item_view(view, layer="candidate") for view in grouped.candidates]
    payload: dict[str, object] = {"items": items, "candidates": candidates, "count": len(items)}
    if candidates:
        payload["notice"] = (
            "`candidates` 是**未确认**的推断或系统观察，**不得**当作事实陈述或作为建议依据；"
            "只有 `items`（稳定层）可以按事实使用。"
        )
    return payload


async def read_profile_items(context: ToolContext, args: ReadProfileItemsArgs) -> ToolResult | ToolFailure:
    """按条件读取具体档案条目（契约第 1 节）。

    契约真源：docs/技术设计/面/consult/tools/read_profile_items.md
    与 `read_profile_summary` 的分工：概览用摘要，细节用本工具。

    只读；`rejected` 条目与已被取代的条目一律不返回（在 `modules/profile` 的 SQL 里
    成立）。未知领域名在这里就失败了两次：参数枚举先拒（`tool_invalid_arguments`），
    用例层再拒（`ProfileDataError`）。这不是重复——枚举保证模型拿到的是词表内的值，
    用例层保证绕过参数模型的调用同样被拒。

    Returns:
        `ToolResult`：`items` 与 `candidates` 两组（每组条目都带 `origin` /
        `confirmation` / `freshness` / `layer`）。
        `ToolFailure`：越权、领域名非法或取数失败——不返回部分结果冒充完整结果。
    """
    account_id = _account_from(context)
    if isinstance(account_id, ToolFailure):
        return account_id

    limit = args.limit if args.limit is not None else DEFAULT_ITEMS_LIMIT
    # 服务端上界（CORE-11）：参数层已用 `le` 拦住，这里再收一次，覆盖绕过参数模型
    # 直接调用本函数的情形。
    limit = max(1, min(limit, MAX_ITEMS_LIMIT))

    try:
        async with session_scope(get_settings()) as session:
            grouped = await read_items(
                session,
                account_id=account_id,
                support_object_id=args.support_object_id,
                domains=list(args.domains) if args.domains is not None else None,
                include_candidates=args.include_candidates,
                limit=limit,
            )
    except AuthorizationError as exc:
        return _failure_from_authz(exc)
    except ProfileDataError as exc:
        # 契约第 5 节：过滤条件非法明确失败，不静默忽略条件。
        return ToolFailure(code="tool_invalid_arguments", message=f"档案条目未能读取：{exc}")
    except Exception as exc:  # noqa: BLE001 —— 取数失败不得返回部分结果冒充完整结果
        logger.warning("read_profile_items 失败：%s", type(exc).__name__)
        return ToolFailure(code="tool_failed", message=f"档案条目未能读取（{type(exc).__name__}）")

    return ToolResult(text=json.dumps(_items_payload(grouped), ensure_ascii=False))


# ---------------------------------------------------------------------------
# 写入：条目
# ---------------------------------------------------------------------------


async def propose_profile_item(context: ToolContext, args: ProposeProfileItemArgs) -> ToolResult | ToolFailure:
    """把对话中已经出现过的信息提成档案条目（契约第 1 节）——档案的唯一写入口。

    契约真源：docs/技术设计/面/consult/tools/propose_profile_item.md

    本函数只做三件事（其余全在 `modules/profile`，那是落层判据的唯一位置）：

    1. 权限：`require_writable`——对象必须存在、属于当前账号且未归档
       （契约第 4 节第 6 条）。为什么在这里显式调用而不是靠用例层：本工具的写入路径是
       `core.pending_write.enqueue`（待处理记录），它不查对象表；不在这里判定，
       归档对象会照常收下一次写入，直到 Worker 领取时才失败——那是「接口回执成功、
       实际永远写不进去」，最坏的一种回执。用例层 `propose_item` 也调 `require_writable`
       （纵深防御），两处判据同源。
    2. 落成待处理记录：只落记录，不等异步完成（契约第 4 节第 7 条）。
    3. 投递：`dispatch_pending_write`，投递失败不让本次调用失败——记录已落库，
       由兜底扫描重投（写入路径第 4.1 节；与 `write_memory` 同一处置）。
       `kind = profile_item` 的消费者归 T12（Worker 侧尚无对应任务），当前投递方
       显式跳过并记日志：记录留在 `pending`，不判 dead，消费者接上后由兜底扫描带回。

    载荷里不放 `confirmation`：确认状态由 `origin` 推导（`confirmation_on_entry`），
    而 Worker 侧还会再校验一次「推断不得是 confirmed」并拒绝构造过的载荷
    （`consumer.write_from_pending`）。放进去等于让模型指定落层，正是契约第 4 节第 2 条
    要拒绝的事。参数模型里也没有这个字段（见 `ProposeProfileItemArgs` 的说明）。

    回执只承诺 `submitted`——写入经待处理记录与 Worker 异步完成，不得回执「已保存」
    （契约第 3 节）。使用者尚未确认的推断仍会进候选层，这是正常的：落层由 `origin` 决定。

    Returns:
        `ToolResult`：`pending_id` 与 `state: "submitted"`。
        `ToolFailure`：越权（两种情形文案相同）、对象已归档（文案区分）、
        待处理记录写入失败（不得回执 submitted）。
    """
    account_id = _account_from(context)
    if isinstance(account_id, ToolFailure):
        return account_id

    try:
        await require_writable(account_id, args.support_object_id)
    except AuthorizationError as exc:
        return _failure_from_authz(exc)

    # 来源定位：会话与消息序号由模型给（它知道对话上下文），工具名由服务端补——
    # 工具名是服务端事实，让模型自报会得到一个可以撒谎的来源定位。
    source: dict[str, object] = {"session_id": args.source.session_id, "tool": "propose_profile_item"}
    if args.source.message_seq is not None:
        source["message_seq"] = args.source.message_seq
    if args.source.relayed_by is not None:
        source["relayed_by"] = args.source.relayed_by

    payload: dict[str, object] = {
        PAYLOAD_DOMAIN: args.domain,
        PAYLOAD_TOPIC: args.topic,
        PAYLOAD_DESCRIPTION: args.description,
    }
    # 可选字段按「给了才带」：不为了载荷完整而补空值——空数组与「没提到」在下游
    # 语义不同（前者是「明确没有」，后者是「未采集」），补默认值会制造假事实。
    for key, value in (
        (PAYLOAD_CONTEXTS, args.contexts),
        (PAYLOAD_MANIFESTATIONS, args.manifestations),
        (PAYLOAD_HELPFUL_SUPPORT, args.helpful_support),
        (PAYLOAD_UNHELPFUL_SUPPORT, args.unhelpful_support),
        (PAYLOAD_PERSON_REPORT, args.person_report),
        (PAYLOAD_PROBABLE_NEED, args.probable_need),
    ):
        if value is not None:
            payload[key] = value

    try:
        async with session_scope(get_settings()) as session:
            record = await enqueue(
                session,
                kind=KIND_PROFILE_ITEM,
                account_id=account_id,
                origin=args.origin,
                payload=payload,
                source=source,
                support_object_id=args.support_object_id,
            )
            pending_id = str(record.id)
    except ProfileDataError as exc:
        # 用例层的纵深防御（推断被尝试写成 confirmed、载荷形状不合法）。
        # 参数模型已经让这些组合表达不出来，走到这里说明调用方绕过了参数模型。
        return ToolFailure(code="tool_failed", message=f"档案条目未能提交：{exc}")
    except Exception as exc:  # noqa: BLE001 —— 待处理记录写入失败必须明确失败，不回执 submitted
        logger.warning("propose_profile_item 失败：%s", type(exc).__name__)
        return ToolFailure(code="tool_failed", message=f"档案条目未能提交（{type(exc).__name__}）")

    # 必须 await：`kiq()` 返回协程，不 await 等于没有投递。
    # kind 必传：投给谁由它决定（第 4 节第 3 条）；当前 profile_item 尚无消费者，
    # 投递方会显式跳过（记录留 pending，不判 dead）。
    await dispatch_pending_write(pending_id, KIND_PROFILE_ITEM)

    return ToolResult(text=json.dumps({"pending_id": pending_id, "state": "submitted"}, ensure_ascii=False))


# ---------------------------------------------------------------------------
# 支持对象：创建
# ---------------------------------------------------------------------------


async def create_support_object(context: ToolContext, args: CreateSupportObjectArgs) -> ToolResult | ToolFailure:
    """在对话中创建一个支持对象并返回其标识（契约第 1 节）。

    契约真源：docs/技术设计/面/consult/tools/create_support_object.md

    与档案面「+ 新建对象」表单走同一个创建用例（`modules/profile.create_object`，
    T04 裁决 5）：对话式创建是一等入口，表单是补充路径。两条路各写一份创建逻辑会漂移，
    而漂移的表现是「表单创建的对象与对话创建的对象在约束上不同」。

    属主取登录态（`_account_from`），参数模型里没有 `account_id`。空名不在这里判——
    `create_object` 经 `normalize_display_name` 与存储层 CHECK 两道拒（契约第 4 节第 1 条），
    工具层只把参数收窄成非空字符串，判据仍只有模块侧一处。

    首对象补绑（支持对象第 6 节、契约第 6 节验证项）：本会话在建立时没有绑定
    （账号当时没有任何在用对象）时，把刚创建的对象补建为该会话的唯一绑定。
    为什么在这里调用而不是别的层：这一条是「对话中创建第一个对象」这条路径的组成部分，
    而创建只经本工具与档案面表单两条路；表单路径的会话绑定由档案面另行处理，本工具
    只负责自己这条。`bind_first_object` 的 `ON CONFLICT DO NOTHING` 保证补绑只发生一次
    ——会话已有绑定后再建第二个对象不改绑（契约第 6 节第二项），这条不变量由
    存储层的主键冲突兜住，不是靠这里先查后写。

    Returns:
        `ToolResult`：`support_object_id` 与实际落库的 `display_name`。
        `ToolFailure`：未登录（`RQ-ACC-01`）、空名或创建失败。
    """
    account_id = _account_from(context)
    if isinstance(account_id, ToolFailure):
        return account_id

    try:
        async with session_scope(get_settings()) as session:
            created = await create_object(session, account_id=account_id, display_name=args.display_name)
            object_id = str(created.id)
            display_name = created.display_name
            # 补绑与创建同一次会话/事务：分两次事务时，创建成功而补绑失败会留下一个
            # 「对象已建、本会话仍无绑定」的中间态，而补绑的时机只有这一次
            # （会话已有绑定后不再补），错过就再也补不上。
            await bind_first_object(
                session,
                session_id=context.session_id,
                account_id=account_id,
                support_object_id=object_id,
            )
    except ProfileDataError as exc:
        # 契约第 5 节：空名或全空白名明确失败，不静默填默认名。
        return ToolFailure(code="tool_invalid_arguments", message=f"未能创建支持对象：{exc}")
    except Exception as exc:  # noqa: BLE001 —— 创建失败必须明确失败，不回执一个标识
        logger.warning("create_support_object 失败：%s", type(exc).__name__)
        return ToolFailure(code="tool_failed", message=f"未能创建支持对象（{type(exc).__name__}）")

    return ToolResult(
        text=json.dumps({"support_object_id": object_id, "display_name": display_name}, ensure_ascii=False)
    )


__all__ = [
    "ACCOUNT_PAYLOAD_KEY",
    "DEFAULT_ITEMS_LIMIT",
    "MAX_ITEMS_LIMIT",
    "CreateSupportObjectArgs",
    "ProposeProfileItemArgs",
    "ReadProfileItemsArgs",
    "ReadProfileSummaryArgs",
    "create_support_object",
    "propose_profile_item",
    "read_profile_items",
    "read_profile_summary",
]
