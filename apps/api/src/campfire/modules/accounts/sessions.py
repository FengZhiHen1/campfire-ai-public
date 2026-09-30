"""会话归属的用例层：登记、越权判定、会话列表与历史水合。

职责：会话归属的四个用例（`register_session` / `require_session_owner` /
`list_sessions` / `load_history`）与账号注销时的归属行清除。
边界：只管归属与呈现的编排；消息的存储归 SDK，对象名经注入回调取，越权文案由本层统一。
参考：docs/技术设计/decisions/会话归属单立表归accounts.md；
docs/技术设计/面/consult/HTTP与SSE契约.md 第 3.2、3.3、7 节；
docs/项目结构设计.md 第 6 节（accounts 用例行）、第 7 节（依赖白名单）。

三段边界写在这里的理由：

归属与消息分开。`campfire_session` 只回答「这个会话属于哪个账号」，SDK 的两张表
回答「这个会话里有什么」。两者不互相推导：归属行的存在不意味着有消息（刚建的会话），
有消息也不意味着归属行冗余（SDK 表没有 `account_id`）。因此水合必须先判归属再读
消息——顺序反了会让一次越权请求真的读出对方的内容，也让失败路径的耗时依赖消息量，
而两种失败必须不可区分（HTTP 契约第 3.3 节），耗时差异本身就是一条区分通道。

对象名经注入取。会话列表要显示支持对象名，而对象归 `modules/profile`；模块之间
禁止互相 import（项目结构设计第 7 节）。因此这里接受一个 `object_name_reader` 回调，
由装配处（面层）传入 profile 的取数实现。回调做成「批量取、返回映射」：逐会话回调
会让一页 20 条变成 20 次查询，而列表是高频入口。

标题与预览不落库。两者都从会话真源算（见 `session_items`）。存它们会造出第二个
可写真源：消息改了标题不会跟着改，冲突时无法判断谁对（与「默认对象」不另存字段
同一种取向，支持对象第 6 节）。
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from campfire.core.auth.deletion import PurgeOutcome
from campfire.core.config import Settings
from campfire.core.db import session_scope
from campfire.modules.accounts import session_repository as repo
from campfire.modules.accounts.errors import (
    SessionNotFoundError,
    SessionQueryError,
    SessionRegistrationError,
)
from campfire.modules.accounts.session_items import (
    HydratedMessage,
    StoredItem,
    build_messages,
    build_preview,
    build_title,
    first_user_message_text,
    last_message_text,
)

logger = logging.getLogger(__name__)

#: 对象名取数回调：给定一页的会话标识，返回（会话标识 → 支持对象名）。
#:
#: 契约细节（实现者须遵守）：
#: - 没有绑定对象（或对象名取不到）的会话不要出现在返回映射里——调用方据此把
#:   该字段置为 `None`（契约第 3.2 节：缺失时前端不渲染该字段，不留占位符）；
#: - 不认识的会话标识应被忽略而不是报错：一页里可能混有刚建、尚未绑定的会话。
#:
#: 实现归 `modules/profile`（它拥有绑定表与对象表），由装配处注入。
ObjectNameReader = Callable[[Sequence[str]], Awaitable[dict[str, str]]]

#: 分页游标的载荷版本。将来改变游标编码时用它区分，避免把旧游标按新格式解读。
_CURSOR_VERSION = 1


# ---------------------------------------------------------------------------
# 结果类型
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SessionOwner:
    """登记结果：会话标识 + 归属账号 + 本次是否新建。"""

    session_id: str
    account_id: str
    created: bool
    """本次是否真的插入了新行。`False` 表示重复登记（幂等分支），供面层记日志。"""


@dataclass(frozen=True, slots=True)
class SessionSummaryView:
    """会话列表的一行（HTTP 与 SSE 契约第 3.2 节）。"""

    session_id: str
    title: str
    support_object_name: str | None
    updated_at: datetime
    last_message_preview: str | None


@dataclass(frozen=True, slots=True)
class SessionPage:
    """一页会话列表。"""

    items: list[SessionSummaryView]
    next_cursor: str | None
    """下一页游标；没有更多时为 `None`（契约第 3.2 节：`next_cursor` 可空）。"""


@dataclass(frozen=True, slots=True)
class SessionHistory:
    """一次历史水合的结果（HTTP 与 SSE 契约第 3.3 节）。"""

    session_id: str
    messages: list[HydratedMessage]


# ---------------------------------------------------------------------------
# 归属登记与判定
# ---------------------------------------------------------------------------


async def register_session(session: AsyncSession, *, session_id: str, account_id: str) -> SessionOwner:
    """登记会话归属；幂等。

    调用时机是会话创建端点，且必须早于写 SDK 会话（决策记录的实现约束：
    「写 SDK 会话之前落行；写行失败则不建会话——不得出现『能读但无归属』的会话」）。
    本函数不负责那个顺序，调用方负责。

    三种结果：

    - 该会话尚未登记 → 插入一行，`created=True`；
    - 已登记且属主相同 → 无操作，`created=False`（重复登记是正常路径：
      会话创建可能被重试，而归属只有一个正确答案）；
    - 已登记但属主不同 → 抛 :class:`SessionRegistrationError`，不修改既有行。

    为什么属主不同是错误而不是「更新归属」：允许改属主等于允许把别人的会话据为己有
    ——一次会话标识猜测就能把对方的历史挂到自己名下，整张归属表的意义随之消失。
    这里选择显式失败，而不是静默保持旧属主（那会让调用方以为登记成功了）。

    Args:
        session: 关系库会话（调用方负责事务边界）。
        session_id: 会话标识（由会话创建端点生成）。
        account_id: 归属账号（取登录态）。

    Returns:
        :class:`SessionOwner`。

    Raises:
        SessionRegistrationError: 该会话已登记在另一个账号名下。
        SessionQueryError: 任一标识形状不合法。
    """
    owner, created = await repo.insert_session_owner(session, session_id=session_id, account_id=account_id)

    if owner.account_id != account_id:
        # 不把两个账号标识写进异常消息：它们都是可枚举的敏感值
        # （同 `SessionNotFoundError` 不携带会话标识的理由）。
        raise SessionRegistrationError()

    return SessionOwner(session_id=owner.session_id, account_id=owner.account_id, created=created)


async def require_session_owner(session: AsyncSession, *, session_id: str, account_id: str) -> None:
    """判定该会话属于该账号，否则抛 :class:`SessionNotFoundError`。

    这是所有按会话取数的唯一入口（水合，以及将来的取消与订阅）。做成一抛错函数
    而不是返回 `bool`：返回布尔值时「忘了检查返回值」是一条静默失效路径，而这条判定
    正是越权边界（与 `core/authz` 的 `require_owned` 同一个理由，支持对象 5.1）。

    不存在与属主不符合并为同一条异常、同一条文案（`SessionNotFoundError.MESSAGE`）：
    区分二者等于提供会话枚举通道。

    Args:
        session: 关系库会话（只读）。
        session_id: 会话标识。
        account_id: 当前账号。

    Raises:
        SessionNotFoundError: 会话不存在，或存在但不属于该账号。
        SessionQueryError: 任一标识形状不合法。
    """
    owned = await repo.is_session_owned_by(session, session_id=session_id, account_id=account_id)
    if not owned:
        raise SessionNotFoundError()


# ---------------------------------------------------------------------------
# 会话列表
# ---------------------------------------------------------------------------


def encode_cursor(marker: datetime, session_id: str) -> str:
    """把游标编码成不透明字符串。

    不透明（base64 的 JSON）而不是明文时间戳：游标是服务端的翻页凭据，不是客户端
    可构造的查询参数。明文会诱使调用方手写一个游标（绕过校验、塞一个不存在的会话标识），
    而解析失败必须显式报错（CORE-07：无静默兜底）。
    """
    payload = json.dumps({"v": _CURSOR_VERSION, "t": marker.isoformat(), "s": session_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(raw: object) -> tuple[datetime, str] | None:
    """解析游标；`None` 或空串表示首页，其余非法输入显式报错。

    为什么非法游标要报错而不是回退到首页：回退会让调用方在触底分页里反复拿到第一页
    并以为「刷新了」，于是无限循环。显式拒绝让问题当场可见（CORE-07）。

    为什么要求时间戳带时区：本游标由 :func:`encode_cursor` 产出，而它总是写入带时区的
    值。一个不带时区的游标只可能来自手写或旧版本，按本地时区解释它会让翻页结果依赖
    服务器配置——宁可拒绝。

    Args:
        raw: 来自查询参数的游标，类型未知。

    Returns:
        `(最近活动时间, 会话标识)`；首页时为 `None`。

    Raises:
        SessionQueryError: 游标非字符串、不是合法 base64、JSON 结构不符、版本不符，
            或时间戳不可解析/缺时区。
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise SessionQueryError("游标必须是字符串")
    if not raw:
        return None

    try:
        decoded = base64.urlsafe_b64decode(raw.encode("ascii"))
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise SessionQueryError("游标不是合法的 base64 文本") from exc
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise SessionQueryError("游标解码后不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise SessionQueryError("游标解码后不是 JSON 对象")
    if payload.get("v") != _CURSOR_VERSION:
        raise SessionQueryError("游标版本不被支持")

    marker_raw = payload.get("t")
    session_raw = payload.get("s")
    if not isinstance(marker_raw, str) or not isinstance(session_raw, str) or not session_raw:
        raise SessionQueryError("游标缺少时间或会话标识")
    try:
        marker = datetime.fromisoformat(marker_raw)
    except ValueError as exc:
        raise SessionQueryError("游标里的时间戳无法解析") from exc
    if marker.tzinfo is None:
        raise SessionQueryError("游标里的时间戳缺少时区")
    return marker, session_raw


def validate_limit(raw: object) -> int:
    """校验列表条数参数（契约第 3.2 节：默认 20、上限 50）。

    超上界显式拒绝而不是截断到 50：截断会让调用方以为拿到了 50 条，而它请求的是
    200 条——它无法从响应里看出这件事（`next_cursor` 只说明还有更多）。

    Args:
        raw: 来自查询参数的 `limit`；`None` 表示未传。

    Returns:
        合法的条数。

    Raises:
        SessionQueryError: 非整数、小于 1，或超过 `repo.LIST_MAX_LIMIT`。
    """
    if raw is None:
        return repo.LIST_DEFAULT_LIMIT
    # `bool` 是 `int` 的子类：`limit=true` 会被当成 1。显式排除——前端传一个布尔值
    # （JSON 里很常见）会静默变成「只要一条」，而调用方看不出原因。
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise SessionQueryError(f"limit 必须是整数，收到 {type(raw).__name__}")
    if raw < 1:
        raise SessionQueryError("limit 必须大于等于 1")
    if raw > repo.LIST_MAX_LIMIT:
        raise SessionQueryError(f"limit 不得超过 {repo.LIST_MAX_LIMIT}")
    return raw


# quality-floor: ignore docstring-promise 异常由 validate_limit/decode_cursor/仓储层抛出（间接 raise），本函数只做编排
async def list_sessions(
    session: AsyncSession,
    *,
    account_id: str,
    cursor: object = None,
    limit: object = None,
    object_name_reader: ObjectNameReader | None = None,
) -> SessionPage:
    """列出该账号的会话（HTTP 与 SSE 契约第 3.2 节）。

    四路取数，各一次查询覆盖整页：

    1. 归属行 + 最近活动时间（`repo.list_session_owners`，已按活动时间倒序、游标翻页）；
    2. 每会话开头若干条目 → 标题（`repo.read_first_items`）；
    3. 每会话末尾若干条目 → 末条预览（`repo.read_last_items`）；
    4. 对象名（注入的 `object_name_reader`）。

    标题与预览只对本页的会话算，不为整账号算。

    `next_cursor` 的判据是「本页取满了 `limit` 条」，不是「还有更多行」。这是有意的：
    多取一条来判断「是否还有」会让每次翻页都多一次查询，而多给一个游标是无害的
    （下一页为空时返回空列表 + `None` 游标，前端自然停在空页）。代价是最后一页会多
    一次请求，这是列表分页的常规取舍。

    Args:
        session: 关系库会话（只读）。
        account_id: 归属账号。
        cursor: 游标（`None` 为首页）。
        limit: 条数（`None` 用默认值）。
        object_name_reader: 对象名取数回调；未注入时 `support_object_name` 一律为 `None`
            ——不是错误，前端对缺失字段的处理就是不渲染（列表页第 36 行）。

    Returns:
        :class:`SessionPage`。

    Raises:
        SessionQueryError: 游标或 `limit` 不合法，或账号标识形状不合法。
    """
    validated_limit = validate_limit(limit)
    before = decode_cursor(cursor)

    rows = await repo.list_session_owners(session, account_id=account_id, before=before, limit=validated_limit)
    session_ids = [row.owner.session_id for row in rows]

    first_items = await repo.read_first_items(session, session_ids=session_ids)
    last_items = await repo.read_last_items(session, session_ids=session_ids)
    object_names = await _read_object_names(session_ids=session_ids, reader=object_name_reader)

    items = [
        SessionSummaryView(
            session_id=row.owner.session_id,
            title=build_title(first_user_message_text(first_items.get(row.owner.session_id, ()))),
            support_object_name=object_names.get(row.owner.session_id),
            updated_at=row.updated_at,
            last_message_preview=build_preview(last_message_text(last_items.get(row.owner.session_id, ()))),
        )
        for row in rows
    ]

    next_cursor = None
    if rows and len(rows) == validated_limit:
        last = rows[-1]
        next_cursor = encode_cursor(last.updated_at, last.owner.session_id)
    return SessionPage(items=items, next_cursor=next_cursor)


async def _read_object_names(*, session_ids: Sequence[str], reader: ObjectNameReader | None) -> dict[str, str]:
    """经注入的回调取对象名；未注入或没有会话时返回空映射。

    本函数不读绑定表：绑定关系归 `modules/profile`（`campfire_session_object`），
    而模块之间禁止互相 import。回调由装配处提供，它同时掌握绑定表与对象表。
    """
    if reader is None or not session_ids:
        return {}
    return dict(await reader(list(session_ids)))


# ---------------------------------------------------------------------------
# 历史水合
# ---------------------------------------------------------------------------


# quality-floor: ignore docstring-promise 异常由 require_session_owner 抛出并原样传播，函数体只做编排
async def load_history(session: AsyncSession, *, session_id: str, account_id: str) -> SessionHistory:
    """水合一条会话的历史（HTTP 与 SSE 契约第 3.3 节）。

    顺序不可换：先判归属，再读消息。先读消息会让一次越权请求真的读出对方的内容
    （哪怕随后丢弃），也让失败路径的耗时依赖消息量——而两种失败必须不可区分，
    耗时差异本身就是一条区分通道。

    失败不冒充空对话（第 3.3 节「水合失败显示错误与重试，不显示空对话冒充成功」）：
    归属不成立时抛 :class:`SessionNotFoundError`，而不是返回 `messages=[]`。一条真的
    没有消息的会话返回 `messages=[]`——两者在数据层就是不同的结果，面层据此给出
    404 与 200 空列表两种响应。

    Args:
        session: 关系库会话（只读）。
        session_id: 会话标识。
        account_id: 当前账号。

    Returns:
        :class:`SessionHistory`，顺序即会话真源顺序。

    Raises:
        SessionNotFoundError: 会话不存在，或存在但不属于该账号。
        SessionQueryError: 任一标识形状不合法。
    """
    await require_session_owner(session, session_id=session_id, account_id=account_id)
    stored: list[StoredItem] = await repo.read_all_items(session, session_id=session_id)
    return SessionHistory(session_id=session_id, messages=build_messages(stored))


# ---------------------------------------------------------------------------
# 账号注销：清除该账号的会话归属行
# ---------------------------------------------------------------------------


class SessionAccountPurger:
    """清除某账号的会话归属行（实现 `core/auth` 的 purger 端口）。

    为什么需要它：[认证与账号] 第 8 节要求「删除 `campfire_session` 中该账号的会话
    归属行」，且必须早于删身份用户。该顺序由注销编排保证（领域清除是第 4 步、删身份
    用户是第 5 步）。删掉它是 fail-closed：残留的归属行会让已注销账号的会话仍通过
    归属判定。

    第 8 节给出的理由是「身份用户一旦删除，就再也无法按 `account_id` 定位这些行」；
    本实现不依赖身份服务定位（`purge_account` 的入参就是 `account_id`），顺序的收益
    是让删身份用户成为整件事的提交点——见 `core/auth/deletion` 的顺序说明。

    为什么不删 SDK 的两张表：那两张表的内容由 SDK 拥有，且会话撤销（第 5 步，经身份
    服务）已让它们不可达；本 purger 只负责业务侧的归属行，不越界。

    幂等：账号没有会话时返回「无数据可清」，不报错——重试注销是正常路径
    （见 `core/auth/deletion` 的幂等说明）。

    `name` 属性（`"session-owner"`）刻意不与 `"profile"` / `"memory"` 重复：注销编排的
    步骤名从它取，多个清除者并存时操作者据此分辨「哪个领域已清过」。名字带 `owner`
    是为了说清它清的是归属行，不是对话内容（后者不归我们删）。
    """

    #: 清除者的领域名（编排步骤名与结果汇总共用，勿与类名耦合）。
    name = "session-owner"

    def __init__(self, settings: Settings) -> None:
        """记录配置。

        Args:
            settings: 应用配置（数据库连接的唯一来源）。
        """
        self._settings = settings

    # quality-floor: ignore docstring-promise 异常由 session_scope 与仓储层抛出并原样传播，函数体只做编排
    async def purge_account(self, account_id: str) -> PurgeOutcome:
        """真删该账号的全部会话归属行。

        Args:
            account_id: 账号标识。

        Returns:
            :class:`PurgeOutcome`，说明删了多少行。

        Raises:
            Exception: 数据库操作失败。不吞——静默失败会让「已删除」成为一句谎话
                （见端口的实现者契约）。
        """
        async with session_scope(self._settings) as session:
            deleted = await repo.delete_session_owners_for_account(session, account_id=account_id)

        detail = f"删除会话归属行 {deleted} 条"
        logger.info("会话归属清除完成：标识=%s %s", account_id, detail)
        return PurgeOutcome(name=self.name, detail=detail)


__all__ = [
    # 回调形状
    "ObjectNameReader",
    # 结果类型
    "SessionHistory",
    "SessionOwner",
    "SessionPage",
    "SessionSummaryView",
    # 登记与判定
    "register_session",
    "require_session_owner",
    # 列表
    "decode_cursor",
    "encode_cursor",
    "list_sessions",
    "validate_limit",
    # 水合
    "load_history",
    # 注销清除
    "SessionAccountPurger",
]
