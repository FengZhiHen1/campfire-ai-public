"""会话归属行与 SDK 会话存储的存储层读写。

职责：`campfire_session` 的登记与归属判定，以及只读 SDK 的
`agent_sessions` / `agent_messages`（会话列表与水合的数据来源）。
边界：只做存储层语句，不含用例编排与对外文案；事务由调用方（`sessions`）持有。
参考：docs/技术设计/decisions/会话归属单立表归accounts.md；
docs/技术设计/面/consult/HTTP与SSE契约.md 第 3.2、3.3 节；
docs/项目结构设计.md 第 10 节（表归属与迁移白名单）。

三条落在此层的纪律：

- 绝不写 SDK 的表。SDK 拥有那两张表的写入语义（它按自己的条目格式序列化），
  我方替它写会造出它读不懂的行。读用显式 `SELECT`，绕过 SDK 的会话对象——那对象
  按 `session_id` 绑定单个会话，而列表要跨会话批量取。
- 归属行的登记靠主键冲突，不靠先查后写。并发下「先查后写」会写出两行或在
  属主冲突时静默改属主（见 :func:`insert_session_owner`）。
- 对象名不由本层取。它归 `modules/profile`，而模块之间禁止互相 import
  （项目结构设计第 7 节）。取数经注入的回调，见 `sessions.list_sessions`。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.core.db.sdk_session import AgentMessage, AgentSession
from campfire.modules.accounts.errors import SessionQueryError
from campfire.modules.accounts.models import MAX_ACCOUNT_ID_LENGTH, MAX_SESSION_ID_LENGTH, CampfireSession
from campfire.modules.accounts.session_items import StoredItem, parse_item

#: 会话列表的默认条数（HTTP 与 SSE 契约第 3.2 节：`limit` 默认 20）。
LIST_DEFAULT_LIMIT = 20

#: 会话列表的条数上界（第 3.2 节：上限 50）。超界显式拒绝而不是静默截断
#: ——静默截断会让调用方以为拿到了全部（CORE-07）。
LIST_MAX_LIMIT = 50

#: 标题与预览需要扫描的条目条数上界（CORE-11）。
#:
#: 为什么需要一个上界：标题要「首条使用者消息」，而首条之前会先落一条或多条应用
#: 注入消息（技能目录、工具可用性、档案摘要…）。这些之后，首条使用者消息通常在
#: 前十条之内就到齐了。上界的意义不是「可能撞满」，而是不让一条只有注入消息的
#: 异常会话把整表拉进内存。取 50：远大于一次运行的注入条数，又不至于让单个会话的
#: 扫描量失控。
LIST_SCAN_MAX_ITEMS = 50

#: 末条预览需要回看的条目条数上界。尾部可能有一串思考段与工具结果，取 20 足够跨过它们。
LAST_MESSAGE_SCAN_MAX_ITEMS = 20

#: SDK 时间戳列的时区。SDK 的两张表是 `timestamp without time zone`，写进去的是
#: `CURRENT_TIMESTAMP`，因此它的语义取决于数据库会话时区——实测本库是
#: `Etc/UTC`。跨表比较时必须显式声明这一点（见 :func:`_effective_updated_at`）：
#: 依赖服务器时区会让同一个查询在时区配置不同的库上给出不同结果。
_SDK_TIMESTAMP_TZ = timezone.utc

#: 显式把裸时间戳解释成 UTC 时用的时区名。与 `_SDK_TIMESTAMP_TZ` 同源，
#: 单独列出是因为它是写进 SQL 的字面量（`timezone('UTC', col)`）。
_SDK_TIMESTAMP_SQL_TZ = "UTC"


def _utc_now() -> datetime:
    """当前 UTC 时间。集中一处，便于测试替换时只有一个改动点。"""
    return datetime.now(timezone.utc)


def to_sdk_datetime(value: datetime | None) -> datetime | None:
    """把 SDK 表的裸时间戳标成 UTC；`None` 原样返回。

    只在缺失时区信息时补：带时区的值不该被改写（那会让一个明确的时刻被重新解释）。
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=_SDK_TIMESTAMP_TZ)
    return value


