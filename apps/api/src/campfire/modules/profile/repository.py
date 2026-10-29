"""支持对象、会话绑定与档案条目的存储层读写。

职责：本模块拥有的表的唯一 SQL 落点（状态判据只此一处）。
边界：不做授权判定（那是 `core/authz` 的调用点，在 `service`）；不做载荷整形（`service`）。
参考：docs/技术设计/technical-details/支持对象.md 第 3、4、6 节；
docs/技术设计/technical-details/个性化档案.md 第 2、3 节。
"""

from __future__ import annotations

import unicodedata
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from campfire.core.pending_write import ORIGINS, UNFINISHED_STATES, PendingWrite
from campfire.modules.profile.errors import ProfileDataError
from campfire.modules.profile.models import (
    CANDIDATE_ORIGINS,
    CONFIRMATION_CONFIRMED,
    CONFIRMATIONS,
    DOMAINS,
    FRESHNESS_CURRENT,
    FRESHNESS_HISTORICAL,
    MAX_ACCOUNT_ID_LENGTH,
    MAX_DISPLAY_NAME_LENGTH,
    MAX_SESSION_ID_LENGTH,
    STABLE_ORIGINS,
    ProfileItem,
    SessionObjectBinding,
    SupportObject,
)

#: 单次读取条目的条数上界（CORE-11：外部输入必须有界）。
#:
#: 取值理由：档案面契约第 3 节的列表端点带 `limit`，而未给数值；读取是热路径
#: （摘要与应急取数都走它），一次拉全表会让运行时延随档案增长而不可控。
#: 500 覆盖「一个对象的档案远超一页」的真实情形，同时把单次查询代价钉在上界内。
ITEMS_MAX_LIMIT = 500

#: 单次读取条目的默认条数。
ITEMS_DEFAULT_LIMIT = 200


def _utc_now() -> datetime:
    """当前 UTC 时间。集中一处，便于测试替换时只有一个改动点。"""
    return datetime.now(timezone.utc)


def normalize_display_name(raw: object) -> str:
    """校验并归一支持对象名（CORE-04：数据边界运行时解析）。

    空名在用例层显式拒绝，存储层 CHECK 亦兜底（支持对象第 8 节）：
    两层都要有——应用层给出可读错误，存储层拒绝一切旁路写入。

    不静默填默认名：猜出来的名字会让切换器出现一条使用者没起过的条目。

    Args:
        raw: 调用方给出的对象名，类型未知（运行时边界）。

    Returns:
        去掉首尾空白后的对象名。

    Raises:
        ProfileDataError: 非字符串、去空白后为空、超宽，或含控制字符。
            异常不回显原始值全文（它可能含使用者填写的姓名）。
    """
    if not isinstance(raw, str):
        raise ProfileDataError(
            "对象名必须是字符串",
            operation="normalize_display_name",
            detail=f"type={type(raw).__name__}",
        )
    stripped = raw.strip()
    if not stripped:
        raise ProfileDataError(
            "对象名不得为空或全为空白",
            operation="normalize_display_name",
            detail="去空白后长度为 0",
        )
    if len(stripped) > MAX_DISPLAY_NAME_LENGTH:
        raise ProfileDataError(
            f"对象名超过 {MAX_DISPLAY_NAME_LENGTH} 字符上界",
            operation="normalize_display_name",
            detail=f"length={len(stripped)}",
        )
    # 控制字符（含换行、制表）会破坏切换器与列表的单行呈现，且不是合法的称呼字符。
    # 判据用 Unicode 的 `Cc` 类别，而不是 `str.isprintable()`：后者会把零宽连接符
    # （组合 emoji 的组成部分）一并拒掉，而组合 emoji 是真实的称呼写法。
    # 不拦其他 Unicode：中文名与 emoji 都是真实用法。
    if any(unicodedata.category(character) == "Cc" for character in stripped):
        raise ProfileDataError(
            "对象名含控制字符",
            operation="normalize_display_name",
            detail="含控制字符（会破坏单行呈现）",
        )
    return stripped


def _validate_account_id(raw: object) -> str:
    """校验账号标识的长度与空值。

    只校验长度与空值，不校验字符集：字符集判据属于记忆侧的分区键
    （`modules/memory/identity.to_account_id` 的 Graphiti `group_id` 规则），
    而档案的账号键只是列值，不成为图名。本层保证的是「落库不会因超宽抛裸 `DBAPIError`」
    ——与 `core/pending_write` 的 `account_id` 同一条说明。
    """
    if not isinstance(raw, str):
        raise ProfileDataError(
            "账号标识必须是字符串",
            operation="validate_account_id",
            detail=f"type={type(raw).__name__}",
        )
    if not raw:
        raise ProfileDataError("账号标识为空", operation="validate_account_id", detail="空值")
    if len(raw) > MAX_ACCOUNT_ID_LENGTH:
        raise ProfileDataError(
            f"账号标识超过 {MAX_ACCOUNT_ID_LENGTH} 字符上界",
            operation="validate_account_id",
            detail=f"length={len(raw)}",
        )
    return raw


def _validate_session_id(raw: object) -> str:
    """校验会话标识的长度与空值（CORE-11：进入查询键的输入必须有界）。"""
    if not isinstance(raw, str):
        raise ProfileDataError(
            "会话标识必须是字符串",
            operation="validate_session_id",
            detail=f"type={type(raw).__name__}",
        )
    if not raw.strip():
        raise ProfileDataError("会话标识为空", operation="validate_session_id", detail="空值或全空白")
    if len(raw) > MAX_SESSION_ID_LENGTH:
        raise ProfileDataError(
            f"会话标识超过 {MAX_SESSION_ID_LENGTH} 字符上界",
            operation="validate_session_id",
            detail=f"length={len(raw)}",
        )
    return raw


