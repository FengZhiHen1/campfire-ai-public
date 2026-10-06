"""档案面的 HTTP 路由：支持对象、摘要、条目读取、确认/纠正/否定/删除、补充条目。

职责：把 `modules/profile` 的用例暴露成档案面契约的 HTTP 形状（路径、查询参数、
载荷与状态码），并把用例层的领域异常映射成对外的 404/409/422。
边界：只做 HTTP 形状与错误码映射——落层判据、授权判定、取数与时间计算都在用例层；
      本模块不直接访问数据库表，也不装配 Agent 运行。
参考：docs/技术设计/面/profile/档案面HTTP契约.md（第 2～6 节）；
      docs/技术设计/technical-details/个性化档案.md 第 4、8 节；
      docs/技术设计/technical-details/支持对象.md 第 4、5 节。

为什么路由放在本模块而不是 `surfaces/`（本包裁决 1）：项目的「面」指产品入口与
Agent 运行装配（docs/项目结构设计.md 第 5 节），而这三个面不装配 skill 与工具池，
它们只是本模块用例的 HTTP 皮肤——与认证不建面、契约归认证与账号同构。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from supertokens_python.recipe.session import SessionContainer

from campfire.core.auth.supertokens import require_session
from campfire.core.authz import (
    OBJECT_ARCHIVED_MESSAGE,
    OBJECT_NOT_ACCESSIBLE_MESSAGE,
    AuthorizationError,
    ObjectArchivedError,
)
from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.core.pagination import parse_offset_cursor
from campfire.modules.profile import service
from campfire.modules.profile.errors import ProfileError
from campfire.modules.profile.models import SupportObject

router = APIRouter(prefix="/profile", tags=["profile"])

#: 条目列表的单页条数默认值与上界（本包裁决 8）。
#:
#: 契约只写「`limit` 未传时服务端必须有上界」，未给数值。取 20/50 与会话列表
#: （HTTP/SSE 契约第 3.2 节：默认 20、上限 50）同一档，避免同一产品里出现两套
#: 分页尺度；上限存在的理由是 CORE-11：无界拉取会随档案条目量增长。
ITEMS_DEFAULT_LIMIT = 20
ITEMS_MAX_LIMIT = 50

#: 一次请求可以回看的原始行数上界。游标是偏移量，而用例层只接 `limit`
#: （`service.read_items` 收敛到 `repository.ITEMS_MAX_LIMIT` = 500），因此
#: 本面用「多取 offset+limit+1 行再切片」实现分页，窗口不能超过用例层上界。
#: 也就是说：可翻页的总窗口受此值约束，超过它之后 `next_cursor` 为 null。
#: 该边界如实登记在交付报告的未决问题节。
PAGE_WINDOW_MAX = 500


# ---------------------------------------------------------------------------
# 会话依赖
# ---------------------------------------------------------------------------


async def current_account(session: SessionContainer | None = Depends(require_session())) -> str:
    """从登录态取得当前账号标识，作为全部端点的归属键。

    为什么要单独一层入口而不是在每个端点里 `Depends(require_session())`：
    端点只需要「当前账号」这一个值，而 SDK 的依赖返回的是会话容器；把
    「取账号」收在一处，端点的签名里就不会出现 SDK 类型，测试也可以只替换
    这一个依赖（`app.dependency_overrides`）而不必构造真实会话。

    `require_session()` 固定 `session_required=True` 与 `check_database=True`
    （见 `core/auth/supertokens.require_session`）：撤销即时生效靠后者，漏传不会
    报错只会静默失去撤销能力，因此这一层不得绕过它。

    Args:
        session: SDK 注入的会话容器；`session_required=True` 时必不为 None。

    Returns:
        账号标识（即身份服务的用户标识，认证与账号第 3 节）。

    Raises:
        RuntimeError: 会话容器缺失。这在 `session_required=True` 下不可达；
            显式失败而不是回落到空账号——空账号在等值查询里查不到任何行，
            会把一次装配缺陷伪装成「这个账号没有对象」。
    """
    if session is None:  # pragma: no cover —— session_required=True 时不可达
        raise RuntimeError("require_session 返回了空会话：拒绝按无账号处理请求")
    return session.get_user_id()


# ---------------------------------------------------------------------------
# 错误映射
# ---------------------------------------------------------------------------


def _error(status_code: int, message: str, code: str) -> JSONResponse:
    """构造带机器可读 code 的错误响应。

    `detail` 是契约里那两句文案（越权与不存在逐字相同、归档文案区分）；
    `code` 是附加的稳定标识，供前端按分支处置而不必匹配中文文案——
    文案是给人读的，会随修改漂移，而 `code` 是契约里的取值
    （档案面契约第 1 节的 `object_archived`）。
    """
    return JSONResponse(status_code=status_code, content={"detail": message, "code": code})


def _map_error(exc: Exception) -> JSONResponse:
    """把用例层的领域异常映射成对外状态码。

    分派顺序是有意的：`ObjectArchivedError` 是 `AuthorizationError` 的子类
    （见 `core/authz/errors` 的分派要求），先判归档再判越权；写反会把「已归档」
    报成「不存在」，使用者就看不到该去恢复的原因。

    Raises:
        Exception: 未映射的异常原样抛出——本函数只负责已知的领域失败，
            基础设施故障必须继续冒泡（不谎报成 4xx）。
    """
    if isinstance(exc, ObjectArchivedError):
        return _error(409, OBJECT_ARCHIVED_MESSAGE, "object_archived")
    if isinstance(exc, AuthorizationError):
        return _error(404, OBJECT_NOT_ACCESSIBLE_MESSAGE, "not_found")
    if isinstance(exc, ProfileError):
        # 载荷不合法与「条目状态不允许该操作」（重复确认、纠正无变更）都归 422：
        # 它们都是「这次请求本身有问题」，重试同样的请求不会变好（契约第 1 节）。
        return _error(422, str(exc), "invalid_payload")
    raise exc


# ---------------------------------------------------------------------------
# 分页
# ---------------------------------------------------------------------------


def _page_window(offset: int, limit: int) -> int:
    """算出本次要向用例层多取的行数（CORE-11：有界）。

    多取一行是为了判断「还有没有下一页」——只看 `len(rows) == offset + limit`
    无法区分「恰好这么多」与「被截断」。
    """
    return min(offset + limit + 1, PAGE_WINDOW_MAX)


# ---------------------------------------------------------------------------
# 载荷模型（对外形状的单一声明处）
# ---------------------------------------------------------------------------


#: `topic` 的长度上界，与存储列同宽（`models.ProfileItem.topic` 的 `String(200)`），
#: 也与工具入口同口径（`tools/profile.py` 的 `ProposeProfileItemArgs.topic` 取
#: `max_length=200`）。
#:
#: 收在载荷层而不是只靠数据库拒绝：超宽载荷到驱动层会抛
#: `StringDataRightTruncationError`，它不是领域异常，而 `_map_error` 只认
#: `ProfileError`/`AuthorizationError`（其余原样冒泡）——契约第 1 节的 422 于是
#: 变成 500。收在这里，拒绝发生在触库之前。
TOPIC_MAX_LENGTH = 200


class CreateObjectRequest(BaseModel):
    """`POST /profile/objects` 的请求体。属主取登录态，不接受调用方传入。"""

    display_name: str


class PatchObjectRequest(BaseModel):
    """`PATCH /profile/objects/{id}` 的请求体：两个状态位的赋值。

    两者都可省略，但至少给一个——全空是一次无效果的请求，静默返回 200
    会让调用方以为改名成功了（边界显式，无静默兜底）。
    """

    display_name: str | None = None
    archived: bool | None = None


class CorrectItemRequest(BaseModel):
    """`POST /profile/items/{item_id}/correct` 的请求体。

    载荷是新条目的完整形状而不是补丁字段（契约第 4 节）：档案条目是
    「谁在何时说的」的记录，补丁会让新条目继承旧条目的来源与时间。
    """

    description: str
    topic: Annotated[str | None, Field(max_length=TOPIC_MAX_LENGTH)] = None
    contexts: list[str] | None = None
    manifestations: list[str] | None = None


class CreateItemRequest(BaseModel):
    """`POST /profile/objects/{id}/items` 的请求体（使用者补充一条）。

    `origin` 不在请求体里：它由服务端定为 `user_statement`，生成方式不是
    使用者可选的字段（契约第 5 节）。
    """

    domain: str
    topic: Annotated[str, Field(max_length=TOPIC_MAX_LENGTH)]
    description: str
    contexts: list[str] | None = None
    manifestations: list[str] | None = None


class SupportObjectPayload(BaseModel):
    """支持对象的对外形状（契约第 2.1、2.2 节）。"""

    id: str
    display_name: str
    archived_at: datetime | None


class ObjectListPayload(BaseModel):
    """支持对象列表；含已归档对象（`archived_at` 非空）。"""

    items: list[SupportObjectPayload]


class SummaryEntryPayload(BaseModel):
    """摘要里的一条（契约第 3 节：每条带 `item_id`、`origin` 与 `last_confirmed_at`）。

    `text` 与 `freshness` 是契约未点名但下游必需的：
    `text` 是条目的可读内容（个性化档案第 4 节「条目」在本面的承载键，与
    前端线格式类型 `ProfileSummaryEntry.text` 对齐）；`freshness` 是条目的
    当下新鲜度，但摘要只取稳定层，故这里恒为 `current`——`stale` 只在
    `GET /profile/objects/{id}/items?include_candidates=true` 的 `candidates`
    组里出现（`ProfileItemPayload.freshness`），页面要标注陈旧须走那条路径。
    """

    item_id: str
    origin: str
    last_confirmed_at: datetime
    text: str
    freshness: str


class SummaryFieldPayload(BaseModel):
    """摘要的一个字段分组（十二个字段见个性化档案第 4 节）。"""

    key: str
    label: str
    items: list[SummaryEntryPayload]


class SummaryPayload(BaseModel):
    """一页摘要；只取稳定层。

    `has_profile` 是契约未点名但必需的一个字段：只有候选条目的对象在摘要意义上
    就是「无档案」（个性化档案第 10 节要求返回「无档案」而不是空对象），
    而 `fields: []` 无法区分它与「有档案但没有稳定条目」。`AC-02` 的
    「本次未使用个性化档案」标注依赖这个区分。
    """

    fields: list[SummaryFieldPayload]
    has_profile: bool


class ProfileItemPayload(BaseModel):
    """档案条目的对外形状（个性化档案第 2 节 + 契约第 3 节）。

    必须含 `origin`、`confirmation`、`freshness` 三项（契约第 3 节）；
    `superseded_by` 与 `supersedes` 是纠正后的互指（第 3 节不变量 3），
    一对都要给出，只给一个会让「谁取代了谁」需要再查一次。
    """

    item_id: str
    support_object_id: str
    domain: str
    topic: str
    description: str
    contexts: list[str]
    manifestations: list[str]
    person_report: str | None
    probable_need: str | None
    helpful_support: list[str]
    unhelpful_support: list[str]
    origin: str
    #: 来源定位原样透出（`AC-07` 的可复核性载体）。存储列是 JSONB，键随写入方
    #: 而不同——本批可达的两个写入方是：补充条目由服务端补
    #: `{"channel": "profile_page"}`（`MANUAL_ENTRY_SOURCE`），以及 Worker 消费
    #: `profile_item` 时原样转发待处理记录里的 `source`（其生产者
    #: ~~`propose_profile_item` 工具尚未实现~~）。因此这里不做键名归一。
    #:
    #: **⇒ 已订正（2026-10-06）**：上面划掉的那句**前提是错的**——`propose_profile_item`
    #: **已实现并已注册**（工具在 `tools/profile.py`、注册点在 `surfaces/consult/registry.py`，
    #: 落层用例在 `modules/profile/service.py` 的 `propose_item`）。**订正后结论不变，
    #: 但理由换了**：该写入方落进 `source` 的键是 `session_id` / `tool`（外加可选的
    #: `message_seq` / `relayed_by`），与手动入口的 `channel` **既无同名键、也不是同一个事实**
    #: ——`channel` 答「这条是在哪个页面写下的」，`tool` 答「哪个工具写下的」；会话定位与
    #: 转述者只对会话内写入存在（手动入口根本没有会话）。**⇒ 归一在这里只能制造假合并**
    #: （把 `profile_page` 与 `propose_profile_item` 并进同一个键，等于断言「档案页是一个工具」），
    #: 而两类来源的键集本来就**不相交**。**因此不做键名归一的理由是「两个写入方的键集不相交
    #: 且语义不同」，不是「生产者尚未实现」。**
    #: 值类型写成 JSON 标量联合而不是 `Any`：后者会让「这里可能混进嵌套对象」
    #: 在类型层不可见，而本面承诺的是可读的来源定位。
    source: dict[str, str | int | float | bool | None]
    confirmation: str
    freshness: str
    first_recorded_at: datetime
    last_confirmed_at: datetime
    superseded_by: str | None
    supersedes: str | None


class ItemsPayload(BaseModel):
    """条目列表响应；候选层单独成组（`AC-18` 的服务端侧保证）。"""

    items: list[ProfileItemPayload]
    candidates: list[ProfileItemPayload]
    next_cursor: str | None


class ConfirmPayload(BaseModel):
    """确认响应（契约第 4 节）。"""

    item_id: str
    confirmation: str


class CorrectPayload(BaseModel):
    """纠正响应：新条目标识 + 被取代的旧条目标识（契约第 4 节）。"""

    item_id: str
    supersedes: str


class RejectPayload(BaseModel):
    """否定响应（契约第 4.1 节）。"""

    item_id: str
    confirmation: str


class DeletePayload(BaseModel):
    """删除响应（契约第 4 节的形状）。

    `already` 是契约保留字段：本实现只在真的删到行时返回 200（`already` 恒为
    `false`），没删到行的一律 404，因此它不再表示「此前已删除」。
    """

    item_id: str
    already: bool


class CreateItemPayload(BaseModel):
    """补充条目响应（契约第 5 节）。"""

    item_id: str


# ---------------------------------------------------------------------------
# 形状转换
# ---------------------------------------------------------------------------


def _object_payload(record: SupportObject) -> SupportObjectPayload:
    """把支持对象行转成对外形状。"""
    return SupportObjectPayload(
        id=str(record.id),
        display_name=record.display_name,
        archived_at=record.archived_at,
    )


def _item_payload(view: service.ItemView, *, support_object_id: str) -> ProfileItemPayload:
    """把条目视图转成对外形状。

    `support_object_id` 由调用方从路径取：`ItemView` 不重复携带它（它由查询的
    WHERE 条件固定），而个性化档案第 2 节的数据形状里有这个字段，前端也靠它
    把条目归到对象名下。
    """
    return ProfileItemPayload(
        item_id=view.item_id,
        support_object_id=support_object_id,
        domain=view.domain,
        topic=view.topic,
        description=view.description,
        contexts=list(view.contexts),
        manifestations=list(view.manifestations),
        person_report=view.person_report,
        probable_need=view.probable_need,
        helpful_support=list(view.helpful_support),
        unhelpful_support=list(view.unhelpful_support),
        origin=view.origin,
        # 来源定位原样透出（不裁剪、不改名）：它是可复核性的载体，
        # 键名随写入方（工具层与补充条目各有一套键）而不同，本面不做归一。
        source=dict(view.source),
        confirmation=view.confirmation,
        freshness=view.freshness,
        first_recorded_at=view.first_recorded_at,
        last_confirmed_at=view.last_confirmed_at,
        superseded_by=view.superseded_by,
        supersedes=view.supersedes,
    )


def _item_uuid(raw: str) -> uuid.UUID | None:
    """解析条目路径参数；非法返回 None。

    非法标识与「不存在」必须得到同一个结果（404）——区分二者会让调用方得以
    枚举「碰巧猜中真实标识」与「根本不是合法标识」（`core/authz` 与
    `service._load_owned_item` 的同一处理）。
    """
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 支持对象端点（契约第 2 节）
# ---------------------------------------------------------------------------


@router.get("/objects", response_model=ObjectListPayload)
async def list_objects(account_id: Annotated[str, Depends(current_account)]) -> ObjectListPayload:
    """列出当前账号的支持对象，含已归档对象（契约第 2.1 节）。

    含已归档对象是有意的：前端据此在切换器里标注「已归档」并给出恢复入口；
    过滤掉它们会让使用者以为对象被删了。
    """
    async with session_scope(get_settings()) as session:
        records = await service.list_objects(session, account_id=account_id)
    return ObjectListPayload(items=[_object_payload(record) for record in records])


@router.post("/objects", response_model=SupportObjectPayload, status_code=201)
async def create_object(
    account_id: Annotated[str, Depends(current_account)],
    payload: Annotated[CreateObjectRequest, Body()],
) -> SupportObjectPayload | JSONResponse:
    """创建一个支持对象（契约第 2.1 节）。

    属主取登录态、不接受调用方传入；空名（去空白后为空）由用例层拒绝并映射 422。
    """
    try:
        async with session_scope(get_settings()) as session:
            record = await service.create_object(session, account_id=account_id, display_name=payload.display_name)
    except ProfileError as exc:
        return _map_error(exc)
    return _object_payload(record)


@router.patch("/objects/{support_object_id}", response_model=SupportObjectPayload)
async def patch_object(
    support_object_id: str,
    account_id: Annotated[str, Depends(current_account)],
    payload: Annotated[PatchObjectRequest, Body()],
) -> SupportObjectPayload | JSONResponse:
    """改名 / 归档 / 恢复（契约第 2.2 节）。

    三个操作合在一个端点上，因为它们都是同一个状态位的赋值（`display_name`
    或 `archived_at`）；拆成三个端点会让改名与归档各自带一份相同的越权判定。

    两个字段都给时先落归档状态、再改名：这样 `{display_name, archived: false}`
    能在归档对象上表达「恢复并改名」，而 `{display_name, archived: true}`
    仍是改名失败（`rename_object` 明确拒绝已归档对象）——顺序写反会让
    「恢复并改名」变成 409。

    Raises:
        RuntimeError: 走到「没有任何状态变更」的分支。这在入口判空之后不可达
            （两个字段至少给了一个）；显式失败而不是静默返回 200，因为静默 200
            会让调用方以为改名成功了。
    """
    if payload.display_name is None and payload.archived is None:
        return _error(422, "请求至少要给出 display_name 或 archived 之一", "invalid_payload")

    try:
        async with session_scope(get_settings()) as session:
            record = None
            if payload.archived is True:
                record = await service.archive_object(
                    session, account_id=account_id, support_object_id=support_object_id
                )
            elif payload.archived is False:
                record = await service.restore_object(
                    session, account_id=account_id, support_object_id=support_object_id
                )
            if payload.display_name is not None:
                record = await service.rename_object(
                    session,
                    account_id=account_id,
                    support_object_id=support_object_id,
                    display_name=payload.display_name,
                )
    except (AuthorizationError, ProfileError) as exc:
        return _map_error(exc)
    if record is None:  # pragma: no cover —— 上面的判空已排除两个字段都缺的情形
        raise RuntimeError("patch_object 走到了没有状态变更的分支")
    return _object_payload(record)


# ---------------------------------------------------------------------------
# 档案读取端点（契约第 3 节）
# ---------------------------------------------------------------------------


@router.get("/objects/{support_object_id}/summary", response_model=SummaryPayload)
async def read_summary(
    support_object_id: str,
    account_id: Annotated[str, Depends(current_account)],
) -> SummaryPayload | JSONResponse:
    """一页摘要：十二个字段，只取稳定层（契约第 3 节）。

    越权与不存在都必须显式失败，不得用空摘要冒充「没有档案」——那会让
    「这不是你的对象」看起来像「这个人还没有档案」。
    """
    try:
        async with session_scope(get_settings()) as session:
            summary = await service.summary(session, account_id=account_id, support_object_id=support_object_id)
    except (AuthorizationError, ProfileError) as exc:
        return _map_error(exc)

    return SummaryPayload(
        fields=[
            SummaryFieldPayload(
                key=field.key,
                label=field.label,
                items=[
                    SummaryEntryPayload(
                        item_id=entry.item_id,
                        origin=entry.origin,
                        last_confirmed_at=entry.last_confirmed_at,
                        text=entry.description,
                        freshness=entry.freshness,
                    )
                    for entry in field.items
                ],
            )
            for field in summary.fields
        ],
        has_profile=summary.has_profile,
    )


@router.get("/objects/{support_object_id}/items", response_model=ItemsPayload)
async def list_items(
    support_object_id: str,
    account_id: Annotated[str, Depends(current_account)],
    domain: Annotated[list[str] | None, Query(description="领域过滤，可重复传入")] = None,
    include_candidates: Annotated[bool, Query()] = False,
    include_superseded: Annotated[bool, Query(description="是否一并返回已被取代的历史条目（默认不返回）")] = False,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=ITEMS_MAX_LIMIT)] = ITEMS_DEFAULT_LIMIT,
) -> ItemsPayload | JSONResponse:
    """读取条目，候选层单独成组（契约第 3 节）。

    候选不混进 `items` 是候选层视觉不变量的服务端侧保证（`AC-18`）：由返回
    结构保证，而不是靠前端自己分。

    `candidates` 只在第一页返回：候选层是「待确认」小分组、不是可分页的流，
    而 `items` 才是被游标分页的那一条流。把两者混在一个游标里需要「合并后的
    原始顺序」，而用例层的返回结构已经把它们分成两组、丢失了交错关系。

    已被取代的历史条目默认不返回。`include_superseded = true` 时它们一并返回
    （带 `freshness = historical` 与互指的 `superseded_by`／`supersedes`），
    由档案页出行首「已更正」标。归组由用例层的 `_group` 决定，不是「历史一律进
    `items`」：历史条目的新鲜度先按 `current` 归一，再走落层判据——未确认的系统推断
    即便已被取代也归 `candidates`（`AC-18`），已确认或非推断来源的才归 `items`。
    落在 `items` 里的历史条目与 `items` 同一条流、同一个排序，按既有的首次记录时间
    倒序插在它原本的位置上。这个开关只放宽「已被取代」，`confirmation = rejected`
    的条目一律不返回，历史回看不适用于被否定的内容。
    `include_candidates` 管的是另一条轴（候选层是否返回），两者不互斥。
    """
    # 游标是本面自定的不透明串（十进制偏移量），只由本面产生、只被本面消费。
    # 用偏移量而不是键集游标：用例层只接 `limit`（不接「从某键之后」的谓词），
    # 面层无法把键集条件下推到查询里，硬做只会得到「看起来是键集、实际是全量重排」
    # 的分页。代价是深翻页需要多读若干行，因此配上 `PAGE_WINDOW_MAX` 硬上界。
    offset = parse_offset_cursor(cursor)
    if offset is None:
        return _error(422, "cursor 不是本面发出的游标", "invalid_payload")

    try:
        async with session_scope(get_settings()) as session:
            grouped = await service.read_items(
                session,
                account_id=account_id,
                support_object_id=support_object_id,
                domains=domain,
                include_candidates=include_candidates,
                include_superseded=include_superseded,
                limit=_page_window(offset, limit),
            )
    except (AuthorizationError, ProfileError) as exc:
        return _map_error(exc)

    stable = grouped.items[offset : offset + limit]
    has_more = len(grouped.items) > offset + limit
    candidates = grouped.candidates if offset == 0 else []

    return ItemsPayload(
        items=[_item_payload(view, support_object_id=support_object_id) for view in stable],
        candidates=[_item_payload(view, support_object_id=support_object_id) for view in candidates],
        next_cursor=str(offset + limit) if has_more else None,
    )


# ---------------------------------------------------------------------------
# 确认、纠正、否定、删除（契约第 4 节）
# ---------------------------------------------------------------------------


@router.post("/items/{item_id}/confirm", response_model=ConfirmPayload)
async def confirm_item(
    item_id: str,
    account_id: Annotated[str, Depends(current_account)],
) -> ConfirmPayload | JSONResponse:
    """确认一条候选条目，此后进稳定层（契约第 4 节）。

    只能作用于未被取代、且 `confirmation = unconfirmed` 的条目；对已确认、
    已否定或已被取代的条目由用例层拒绝并映射 422（重复确认是调用方的错误，
    不是幂等操作；历史条目只可回看，没有确认这条能力）。
    """
    if _item_uuid(item_id) is None:
        return _error(404, OBJECT_NOT_ACCESSIBLE_MESSAGE, "not_found")
    try:
        async with session_scope(get_settings()) as session:
            row = await service.confirm_item(session, account_id=account_id, item_id=item_id)
    except (AuthorizationError, ProfileError) as exc:
        return _map_error(exc)
    return ConfirmPayload(item_id=str(row.item_id), confirmation=row.confirmation)


@router.post("/items/{item_id}/correct", response_model=CorrectPayload, status_code=201)
async def correct_item(
    item_id: str,
    account_id: Annotated[str, Depends(current_account)],
    payload: Annotated[CorrectItemRequest, Body()],
) -> CorrectPayload | JSONResponse:
    """纠正 = 新增取代条目，旧条目转 `historical` 并互指（契约第 4 节）。

    不物理覆盖：旧条目保留可回看，注入只含新条目。
    """
    if _item_uuid(item_id) is None:
        return _error(404, OBJECT_NOT_ACCESSIBLE_MESSAGE, "not_found")
    try:
        async with session_scope(get_settings()) as session:
            new_item, old_item = await service.correct_item(
                session,
                account_id=account_id,
                item_id=item_id,
                description=payload.description,
                topic=payload.topic,
                contexts=payload.contexts,
                manifestations=payload.manifestations,
            )
    except (AuthorizationError, ProfileError) as exc:
        return _map_error(exc)
    return CorrectPayload(item_id=str(new_item.item_id), supersedes=str(old_item.item_id))


@router.post("/items/{item_id}/reject", response_model=RejectPayload)
async def reject_item(
    item_id: str,
    account_id: Annotated[str, Depends(current_account)],
) -> RejectPayload | JSONResponse:
    """否定一条候选：不物理删除，此后不进摘要、不参与注入、不再作候选（契约第 4.1 节）。

    与删除分开是因为语义不同：「使用者否定过这件事」本身是可追溯事实，
    放进删除端点会丢掉这个语义（第 4.1 节）。
    """
    if _item_uuid(item_id) is None:
        return _error(404, OBJECT_NOT_ACCESSIBLE_MESSAGE, "not_found")
    try:
        async with session_scope(get_settings()) as session:
            row = await service.reject_item(session, account_id=account_id, item_id=item_id)
    except (AuthorizationError, ProfileError) as exc:
        return _map_error(exc)
    return RejectPayload(item_id=str(row.item_id), confirmation=row.confirmation)


@router.delete("/items/{item_id}", response_model=DeletePayload)
async def delete_item(
    item_id: str,
    account_id: Annotated[str, Depends(current_account)],
) -> DeletePayload | JSONResponse:
    """删除一条条目（契约第 4 节）。

    越权与不存在的响应逐字相同：两者都由用例层归为「不可访问」，经
    `_map_error` 得到同一个 404——面层不另开一条错误路径，也就没有
    「两条路径文案漂移」的可能。

    幂等只覆盖「本账号尚未删过这条、且条目确实存在」的第一次删除：条目是物理
    删除，库表里没有留痕，因此第二次删除与「从未存在」在服务端不可区分，一律
    404（契约第 6 节「条目不存在 → 404」；2026-09-30 编排器裁决 1：删除的
    越权或不存在不得返回 200）。
    """
    if _item_uuid(item_id) is None:
        return _error(404, OBJECT_NOT_ACCESSIBLE_MESSAGE, "not_found")
    try:
        async with session_scope(get_settings()) as session:
            await service.delete_item(session, account_id=account_id, item_id=item_id)
    except (AuthorizationError, ProfileError) as exc:
        return _map_error(exc)
    return DeletePayload(item_id=item_id, already=False)


# ---------------------------------------------------------------------------
# 补充条目（契约第 5 节）
# ---------------------------------------------------------------------------


@router.post("/objects/{support_object_id}/items", response_model=CreateItemPayload, status_code=201)
async def create_item(
    support_object_id: str,
    account_id: Annotated[str, Depends(current_account)],
    payload: Annotated[CreateItemRequest, Body()],
) -> CreateItemPayload | JSONResponse:
    """使用者在档案页手动补充一条（契约第 5 节）。

    `origin` 由用例层定为 `user_statement`，来源定位由用例层补（该入口的请求体
    不含 `source`）。归档对象上新增返回 409 `object_archived`，文案区分于越权：
    属主自己的对象，使用者需要知道原因才能去恢复。
    """
    try:
        async with session_scope(get_settings()) as session:
            row = await service.add_manual_item(
                session,
                account_id=account_id,
                support_object_id=support_object_id,
                domain=payload.domain,
                topic=payload.topic,
                description=payload.description,
                contexts=payload.contexts,
                manifestations=payload.manifestations,
            )
    except (AuthorizationError, ProfileError) as exc:
        return _map_error(exc)
    return CreateItemPayload(item_id=str(row.item_id))


__all__ = [
    "ITEMS_DEFAULT_LIMIT",
    "ITEMS_MAX_LIMIT",
    "PAGE_WINDOW_MAX",
    "current_account",
    "router",
]