def validate_session_id(raw: object) -> str:
    """校验会话标识的形状（CORE-04：数据边界运行时解析）。

    会话标识来自 URL 路径，是未经校验的外部输入。不校验就进查询键有两个后果：
    超宽值会让驱动抛裸 `DBAPIError`（调用方拿到驱动异常而不是可处理的领域错误），
    全空白值会让等值查询在任何行上都为假——于是「格式非法」被伪装成「这个会话不存在」，
    而调用方据此返回 404 时看不出自己漏了校验。

    Raises:
        SessionQueryError: 非字符串、全空白，或超过 `MAX_SESSION_ID_LENGTH`。
    """
    if not isinstance(raw, str):
        raise SessionQueryError(f"会话标识必须是字符串，收到 {type(raw).__name__}")
    if not raw.strip():
        raise SessionQueryError("会话标识为空或只有空白")
    if len(raw) > MAX_SESSION_ID_LENGTH:
        raise SessionQueryError(f"会话标识超过 {MAX_SESSION_ID_LENGTH} 字符上界")
    return raw


def validate_account_id(raw: object) -> str:
    """校验账号标识的形状。判据与 :func:`validate_session_id` 同源。

    Raises:
        SessionQueryError: 非字符串、空，或超过 `MAX_ACCOUNT_ID_LENGTH`。
    """
    if not isinstance(raw, str):
        raise SessionQueryError(f"账号标识必须是字符串，收到 {type(raw).__name__}")
    if not raw:
        raise SessionQueryError("账号标识为空")
    if len(raw) > MAX_ACCOUNT_ID_LENGTH:
        raise SessionQueryError(f"账号标识超过 {MAX_ACCOUNT_ID_LENGTH} 字符上界")
    return raw


# ---------------------------------------------------------------------------
# 会话归属行
# ---------------------------------------------------------------------------


async def insert_session_owner(
    session: AsyncSession,
    *,
    session_id: str,
    account_id: str,
    now: datetime | None = None,
) -> tuple[CampfireSession, bool]:
    """登记会话归属；返回既有/新插入的行与「本次是否真的插入了」。

    冲突处理是 `ON CONFLICT (session_id) DO NOTHING`，与 `profile.insert_session_binding`
    同一种做法：把「一个会话只有一行归属」这条不变量交给主键，而不是先查后写——
    后者在并发下会写出两行，或在属主不同时静默把归属改掉。

    属主不可变：本函数只插入，从不更新 `account_id`。命中既有行时把该行
    原样返回，由调用方（`sessions.register_session`）比较属主并决定「无操作」还是
    报错。把比较放在调用方而不是这里，是因为「属主不同是错误」是对外语义，
    而本层只承担存储事实。

    为什么用 `ON CONFLICT ... RETURNING` 的返回值判断是否插入：这是唯一可靠的判据。
    「先查存在性再插入」在并发下会给出错误的 `created`；比较 `created_at` 与当前
    时间会因时间精度而抖动。冲突时 `RETURNING` 返回空集，因此重读一次既有行。

    Returns:
        `(归属行, 本次是否插入)`。第二条为 `False` 表示该会话此前已登记
        （属主相同或不同由调用方比较）。

    Raises:
        SessionQueryError: 任一标识形状不合法。
    """
    normalized_session = validate_session_id(session_id)
    normalized_account = validate_account_id(account_id)

    statement = (
        pg_insert(CampfireSession)
        .values(session_id=normalized_session, account_id=normalized_account, created_at=now or _utc_now())
        .on_conflict_do_nothing(index_elements=[CampfireSession.session_id])
        .returning(CampfireSession)
    )
    inserted = (await session.execute(statement)).scalar_one_or_none()
    if inserted is not None:
        return inserted, True

    # 冲突：该会话已有归属行。重读它——不更新，属主不可变。
    existing = await get_session_owner(session, session_id=normalized_session)
    if existing is None:  # pragma: no cover —— 冲突意味着行存在；并发删除才可能到这里
        raise SessionQueryError("会话归属行的登记与重读结果不一致")
    return existing, False


async def get_session_owner(session: AsyncSession, *, session_id: str) -> CampfireSession | None:
    """取某会话的归属行；没有则返回 `None`。

    返回 `None` 的语义是「这个会话不属于任何账号」，调用方据此按「不存在」处理
    ——不是「放行」（fail-closed：读路径上的缺行一律拒绝）。
    """
    normalized = validate_session_id(session_id)
    return (
        await session.execute(select(CampfireSession).where(CampfireSession.session_id == normalized))
    ).scalar_one_or_none()