def to_object_uuid(raw: object) -> uuid.UUID:
    """把外部传入的对象标识解析成 UUID（CORE-04）。

    必须显式解析：若把畸形字符串直接放进查询，PostgreSQL 会抛裸
    `DBAPIError`（`invalid input syntax for type uuid`），调用方拿到的是驱动异常
    而不是可处理的领域错误——也无法据此返回 404。

    Raises:
        ProfileDataError: 非字符串、空值，或不是合法 UUID。
            异常不回显原始值全文（它可能来自调用方的畸形输入）。
    """
    return _to_uuid(raw, operation="to_object_uuid", label="支持对象标识")


def to_item_uuid(raw: object) -> uuid.UUID:
    """把外部传入的条目标识解析成 UUID。

    Raises:
        ProfileDataError: 非字符串、空值，或不是合法 UUID。
    """
    return _to_uuid(raw, operation="to_item_uuid", label="档案条目标识")


def _to_uuid(raw: object, *, operation: str, label: str) -> uuid.UUID:
    """标识解析的共用实现（两个入口只差措辞，避免复制粘贴漂移）。

    接受两种输入：字符串（外部调用方，如 HTTP 载荷与工具参数）与
    `uuid.UUID`（内部调用方，如从数据库行里读出的标识）。后者是必需的：
    ORM 列映射成 `UUID(as_uuid=True)`，从行上取到的就是 `UUID` 对象；
    只接受字符串会让「拿行上的标识去判定归属」这条内部路径直接抛错
    ——服务层的纠正/确认/删除都要这么做。

    形状校验只在此处做一次：先从边界收窄成 `UUID`，其余各层只传 `UUID`。
    """
    if isinstance(raw, uuid.UUID):
        return raw
    if not isinstance(raw, str):
        raise ProfileDataError(
            f"{label}必须是字符串或 UUID",
            operation=operation,
            detail=f"type={type(raw).__name__}",
        )
    if not raw.strip():
        raise ProfileDataError(f"{label}为空", operation=operation, detail="空值或全空白")
    try:
        return uuid.UUID(raw.strip())
    except ValueError as exc:
        raise ProfileDataError(
            f"{label}不是合法 UUID",
            operation=operation,
            detail="无法解析为 UUID",
        ) from exc


# ---------------------------------------------------------------------------
# 支持对象
# ---------------------------------------------------------------------------


async def insert_support_object(
    session: AsyncSession,
    *,
    account_id: object,
    display_name: object,
) -> SupportObject:
    """插入一个支持对象（支持对象第 4 节的创建操作）。

    属主由调用方（用例层）从登录态传入，不接受请求体里的账号：
    忘记传就落到别人名下这类缺陷要由实现层堵掉（第 4 节创建操作的不变量）。

    Returns:
        已加入会话的记录（尚未提交）。

    Raises:
        ProfileDataError: 账号标识或对象名不合法。
    """
    record = SupportObject(
        account_id=_validate_account_id(account_id),
        display_name=normalize_display_name(display_name),
    )
    session.add(record)
    return record


async def get_support_object(session: AsyncSession, *, support_object_id: object) -> SupportObject | None:
    """按标识取支持对象；不存在返回 `None`（含已归档的——归档对象仍可读）。

    Raises:
        ProfileDataError: 标识不是合法 UUID。
    """
    parsed = to_object_uuid(support_object_id)
    return (await session.execute(select(SupportObject).where(SupportObject.id == parsed))).scalar_one_or_none()


async def list_support_objects(session: AsyncSession, *, account_id: object) -> list[SupportObject]:
    """列出某账号的全部支持对象，含已归档对象，按创建先后排序。

    为什么含已归档：档案面契约第 2.1 节要求列表含 `archived_at` 非空的行，
    前端据此在切换器里标「已归档」——归档对象仍可从档案页进入查看或恢复
    （支持对象第 4 节）。默认排序（创建先后）也是「上次选择」推导的回退路径。

    Raises:
        ProfileDataError: 账号标识不合法。
    """
    normalized = _validate_account_id(account_id)
    statement = (
        select(SupportObject)
        .where(SupportObject.account_id == normalized)
        .order_by(SupportObject.created_at, SupportObject.id)
    )
    return list((await session.execute(statement)).scalars())