async def is_session_owned_by(session: AsyncSession, *, session_id: str, account_id: str) -> bool:
    """该会话是否登记在这个账号名下。

    单条 `EXISTS` 查询而不是取行回来比较：调用方（`load_history`）只需要一个是非
    判定，不需要归属行的内容，而 `EXISTS` 只回一个布尔值。
    """
    normalized_session = validate_session_id(session_id)
    normalized_account = validate_account_id(account_id)
    statement = select(
        select(CampfireSession.session_id)
        .where(
            CampfireSession.session_id == normalized_session,
            CampfireSession.account_id == normalized_account,
        )
        .exists()
    )
    return bool((await session.execute(statement)).scalar_one())


@dataclass(frozen=True, slots=True)
class SessionListRow:
    """会话列表的一行：归属行 + 该会话的「最近活动时间」。

    `updated_at` 与归属行分开放，因为它来自另一张表（SDK 的活动时间），
    而不是 `campfire_session` 的列——归属表只存归属与登记（决策记录）。
    """

    owner: CampfireSession
    updated_at: datetime


def _effective_updated_at():  # noqa: ANN202 —— 返回 SQLAlchemy 表达式
    """会话「最近活动时间」的 SQL 表达式：SDK 活动时间，缺行时退回登记时间。

    为什么要 `timezone('UTC', …)`：SDK 的 `updated_at` 是 `timestamp without time
    zone`，而 `campfire_session.created_at` 是带时区的。把两者放进同一个
    `coalesce` 时，PostgreSQL 会用数据库会话时区解释那个裸时间戳——时区配置一变
    （例如部署到 `Asia/Shanghai` 的库），同一个会话的排序位置就会漂移几小时。
    显式声明 UTC 让结果与服务器配置无关。

    为什么缺行要退回登记时间：会话归属行先于 SDK 会话写入而落（决策记录的创建时机
    ——建会话端点在写 SDK 会话之前落归属行）。一个刚创建、还没发过消息的会话在
    `agent_sessions` 里没有行，若不退回，它会因为排序键为 NULL 而落到列表末尾
    （PostgreSQL 的 `DESC` 默认 `NULLS FIRST`，实际会浮到最前）——两种都不是
    「刚建的会话在最前」。
    """
    return func.coalesce(
        func.timezone(_SDK_TIMESTAMP_SQL_TZ, AgentSession.updated_at),
        CampfireSession.created_at,
    )


# quality-floor: ignore docstring-promise 异常由 validate_account_id 抛出（间接 raise），本函数只做查询
async def list_session_owners(
    session: AsyncSession,
    *,
    account_id: str,
    before: tuple[datetime, str] | None = None,
    limit: int,
) -> list[SessionListRow]:
    """按账号取会话列表行，按最近活动时间倒序，游标翻页。

    排序键是 `(最近活动时间 DESC, session_id DESC)`。决胜键不能省：活动时间的精度
    到微秒，同一批写入的会话可能撞值，只用它排序时两条记录的顺序在两次查询之间
    可能不同——游标翻页会因此漏行或重复。

    为什么排序与游标都用同一个表达式：若按 A 排序而按 B 翻页，一页里装的就
    不是「按 A 的前 N 条」，翻页会跳行。因此两者必须是同一个键（`_effective_updated_at`）。

    已知代价（如实写明）：该表达式跨两张表，`ix_campfire_session_account_created`
    只能服务账号过滤，排序走不了索引。按账号的会话行数在个人账号场景下很小
    （一位使用者的会话量），因此接受；会话量真变大时须改为物化活动时间或加表达式索引。

    为什么用游标而不是 `OFFSET`：`OFFSET` 在第 N 页要跳过前 N 页的行，而中途新登记
    的会话会把窗口推移，导致翻页重复或跳过（列表页支持触底分页，一边翻一边开新会话
    是常态）。

    Args:
        session: 关系库会话（只读）。
        account_id: 账号标识。
        before: 上一页最后一条的 `(最近活动时间, session_id)`；首页传 `None`。
        limit: 本页最多取几条（调用方已保证在界内）。

    Returns:
        本页的列表行，最多 `limit` 条。

    Raises:
        SessionQueryError: 账号标识形状不合法。
    """
    normalized_account = validate_account_id(account_id)
    effective = _effective_updated_at()

    statement = (
        select(CampfireSession, effective.label("effective_updated_at"))
        .outerjoin(AgentSession, AgentSession.session_id == CampfireSession.session_id)
        .where(CampfireSession.account_id == normalized_account)
    )
    if before is not None:
        cursor_marker, cursor_session = before
        # 行值比较（row value comparison）：等价于「按 (时间, 标识) 全序严格小于游标」，
        # 比手写 OR 展开更难写错。
        statement = statement.where(
            tuple_(effective, CampfireSession.session_id) < tuple_(cursor_marker, cursor_session)
        )
    statement = statement.order_by(effective.desc(), CampfireSession.session_id.desc()).limit(limit)

    rows: list[SessionListRow] = []
    for owner, updated_at in (await session.execute(statement)).all():
        marker = to_sdk_datetime(updated_at)
        if marker is None:  # pragma: no cover —— coalesce 保证非空，这里只是类型收窄
            marker = owner.created_at
        rows.append(SessionListRow(owner=owner, updated_at=marker))
    return rows


# ---------------------------------------------------------------------------
# SDK 会话存储（只读）
# ---------------------------------------------------------------------------


async def read_first_items(
    session: AsyncSession,
    *,
    session_ids: list[str],
    per_session_limit: int = LIST_SCAN_MAX_ITEMS,
) -> dict[str, list[StoredItem]]:
    """批量取这些会话的开头若干条目（正序），供标题摘要使用。

    用窗口函数按会话分组取前 N 条，一次查询覆盖整页：逐会话查一次会让列表页产生
    50 次往返，而这里每个会话只需要前几条。

    排序键与 SDK 自己的读取一致（`created_at, id` 正序）。`id` 不能省：SDK 的两张表
    在 PostgreSQL 里是 `timestamp without time zone`，而 `CURRENT_TIMESTAMP` 在
    同一事务里是常量——同一批写入的多条会取得完全相同的时间戳（实测），
    因此自增主键才是真正的顺序依据。

    Returns:
        `session_id → 条目列表（正序）`；无消息行的会话不出现在结果里。
    """
    return await _read_windowed_items(
        session,
        session_ids=session_ids,
        per_session_limit=per_session_limit,
        ascending=True,
    )


async def read_last_items(
    session: AsyncSession,
    *,
    session_ids: list[str],
    per_session_limit: int = LAST_MESSAGE_SCAN_MAX_ITEMS,
) -> dict[str, list[StoredItem]]:
    """批量取这些会话的末尾若干条目（返回时按正序），供末条预览使用。

    `None` 与空列表在这一层不区分：没有消息行的会话不出现在结果字典里，
    调用方据此把预览置为 `None`。
    """
    return await _read_windowed_items(
        session,
        session_ids=session_ids,
        per_session_limit=per_session_limit,
        ascending=False,
    )


async def _read_windowed_items(
    session: AsyncSession,
    *,
    session_ids: list[str],
    per_session_limit: int,
    ascending: bool,
) -> dict[str, list[StoredItem]]:
    """按会话分组取头/尾 N 条条目（窗口函数），统一返回正序。

    方向只影响选哪些行（`rank` 的排序方向），不影响返回顺序：最终语句一律按
    `row_id` 升序取回，因此每个会话的列表天然是正序。这一条必须成立——调用方
    （预览与水合）一律按正序处理，方向转换若泄漏到调用方，同一段对话在列表与
    水合两处会给出相反的末条。

    为什么正序可以用 `row_id` 表达：`row_id` 就是 `agent_messages.id`（自增主键），
    它与 `(created_at, id)` 的先后一致（`created_at` 在同一事务内是常量，
    跨事务才增长），因此按它升序排与 SDK 的时间序相同。
    """
    if not session_ids:
        return {}

    order_keys = (
        (AgentMessage.created_at.asc(), AgentMessage.id.asc())
        if ascending
        else (AgentMessage.created_at.desc(), AgentMessage.id.desc())
    )
    ranked = (
        select(
            AgentMessage.session_id.label("session_id"),
            AgentMessage.id.label("row_id"),
            AgentMessage.message_data.label("message_data"),
            func.row_number().over(partition_by=AgentMessage.session_id, order_by=order_keys).label("rank"),
        )
        .where(AgentMessage.session_id.in_(session_ids))
        .subquery()
    )
    statement = (
        select(ranked.c.session_id, ranked.c.row_id, ranked.c.message_data)
        .where(ranked.c.rank <= per_session_limit)
        .order_by(ranked.c.session_id, ranked.c.row_id.asc())
    )

    grouped: dict[str, list[StoredItem]] = {}
    for session_id, row_id, message_data in (await session.execute(statement)).all():
        parsed = parse_item(message_data)
        if parsed is None:
            # 损坏行由 SDK 的读取路径跳过（`get_items` 捕获 JSONDecodeError）；这里同样
            # 跳过——一行坏数据不该让整个列表页失败。水合侧会记警告（`build_messages`）。
            continue
        grouped.setdefault(str(session_id), []).append(StoredItem(row_id=int(row_id), data=parsed))

    return grouped