async def rename_support_object(
    session: AsyncSession,
    *,
    support_object_id: object,
    display_name: object,
    now: datetime | None = None,
) -> SupportObject | None:
    """改名。不改触档案——历史条目的来源与内容不随改名变化（支持对象第 4 节）。

    条件更新带 `archived_at IS NULL`：改名一个已归档对象明确失败
    （第 8 节：改名明确失败；归档才是幂等的那个）。

    Returns:
        更新后的记录；返回 `None` 有三种可能——对象不存在、对象已归档。
        调用方须先用授权端口判定越权（本层不区分这两种情形，见 `service`）。
        之所以把「已归档」也归到 `None`，是因为它们的后续处置由授权端口统一给出
        文案，本层再分一次会把同一判定拆成两处。

    Raises:
        ProfileDataError: 标识或对象名不合法。
    """
    parsed = to_object_uuid(support_object_id)
    name = normalize_display_name(display_name)
    reference = now if now is not None else _utc_now()
    statement = (
        update(SupportObject)
        .where(
            SupportObject.id == parsed,
            SupportObject.archived_at.is_(None),
        )
        .values(display_name=name, updated_at=reference)
        .returning(SupportObject)
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def archive_support_object(
    session: AsyncSession,
    *,
    support_object_id: object,
    now: datetime | None = None,
) -> SupportObject | None:
    """归档：置 `archived_at`。幂等——重复归档不报错，只刷新 `archived_at`（第 8 节）。

    不删除任何数据：档案条目全部保留，仍可读取（第 4 节）。

    Returns:
        更新后的记录；对象不存在时为 `None`。归档已归档对象也返回记录
        ——幂等正是这个函数要提供的语义。

    Raises:
        ProfileDataError: 标识不合法。
    """
    parsed = to_object_uuid(support_object_id)
    reference = now if now is not None else _utc_now()
    statement = (
        update(SupportObject)
        .where(SupportObject.id == parsed)
        .values(archived_at=reference, updated_at=reference)
        .returning(SupportObject)
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def restore_support_object(
    session: AsyncSession,
    *,
    support_object_id: object,
    now: datetime | None = None,
) -> SupportObject | None:
    """恢复：置 `archived_at` 为空。幂等——重复恢复保持为空，不报错（第 8 节）。

    Returns:
        更新后的记录；对象不存在时为 `None`。

    Raises:
        ProfileDataError: 标识不合法。
    """
    parsed = to_object_uuid(support_object_id)
    reference = now if now is not None else _utc_now()
    statement = (
        update(SupportObject)
        .where(SupportObject.id == parsed)
        .values(archived_at=None, updated_at=reference)
        .returning(SupportObject)
    )
    return (await session.execute(statement)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# 会话与对象的绑定
# ---------------------------------------------------------------------------


async def get_session_binding(session: AsyncSession, *, session_id: object) -> SessionObjectBinding | None:
    """取某会话的绑定；无绑定时返回 `None`（无对象账号的会话是正常情形）。

    Raises:
        ProfileDataError: 会话标识不合法。
    """
    normalized = _validate_session_id(session_id)
    return (
        await session.execute(select(SessionObjectBinding).where(SessionObjectBinding.session_id == normalized))
    ).scalar_one_or_none()


async def list_session_bindings(
    session: AsyncSession,
    *,
    session_ids: Sequence[object],
) -> list[SessionObjectBinding]:
    """按会话标识批量取绑定：一次查询覆盖整页。

    与 :func:`get_session_binding` 是同一件事的批量形态。逐会话取绑定会让一页
    20 条产生 20 次查询（会话列表的对象名取数正是这种页级调用）。

    每行与逐条版取到的是同一行：`session_id` 是绑定表主键，一个会话至多一行，
    因此这里既不需要 `order_by`，也不存在「取第一条」的选取规则。

    空集合不发查询：`IN ()` 没有语义，早返回让调用方少一次往返。

    Args:
        session: 关系库会话。
        session_ids: 会话标识集合。条数上界由调用方给出（会话列表一页的上界是
            `modules/accounts/session_repository.LIST_MAX_LIMIT`），本层不再另设
            一道上界——另设会把「页有多大」这一事实复制成两处。

    Returns:
        命中的绑定行；没有绑定的会话不出现。

    Raises:
        ProfileDataError: 任一会话标识不合法（与逐条版同一判据与顺序）。
    """
    if not session_ids:
        return []
    normalized = [_validate_session_id(session_id) for session_id in session_ids]
    statement = select(SessionObjectBinding).where(SessionObjectBinding.session_id.in_(normalized))
    return list((await session.execute(statement)).scalars())


async def insert_session_binding(
    session: AsyncSession,
    *,
    session_id: object,
    account_id: object,
    support_object_id: object,
    now: datetime | None = None,
) -> SessionObjectBinding | None:
    """建立绑定；已有绑定则不动（支持对象第 6 节：绑定不可变）。

    「判定已有绑定」用主键存在性（`ON CONFLICT DO NOTHING`），不用更新：
    一个会话恰好一个对象，改绑不是本表的操作——「可切换」影响的是后续新建的会话
    （第 6 节）。条件插入把这个不变量交给存储层，并发下也不会出现第二行。

    Returns:
        `None` 表示该会话已有绑定、本次无操作（不是错误）。调用方据此区分
        「本次补建了」与「早已绑定」——首对象补绑只发生一次（第 6 节）。
        返回记录表示本次真的建立了绑定。

    Raises:
        ProfileDataError: 任一标识不合法。
    """
    normalized_session = _validate_session_id(session_id)
    normalized_account = _validate_account_id(account_id)
    parsed_object = to_object_uuid(support_object_id)
    reference = now if now is not None else _utc_now()

    statement = (
        pg_insert(SessionObjectBinding)
        .values(
            session_id=normalized_session,
            account_id=normalized_account,
            support_object_id=parsed_object,
            bound_at=reference,
        )
        .on_conflict_do_nothing(index_elements=[SessionObjectBinding.session_id])
        .returning(SessionObjectBinding)
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def delete_session_binding(session: AsyncSession, *, session_id: object) -> int:
    """删除某会话的对象绑定，返回删除条数。

    只在会话本身被丢弃时用（应急入口的运行起步失败补偿）：绑定行不随会话归属行消失，
    留着它会成为 :func:`latest_bound_object_id` 的输入——一个从未存在过的会话就此
    决定该账号下一次新建会话绑哪个对象。

    `DELETE ... WHERE` 命中 0 行不报错，因此本函数天然幂等：会话没有绑定时调用安全。

    Raises:
        ProfileDataError: 会话标识不合法。
    """
    normalized = _validate_session_id(session_id)
    result = await session.execute(delete(SessionObjectBinding).where(SessionObjectBinding.session_id == normalized))
    return int(getattr(result, "rowcount", 0) or 0)


async def latest_bound_object_id(session: AsyncSession, *, account_id: object) -> uuid.UUID | None:
    """推导该账号「上一次的选择」：取 `bound_at` 最大的那条绑定的对象（第 6 节）。

    「默认沿用上一次的选择」由本表推导，不另存字段——那会成为第二个可写的真源，
    与绑定记录冲突时无法判断谁对。

    只取在用对象（`archived_at IS NULL`）：归档对象不再被选为默认对象，
    而全部对象归档后本函数返回 `None`（而不是回退到归档对象）——这不是错误，
    由入口引导新建（第 8 节末行、第 9 节验证项）。

    Returns:
        对象标识；没有可用历史时为 `None`。

    Raises:
        ProfileDataError: 账号标识不合法。
    """
    normalized = _validate_account_id(account_id)
    statement = (
        select(SessionObjectBinding.support_object_id)
        .join(SupportObject, SupportObject.id == SessionObjectBinding.support_object_id)
        .where(
            SessionObjectBinding.account_id == normalized,
            SupportObject.archived_at.is_(None),
        )
        .order_by(SessionObjectBinding.bound_at.desc(), SessionObjectBinding.session_id)
        .limit(1)
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def earliest_active_object_id(session: AsyncSession, *, account_id: object) -> uuid.UUID | None:
    """推导回退路径：该账号创建最早的在用对象（第 6 节）。

    没有绑定历史时用它（内存中的「上次选择」推导的第二段）。

    Returns:
        对象标识；没有在用对象时为 `None`（不是错误）。

    Raises:
        ProfileDataError: 账号标识不合法。
    """
    normalized = _validate_account_id(account_id)
    statement = (
        select(SupportObject.id)
        .where(
            SupportObject.account_id == normalized,
            SupportObject.archived_at.is_(None),
        )
        .order_by(SupportObject.created_at, SupportObject.id)
        .limit(1)
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def count_active_objects(session: AsyncSession, *, account_id: object) -> int:
    """统计该账号在用对象数。

    用途：判定「账号是否一个在用对象都没有」——首对象补绑与默认对象推导都要问这个
    问题（第 6 节）。用 `count` 而不是取回全部行：只问存在性时不该构造对象。

    Raises:
        ProfileDataError: 账号标识不合法。
    """
    normalized = _validate_account_id(account_id)
    statement = (
        select(func.count())
        .select_from(SupportObject)
        .where(
            SupportObject.account_id == normalized,
            SupportObject.archived_at.is_(None),
        )
    )
    return (await session.execute(statement)).scalar_one()


# ---------------------------------------------------------------------------
# 档案条目
# ---------------------------------------------------------------------------


async def insert_item(
    session: AsyncSession,
    *,
    support_object_id: object,
    domain: str,
    topic: object,
    description: object,
    origin: str,
    confirmation: str,
    source: dict,
    contexts: list | None = None,
    manifestations: list | None = None,
    helpful_support: list | None = None,
    unhelpful_support: list | None = None,
    person_report: str | None = None,
    probable_need: str | None = None,
    pending_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> ProfileItem:
    """插入一条档案条目。

    落层判据不在本层：`confirmation` 由调用方（用例层）经 `confirmation_on_entry`
    按 `origin` 算出，而「推断不得写成已确认」在用例层硬卡（第 7 节）。
    本层只落库，并在存储层由 CHECK 兜住词表的闭集。

    Returns:
        已加入会话的记录（尚未提交）。

    Raises:
        ProfileDataError: 领域不在词表内、`origin`/`confirmation` 不在词表内，
            或描述/主题为空。
    """
    if domain not in DOMAINS:
        raise ProfileDataError(
            f"领域不在词表内：{domain!r}",
            operation="insert_item",
            detail=f"合法取值={sorted(DOMAINS)}",
        )
    if origin not in ORIGINS:
        raise ProfileDataError(
            f"生成方式不在词表内：{origin!r}",
            operation="insert_item",
            detail=f"合法取值={sorted(ORIGINS)}",
        )
    if confirmation not in CONFIRMATIONS:
        raise ProfileDataError(
            f"确认状态不在词表内：{confirmation!r}",
            operation="insert_item",
            detail=f"合法取值={sorted(CONFIRMATIONS)}",
        )
    text_topic = _require_text(topic, field="topic", operation="insert_item")
    text_description = _require_text(description, field="description", operation="insert_item")
    reference = now if now is not None else _utc_now()

    record = ProfileItem(
        support_object_id=to_object_uuid(support_object_id),
        domain=domain,
        topic=text_topic,
        description=text_description,
        contexts=list(contexts or []),
        manifestations=list(manifestations or []),
        helpful_support=list(helpful_support or []),
        unhelpful_support=list(unhelpful_support or []),
        person_report=person_report,
        probable_need=probable_need,
        origin=origin,
        source=dict(source or {}),
        confirmation=confirmation,
        freshness=FRESHNESS_CURRENT,
        first_recorded_at=reference,
        last_confirmed_at=reference,
        pending_id=pending_id,
    )
    session.add(record)
    return record


def _require_text(raw: object, *, field: str, operation: str) -> str:
    """校验「非空文本」字段（主题与描述共用，避免两处各写一遍判据）。

    Raises:
        ProfileDataError: 非字符串或去空白后为空。
    """
    if not isinstance(raw, str):
        raise ProfileDataError(
            f"{field} 必须是字符串",
            operation=operation,
            detail=f"type={type(raw).__name__}",
        )
    stripped = raw.strip()
    if not stripped:
        raise ProfileDataError(
            f"{field} 不得为空或全为空白",
            operation=operation,
            detail="去空白后长度为 0",
        )
    return stripped


async def get_item(session: AsyncSession, *, item_id: object) -> ProfileItem | None:
    """按标识取条目；不存在返回 `None`。

    Raises:
        ProfileDataError: 标识不是合法 UUID。
    """
    parsed = to_item_uuid(item_id)
    return (await session.execute(select(ProfileItem).where(ProfileItem.item_id == parsed))).scalar_one_or_none()


async def list_items(
    session: AsyncSession,
    *,
    support_object_id: object,
    include_candidates: bool = False,
    include_superseded: bool = False,
    domains: list[str] | None = None,
    limit: int = ITEMS_DEFAULT_LIMIT,
) -> list[ProfileItem]:
    """列出某对象的条目，候选层单独成组由调用方按 `confirmation` 分流。

    四条取数约束（档案面契约第 3 节、`read_profile_items` 契约第 4 节）：

    1. `confirmation = rejected` 的条目一律不返回：使用者否定过的内容不得再作为
       上下文进入对话。这条没有开关——它连 `include_superseded` 也不放开，
       因为它管的是「否定过的内容不得回看」，与「已取代的旧条目可回看」是两件事；
    2. `superseded_by` 非空的条目不返回，`include_superseded` 为真时返回；
    3. `freshness = historical` 的条目不返回，`include_superseded` 为真时返回；
    4. 第 2、3 条是同一件事的两侧：纠正一次同时置这两个字段并互指，因此开关
       必须同时管住两道——只放一道仍取不到任何历史条目。

    第 2、3 条的开关只服务给人看的读路径（档案页的行首「已更正」标）：历史条目
    「此后不参与注入」，模型侧不接这个参数，`include_superseded` 缺省即模型侧行为。

    候选条目是否返回由 `include_candidates` 决定；返回时自带候选标记
    （`confirmation = unconfirmed`），调用方与模型都不得把它当作事实。
    它与 `include_superseded` 是两条独立的轴（候选层 / 时效），不互斥：
    「已被取代的候选」是可达状态（纠正一条未确认的候选），两个开关都真时返回它。

    Args:
        session: 关系库会话。
        support_object_id: 归属对象（调用方须先经 `require_owned` 判定）。
        include_candidates: 为真时一并返回未确认条目。
        include_superseded: 为真时一并返回已被取代的历史条目。
        domains: 可选的领域过滤；未知领域名显式拒绝而不是静默返回空列表
            ——后者会让打错字的过滤看起来像「这个领域没有条目」。
        limit: 条数上界，收敛到 `ITEMS_MAX_LIMIT`。

    Returns:
        匹配的条目（按首次记录时间倒序，稳定）。

    Raises:
        ProfileDataError: 标识不合法，或 `domains` 含词表外的取值。
    """
    conditions = _visible_item_conditions(
        parsed_object=to_object_uuid(support_object_id),
        include_candidates=include_candidates,
        include_superseded=include_superseded,
        domains=domains,
    )
    return await _select_items(session, conditions=conditions, limit=limit)


async def list_candidate_items(
    session: AsyncSession,
    *,
    support_object_id: object,
    include_superseded: bool = False,
    domains: list[str] | None = None,
    limit: int = ITEMS_DEFAULT_LIMIT,
) -> list[ProfileItem]:
    """只取候选层条目：与 `list_items` 的稳定层流各受各自上限约束，互不挤占。

    两条流不可合并成一条带窗口的查询——较新的候选会占满窗口、把稳定条目挤出
    `items`（回归 `test_items_pagination_is_not_starved_by_candidates`）。
    """
    conditions = _visible_item_conditions(
        parsed_object=to_object_uuid(support_object_id),
        include_candidates=True,
        include_superseded=include_superseded,
        domains=domains,
    )
    # 稳定层判据的补集（`ORIGINS` 只有六个取值、四个是稳定来源）。
    conditions.append(
        and_(
            ProfileItem.origin.notin_(sorted(STABLE_ORIGINS)),
            ProfileItem.confirmation != CONFIRMATION_CONFIRMED,
        )
    )
    return await _select_items(session, conditions=conditions, limit=limit)


def _visible_item_conditions(
    *,
    parsed_object: uuid.UUID,
    include_candidates: bool,
    include_superseded: bool,
    domains: list[str] | None,
) -> list[ColumnElement[bool]]:
    """条目可见性条件（`list_items` 与 `list_candidate_items` 共用）。"""
    if domains is not None:
        unknown = sorted({value for value in domains if value not in DOMAINS})
        if unknown:
            raise ProfileDataError(
                f"领域过滤含词表外的取值：{' '.join(unknown)}",
                operation="list_items",
                detail=f"合法取值={sorted(DOMAINS)}",
            )
    conditions: list[ColumnElement[bool]] = [
        ProfileItem.support_object_id == parsed_object,
        # 被否定的条目一律不返回（第 2 节的 rejected 语义）；这一条没有开关。
        ProfileItem.confirmation != "rejected",
    ]
    if not include_superseded:
        # 已取代 / 历史的条目不返回（第 3 节不变量 3）；两道成对。
        conditions.append(ProfileItem.superseded_by.is_(None))
        conditions.append(ProfileItem.freshness != FRESHNESS_HISTORICAL)
    if not include_candidates:
        conditions.append(_stable_layer_clause())
    if domains is not None:
        conditions.append(ProfileItem.domain.in_(sorted(domains)))
    return conditions


async def _select_items(
    session: AsyncSession, *, conditions: list[ColumnElement[bool]], limit: int
) -> list[ProfileItem]:
    """按给定条件取条目（首次记录时间倒序，条数收敛到 `ITEMS_MAX_LIMIT`）。"""
    effective_limit = max(1, min(limit, ITEMS_MAX_LIMIT))
    statement = (
        select(ProfileItem).where(*conditions).order_by(ProfileItem.first_recorded_at.desc(), ProfileItem.item_id)
    )
    statement = statement.limit(effective_limit)
    return list((await session.execute(statement)).scalars())


def _stable_layer_clause():  # noqa: ANN202 —— 返回 SQLAlchemy 布尔表达式
    """稳定层的 SQL 判据，与 `models.lands_in_stable_layer` 同一条规则。

    两处必须表达同一件事：纯函数供用例层与测试直接断言，本表达式供 SQL 过滤。
    把它写成一处并让两边都引用它是不可能的（一侧是 Python 谓词、一侧是 SQL 表达式），
    因此这里以测试钉住两者一致（见 `test_profile_items_integration`）。
    """
    return or_(
        ProfileItem.origin.in_(sorted(STABLE_ORIGINS)),
        ProfileItem.confirmation == CONFIRMATION_CONFIRMED,
    )


async def read_stable_items_by_domains(
    session: AsyncSession,
    *,
    support_object_id: object,
    domains: tuple[str, ...] | None = None,
    topics: tuple[str, ...] | None = None,
) -> list[ProfileItem]:
    """读取稳定层条目，供摘要与应急预取取数（只取稳定层，第 4 节）。

    与 :func:`list_items` 的分工：这个只服务「系统维护的取数」，
    固定只取稳定层、不分页（一个对象的稳定层规模受档案本身约束，
    而摘要与应急预取都是等待时延的路径）。

    Args:
        session: 关系库会话。
        support_object_id: 归属对象（调用方须先经 `require_owned` 判定）。
        domains: 可选的领域过滤（第 4、8 节的领域映射）。`None` 表示不限。
        topics: 可选的 `topic` 精确过滤（`communication` 组的三个具名取值用它）。

    Returns:
        稳定层条目，按最近确认时间倒序。

    Raises:
        ProfileDataError: 标识不合法。
    """
    parsed = to_object_uuid(support_object_id)
    conditions = [
        ProfileItem.support_object_id == parsed,
        ProfileItem.freshness == FRESHNESS_CURRENT,
        ProfileItem.superseded_by.is_(None),
        ProfileItem.confirmation != "rejected",
        _stable_layer_clause(),
    ]
    if domains is not None:
        conditions.append(ProfileItem.domain.in_(domains))
    if topics is not None:
        conditions.append(ProfileItem.topic.in_(topics))
    statement = (
        select(ProfileItem).where(*conditions).order_by(ProfileItem.last_confirmed_at.desc(), ProfileItem.item_id)
    )
    return list((await session.execute(statement)).scalars())


async def read_candidate_items(
    session: AsyncSession,
    *,
    support_object_id: object,
) -> list[ProfileItem]:
    """读取候选层条目（未经确认的非推断来源不在此，见落层判据）。

    候选层的定义是「不进稳定层」：`system_observation` 与 `ai_inference` 且未确认。
    `third_party_report` 与 `document` 虽 `unconfirmed` 但属稳定层，不在此列
    ——摘要取数要它们，候选确认界面不要它们。

    Raises:
        ProfileDataError: 标识不合法。
    """
    parsed = to_object_uuid(support_object_id)
    statement = (
        select(ProfileItem)
        .where(
            ProfileItem.support_object_id == parsed,
            ProfileItem.freshness == FRESHNESS_CURRENT,
            ProfileItem.superseded_by.is_(None),
            ProfileItem.confirmation == "unconfirmed",
            ProfileItem.origin.in_(sorted(CANDIDATE_ORIGINS)),
        )
        .order_by(ProfileItem.first_recorded_at.desc(), ProfileItem.item_id)
    )
    return list((await session.execute(statement)).scalars())


async def confirm_item(
    session: AsyncSession,
    *,
    item_id: object,
    now: datetime | None = None,
) -> ProfileItem | None:
    """确认一条候选条目：置 `confirmed` 并刷新 `last_confirmed_at`。

    为什么只接受 `unconfirmed`：契约第 4 节要求「确认只能作用于候选条目；
    对已确认或已否定的条目返回 422」。把该判据放进 `WHERE` 而不是先查后改，
    并发下也不会把一条已被否定的条目改回确认态。

    为什么还要求未被取代：设计给历史条目的话是「可回看」（第 5 节第 5 条），
    回看即只读；`RQ-MEM-03` 给使用者的条目能力是「查 / 纠 / 删」，
    没有「确认一条已被取代的条目」。而被取代的条目仍可能停在 `unconfirmed`
    ——推断被取代时不会顺带确认它——确认它会按归组判据把这条历史行
    从 `candidates` 移进 `items`，成一次设计未认可的状态转移。
    判据与 `mark_superseded` 同法放进 `WHERE`，不留先查后改的竞态窗口。

    刷新 `last_confirmed_at` 是必须的：它既是「最近确认时间」的展示值，
    也是降权 90 天的计时起点（第 3 节）。

    Returns:
        更新后的记录；`None` 表示条目不存在、当前不是 `unconfirmed`，或已被取代
        （对调用方都是「不能确认」，由用例层转成统一的失败语义）。

    Raises:
        ProfileDataError: 标识不合法。
    """
    parsed = to_item_uuid(item_id)
    reference = now if now is not None else _utc_now()
    statement = (
        update(ProfileItem)
        .where(
            ProfileItem.item_id == parsed,
            ProfileItem.confirmation == "unconfirmed",
            ProfileItem.superseded_by.is_(None),
        )
        .values(confirmation="confirmed", last_confirmed_at=reference)
        .returning(ProfileItem)
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def reject_item(session: AsyncSession, *, item_id: object) -> ProfileItem | None:
    """否定一条候选：置 `rejected`。不物理删除（第 2 节）。

    「使用者否定过这件事」本身是可追溯事实，因此不删行；此后它不进摘要、
    不参与注入、不得再次作为候选提出——后两条由读路径的过滤承载。

    未被取代也是必要条件（与 `confirm_item` 同判据）：历史条目只可回看
    （第 5 节第 5 条），而 `RQ-MEM-03` 没有「否定一条已被取代的条目」这条能力。
    已取代的行仍可能停在 `unconfirmed`，否定它会置 `rejected`，
    而读路径把 `rejected` 一律排除——这条历史行于是从所有读路径消失，
    连「可回看」也不再成立。判据放进 `WHERE`，不留先查后改的竞态窗口。

    Returns:
        更新后的记录；`None` 表示条目不存在、当前不是 `unconfirmed`，或已被取代。

    Raises:
        ProfileDataError: 标识不合法。
    """
    parsed = to_item_uuid(item_id)
    statement = (
        update(ProfileItem)
        .where(
            ProfileItem.item_id == parsed,
            ProfileItem.confirmation == "unconfirmed",
            ProfileItem.superseded_by.is_(None),
        )
        .values(confirmation="rejected")
        .returning(ProfileItem)
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def mark_superseded(
    session: AsyncSession,
    *,
    old_item_id: object,
    new_item_id: object,
) -> ProfileItem | None:
    """把旧条目转 `historical` 并与新条目互指（第 3 节不变量 3）。

    纠正以「新增条目 + 旧条目转 `historical` 并互指」表达，不物理覆盖、
    也不静默改写。两个指针都要写：档案面契约第 4 节的响应带 `supersedes`，
    而取数只认 `superseded_by`——缺任一侧都会让「谁取代了谁」只答一半。

    状态判据放进 `WHERE` 而不是先查后改（与 `confirm_item` 同法）：对已被取代的
    条目再来一次纠正会覆写 `superseded_by`，让先前的取代者成为悬挂指针，
    而「谁取代了谁」只答一半正是不可变量 3 禁止的静默改写。放进 `WHERE` 后，
    并发下的两个纠正请求也只有一个能拿到行。

    Returns:
        更新后的旧条目；`None` 表示旧条目不存在、已被取代，或不在 `current` 态
        （由用例层转成明确的失败，而不是静默改写既有的取代关系）。

    Raises:
        ProfileDataError: 任一标识不合法。
    """
    parsed_old = to_item_uuid(old_item_id)
    parsed_new = to_item_uuid(new_item_id)
    statement = (
        update(ProfileItem)
        .where(
            ProfileItem.item_id == parsed_old,
            # 状态判据放进 WHERE（与 `confirm_item` 同法）：只有尚未被取代的
            # `current` 条目能被再次取代，否则这次纠正会覆写既有的
            # `superseded_by`，先前的取代者随之成为悬挂指针——「谁取代了谁」
            # 只答一半正是第 3 节不变量 3 禁止的静默改写。
            ProfileItem.freshness == FRESHNESS_CURRENT,
            ProfileItem.superseded_by.is_(None),
        )
        .values(
            freshness=FRESHNESS_HISTORICAL,
            superseded_by=parsed_new,
        )
        .returning(ProfileItem)
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def set_item_supersedes(
    session: AsyncSession,
    *,
    item_id: object,
    supersedes: object,
) -> ProfileItem | None:
    """补写新条目的 `supersedes` 反向指针（互指的另一半）。

    Returns:
        更新后的记录；`None` 表示条目不存在。

    Raises:
        ProfileDataError: 任一标识不合法。
    """
    parsed = to_item_uuid(item_id)
    parsed_old = to_item_uuid(supersedes)
    statement = (
        update(ProfileItem).where(ProfileItem.item_id == parsed).values(supersedes=parsed_old).returning(ProfileItem)
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def delete_item(session: AsyncSession, *, item_id: object) -> bool:
    """物理删除一条条目（纠正的对照：删除不留取代条目）。

    为什么删除是物理的、而 `rejected` 不是：`rejected` 表达「使用者否定过这件事」，
    那本身是可追溯事实，故留行；而删除表达「这条内容不该存在」，
    且 `AC-08` 要求删除后该内容不再被取数——留行会让「删除须覆盖检索与衍生中的使用」
    多出一层过滤依赖，而物理删除在存储层就闭合了。

    Returns:
        True 表示删掉了一行；False 表示该条目不存在（删除幂等：
        重复删除不算错误，由用例层据此返回 `already`）。

    Raises:
        ProfileDataError: 标识不合法。
    """
    parsed = to_item_uuid(item_id)
    result = await session.execute(delete(ProfileItem).where(ProfileItem.item_id == parsed))
    return bool(getattr(result, "rowcount", 0) or 0)


async def find_item_by_pending_id(session: AsyncSession, *, pending_id: uuid.UUID) -> ProfileItem | None:
    """按待处理记录标识找条目——幂等键的查询入口（写入路径第 5 节）。

    重复消费时先查它：命中即说明该 `pending_id` 已经写成条目，不得再写第二条。

    Returns:
        已存在的条目；没有则 `None`。
    """
    return (await session.execute(select(ProfileItem).where(ProfileItem.pending_id == pending_id))).scalar_one_or_none()


async def has_unfinished_pending_writes(session: AsyncSession, *, support_object_id: object) -> bool:
    """该对象是否还有未完成的待处理写入（`read_profile_summary` 契约第 4 节）。

    摘要的 `possibly_stale` 由它决定：写入是异步的，只要还有记录没走到 `done`，
    摘要就可能未含最新内容，必须如实标注而不是假装摘要已是最新。

    只取存在性（`SELECT 1 ... LIMIT 1`）：这是摘要取数路径上的一次附加查询，
    少构造一行对象就少一份开销。

    Raises:
        ProfileDataError: 标识不合法。
    """
    parsed = to_object_uuid(support_object_id)
    found = (
        await session.execute(
            select(1)
            .select_from(PendingWrite)
            .where(
                PendingWrite.support_object_id == str(parsed),
                PendingWrite.state.in_(sorted(UNFINISHED_STATES)),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return found is not None


# ---------------------------------------------------------------------------
# 注销清除（实现 core/auth 的 purger 端口）
# ---------------------------------------------------------------------------


async def delete_items_for_account(session: AsyncSession, *, account_id: object) -> int:
    """删除某账号全部支持对象下的全部档案条目，返回条数。

    只删自己账号对象下的条目：条目表没有 `account_id` 列（归属经对象表达），
    因此用子查询按对象归属圈定范围，而不是按条目自身的任何列。

    必须先于 :func:`delete_support_objects_for_account`：条目对对象声明了外键，
    顺序反了会被外键拒绝（支持对象第 7 节的顺序约束）。

    Raises:
        ProfileDataError: 账号标识不合法。
    """
    normalized = _validate_account_id(account_id)
    owned = select(SupportObject.id).where(SupportObject.account_id == normalized)
    result = await session.execute(delete(ProfileItem).where(ProfileItem.support_object_id.in_(owned)))
    return int(getattr(result, "rowcount", 0) or 0)


async def delete_session_bindings_for_account(session: AsyncSession, *, account_id: object) -> int:
    """删除某账号的全部会话-对象绑定行，返回条数。

    绑定不构成对外内容，但属该账号的数据（支持对象第 7 节：真删）。

    Raises:
        ProfileDataError: 账号标识不合法。
    """
    normalized = _validate_account_id(account_id)
    result = await session.execute(delete(SessionObjectBinding).where(SessionObjectBinding.account_id == normalized))
    return int(getattr(result, "rowcount", 0) or 0)


async def delete_support_objects_for_account(session: AsyncSession, *, account_id: object) -> int:
    """删除某账号的全部支持对象（含已归档的），返回条数。

    归档是生命周期状态，不是注销的豁免（支持对象第 7 节、`AC-24`）。

    Raises:
        ProfileDataError: 账号标识不合法。
    """
    normalized = _validate_account_id(account_id)
    result = await session.execute(delete(SupportObject).where(SupportObject.account_id == normalized))
    return int(getattr(result, "rowcount", 0) or 0)


async def delete_item_scoped(
    session: AsyncSession,
    *,
    item_id: object,
    account_id: object,
) -> ProfileItem | None:
    """删除一条条目，范围由属主圈定，返回被删的行；不属于该账号则返回 `None`。

    为什么用一条带归属判定的 `DELETE ... RETURNING` 而不是「先查再判再删」：
    后者多一次往返，且存在真实窗口（查到之后、删除之前对象换主不会发生，
    但先查后删这条路径本身把归属判定与删除拆成两处，容易在改动中漏掉一侧）。
    单条 SQL 让「只删自己的」成为存储层的事实。

    不删已归档对象下的条目：归档对象仍可纠正与删除条目（支持对象第 4 节：
    归档对象可读，`RQ-MEM-03` 不因归档失效），因此这里只按属主圈定，不看归档状态。

    Returns:
        被删的条目（供调用方回报 `already: false`）；`None` 表示没有删到任何行
        ——不存在、不属于该账号，或已被删除。三种情形合并是有意的：
        区分它们等于提供条目枚举通道。调用方据 `None` 报「不可访问」（404），
        不把它回报成成功（2026-09-30 编排器裁决 1）。

    Raises:
        ProfileDataError: 标识不合法。
    """
    parsed_item = to_item_uuid(item_id)
    normalized = _validate_account_id(account_id)
    owned = select(SupportObject.id).where(SupportObject.account_id == normalized)
    statement = (
        delete(ProfileItem)
        .where(
            ProfileItem.item_id == parsed_item,
            ProfileItem.support_object_id.in_(owned),
        )
        .returning(ProfileItem)
    )
    return (await session.execute(statement)).scalar_one_or_none()


__all__ = [
    "ITEMS_DEFAULT_LIMIT",
    "ITEMS_MAX_LIMIT",
    "archive_support_object",
    "confirm_item",
    "count_active_objects",
    "delete_item",
    "delete_item_scoped",
    "delete_items_for_account",
    "delete_session_bindings_for_account",
    "delete_support_objects_for_account",
    "earliest_active_object_id",
    "find_item_by_pending_id",
    "get_item",
    "get_session_binding",
    "get_support_object",
    "has_unfinished_pending_writes",
    "insert_item",
    "insert_session_binding",
    "insert_support_object",
    "latest_bound_object_id",
    "list_candidate_items",
    "list_items",
    "list_session_bindings",
    "list_support_objects",
    "mark_superseded",
    "normalize_display_name",
    "read_candidate_items",
    "read_stable_items_by_domains",
    "reject_item",
    "rename_support_object",
    "restore_support_object",
    "set_item_supersedes",
    "to_item_uuid",
    "to_object_uuid",
]