# quality-floor: ignore docstring-promise 异常由 validate_session_id 抛出（间接 raise），本函数只做查询
async def read_all_items(session: AsyncSession, *, session_id: str) -> list[StoredItem]:
    """取某会话的全部条目（正序），供水合使用。

    不设条数上界（与列表侧的扫描上界不同）：水合要给出完整历史，截断它就是
    「显示一段不完整的对话而不说」。会话本身的规模由压缩机制约束
    （`agent/context/compaction.py`），不会无界增长。

    SDK 自己的 `get_items()` 在这条路径上不可用：它读回的是未排序保证的条目
    联合类型（基座「已知偏差」记了这一点），而水合要的是严格的正序行，且需要行标识
    作为消息 `id`（`get_items` 不返回标识）。

    Raises:
        SessionQueryError: 会话标识形状不合法。
    """
    normalized = validate_session_id(session_id)
    statement = (
        select(AgentMessage.id, AgentMessage.message_data)
        .where(AgentMessage.session_id == normalized)
        .order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc())
    )
    items: list[StoredItem] = []
    for row_id, message_data in (await session.execute(statement)).all():
        parsed = parse_item(message_data)
        if parsed is None:
            continue
        items.append(StoredItem(row_id=int(row_id), data=parsed))
    return items


async def count_session_items(session: AsyncSession, *, session_id: str) -> int:
    """统计某会话在 SDK 表里的消息条数（诊断与集成测试用）。"""
    normalized = validate_session_id(session_id)
    statement = select(func.count()).select_from(AgentMessage).where(AgentMessage.session_id == normalized)
    return int((await session.execute(statement)).scalar_one())


async def delete_session_owner(session: AsyncSession, *, session_id: str) -> int:
    """删除一条会话归属行，返回删除条数。

    三个调用场景：测试清理、运维手工清理，以及「会话刚建好就注定不存在」的补偿删除
    （应急入口的运行起步失败——那次请求的 `session_id` 没有回给调用方，留下的归属行
    永久不可达，而它的首轮注入标记已为真）。命中 0 行不报错，重复调用安全。
    """
    normalized = validate_session_id(session_id)
    result = await session.execute(delete(CampfireSession).where(CampfireSession.session_id == normalized))
    return int(getattr(result, "rowcount", 0) or 0)


async def delete_session_owners_for_account(session: AsyncSession, *, account_id: str) -> int:
    """删除该账号的全部会话归属行，返回删除条数（注销路径用）。

    `DELETE ... WHERE` 命中 0 行不报错，因此本函数天然幂等——重试注销是正常路径
    （见 `core/auth/deletion` 的幂等说明）。
    """
    normalized = validate_account_id(account_id)
    result = await session.execute(delete(CampfireSession).where(CampfireSession.account_id == normalized))
    return int(getattr(result, "rowcount", 0) or 0)


__all__ = [
    # 常量
    "LAST_MESSAGE_SCAN_MAX_ITEMS",
    "LIST_DEFAULT_LIMIT",
    "LIST_MAX_LIMIT",
    "LIST_SCAN_MAX_ITEMS",
    # 校验与归一
    "to_sdk_datetime",
    "validate_account_id",
    "validate_session_id",
    # 结果类型
    "SessionListRow",
    # 归属行
    "delete_session_owner",
    "delete_session_owners_for_account",
    "get_session_owner",
    "insert_session_owner",
    "is_session_owned_by",
    "list_session_owners",
    # SDK 只读
    "count_session_items",
    "read_all_items",
    "read_first_items",
    "read_last_items",
]
