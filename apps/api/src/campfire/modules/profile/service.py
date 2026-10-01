"""个性化档案的用例层：对象生命周期、条目读写、纠正、确认、删除、摘要与应急取数。

职责：编排存储读写与授权判定，并硬卡落层判据（个性化档案第 7 节）。
边界：不实现授权判定（调 `core/authz`）；不直连 HTTP 形状（那是档案面的装配）。
参考：docs/技术设计/technical-details/支持对象.md 第 3～6 节；
docs/技术设计/technical-details/个性化档案.md 第 2～8 节；
docs/技术设计/面/profile/档案面HTTP契约.md。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from campfire.core.authz import (
    OBJECT_ARCHIVED_MESSAGE,
    OBJECT_NOT_ACCESSIBLE_MESSAGE,
    AuthorizationError,
    ObjectArchivedError,
    require_owned,
    require_writable,
)
from campfire.modules.profile import repository as repo
from campfire.modules.profile.errors import (
    InferredCannotBeConfirmedError,
    ProfileDataError,
    ProfileItemNotFoundError,
)
from campfire.modules.profile.models import (
    CANDIDATE_ORIGINS,
    CONFIRMATION_CONFIRMED,
    DOMAINS,
    EMERGENCY_COMMUNICATION_DOMAIN,
    EMERGENCY_COMMUNICATION_FIELDS,
    EMERGENCY_GROUP_COMMUNICATION,
    EMERGENCY_GROUP_DOMAINS,
    EMERGENCY_GROUPS,
    EMERGENCY_STRATEGY_DOMAIN,
    EMERGENCY_STRATEGY_FIELDS,
    FRESHNESS_CURRENT,
    FRESHNESS_HISTORICAL,
    MANUAL_ENTRY_SOURCE,
    ProfileItem,
    SessionObjectBinding,
    SupportObject,
    confirmation_on_entry,
    effective_freshness,
    lands_in_stable_layer,
)

# ============================================================================
# 一页摘要（个性化档案第 4 节）
# ============================================================================

#: 摘要的十二个字段：`key` → (展示标签, 取数领域)。
#:
#: 第 4 节定义的是「摘要字段 → 取数领域」的映射，标签是展示层的事，
#: 但它是契约的一部分（前端按 key 定位字段），因此与映射一起放在这里，
#: 不散落到面层。顺序照第 4 节的书写顺序。
SUMMARY_FIELD_DOMAINS: dict[str, tuple[str, tuple[str, ...]]] = {
    "about_me": ("我是什么样的人", ("about_self",)),
    "how_i_communicate": ("我怎么沟通", ("communication",)),
    "what_is_important_to_me": ("什么对我重要", ("about_self",)),
    "my_strengths": ("我的优势", ("about_self",)),
    "my_sensory_needs": ("我的感觉需求", ("sensory_processing",)),
    "things_that_may_distress_me": ("可能让我不适的事", ("triggers_and_support",)),
    "how_you_can_help": ("你可以怎样帮我", ("triggers_and_support",)),
    "please_do": ("请这样做", ("triggers_and_support",)),
    "please_dont": ("请不要这样做", ("triggers_and_support",)),
    "how_i_show_pain_or_distress": ("我怎样表达疼痛或不适", ("sensory_processing",)),
    "important_people": ("重要的人", ("about_self",)),
    "critical_health_safety_information": ("关键健康与安全信息", ("physical_medical", "risk_and_crisis")),
}


@dataclass(frozen=True, slots=True)
class SummaryEntry:
    """摘要里的一条：条目本身 + 它的来源与时间（第 4 节：每条可追溯到具体条目）。"""

    item_id: str
    origin: str
    last_confirmed_at: datetime
    description: str
    #: 该条目的当下新鲜度。本结构只由摘要与应急取数填充，而这条路只取稳定层，
    #: `stale` 又只降权非稳定层的未确认条目（第 3 节）——两者交集为空，
    #: 因此这里恒为 `current`。被降权条目的陈旧标注在条目读取路径上
    #: （`ItemView.freshness`，须显式检索候选）。
    freshness: str


@dataclass(frozen=True, slots=True)
class SummaryField:
    """摘要的一个字段。"""

    key: str
    label: str
    items: list[SummaryEntry]


@dataclass(frozen=True, slots=True)
class ProfileSummary:
    """一页摘要（第 4 节）。

    `has_profile` 是显式的：目录档时返回「无档案」而不是空对象
    （第 10 节验证项）。只有候选条目的对象同样得到 `has_profile = False`
    ——候选层不得进摘要，因此它在摘要意义上就是「无档案」。
    """

    support_object_id: str
    #: 是否有可用的稳定层内容。False 时调用方须在输出里标注「本次未使用个性化档案」
    #: （`AC-02`），而不是把它当成「这个人没有任何特征」。
    has_profile: bool
    fields: list[SummaryField] = field(default_factory=list)
    #: 参与摘要的条目数（`read_profile_summary` 契约第 3 节的 `item_count`）。
    item_count: int = 0
    generated_at: datetime | None = None
    #: 摘要可能未含最新写入（写入是异步的）。有未完成的待处理记录时为真
    #: （`read_profile_summary` 契约第 4 节）。
    possibly_stale: bool = False


@dataclass(frozen=True, slots=True)
class EmergencyContext:
    """应急预取（第 8 节的八组）。

    某组未预存时显式返回 absent，不为 `null` 让调用方去猜
    （第 8 节原文与技能设计：缺失即标注，不得由模型补全）。
    因此键总是存在，值是一个显式状态而不是可能为空的列表。

    `communication` 组是具名结构而不是条目列表（第 8 节的
    `communication{baseline, best_mode, processing_time_seconds}`），
    因此它单独占一个字段；缺哪个键就不出现哪个键（absent 与「值为空」可区分）。
    """

    support_object_id: str
    #: 是否有档案对象。False 表示「无档案」——整份上下文不可用，
    #: 调用方须按 `AC-02` 标注「本次未使用个性化档案」。
    has_profile: bool
    #: 框架七组：键 → 该组的条目列表。组未预存时值为 `None`（显式 absent）。
    groups: dict[str, list[SummaryEntry] | None] = field(default_factory=dict)
    #: `communication` 组：键 → 该键的条目。未预存的键不出现在字典里。
    communication: dict[str, SummaryEntry] = field(default_factory=dict)


# ============================================================================
# 支持对象：生命周期用例
# ============================================================================


async def create_object(session: AsyncSession, *, account_id: object, display_name: object) -> SupportObject:
    """创建一个支持对象（支持对象第 4 节）。

    属主取登录态、不接受调用方传入（第 4 节创建操作的不变量）：
    忘记传就落到别人名下这类缺陷要由实现层堵掉。本函数因此只收
    `account_id`（由调用方从会话取）与 `display_name`。

    Args:
        session: 关系库会话（调用方负责提交）。
        account_id: 属主账号（来自登录态）。
        display_name: 对象名；空名与全空白名在此被拒（存储层 CHECK 亦兜底）。

    Returns:
        已加入会话的记录（尚未提交）。

    Raises:
        ProfileDataError: 账号标识或对象名不合法。
    """
    return await repo.insert_support_object(session, account_id=account_id, display_name=display_name)


async def list_objects(session: AsyncSession, *, account_id: object) -> list[SupportObject]:
    """列出某账号的支持对象，含已归档对象（档案面契约第 2.1 节）。

    只列出该账号自己的对象：账号来自登录态，因此不存在「列出别人的」这条路径。

    Raises:
        ProfileDataError: 账号标识不合法。
    """
    return await repo.list_support_objects(session, account_id=account_id)


async def rename_object(
    session: AsyncSession,
    *,
    account_id: object,
    support_object_id: object,
    display_name: object,
    now: datetime | None = None,
) -> SupportObject:
    """改名。不改触档案——历史条目的来源与内容不随改名变化（第 4 节）。

    改名一个已归档对象明确失败（第 8 节）。

    Raises:
        AuthorizationError: 对象不存在或不属于该账号（文案与「不存在」相同）。
        ObjectArchivedError: 对象已归档——改名明确失败，而归档才是幂等的那个。
        ProfileDataError: 对象名不合法。
    """
    await require_owned(account_id, support_object_id)
    updated = await repo.rename_support_object(
        session, support_object_id=support_object_id, display_name=display_name, now=now
    )
    if updated is None:
        # 授权刚通过，因此这里只可能是「已归档」——`rename_support_object` 的 WHERE
        # 带 `archived_at IS NULL`。把它转成归档错误而不是「不存在」：属主自己的对象，
        # 使用者需要知道原因（第 5.3 节）。
        raise ObjectArchivedError(OBJECT_ARCHIVED_MESSAGE)
    return updated


async def archive_object(
    session: AsyncSession,
    *,
    account_id: object,
    support_object_id: object,
    now: datetime | None = None,
) -> SupportObject:
    """归档：置 `archived_at`。不删除任何数据，档案条目全部保留（第 4 节）。

    幂等：重复归档不报错，只刷新 `archived_at`（第 8 节）。

    Raises:
        AuthorizationError: 对象不存在或不属于该账号。
    """
    await require_owned(account_id, support_object_id)
    record = await repo.archive_support_object(session, support_object_id=support_object_id, now=now)
    if record is None:
        # `require_owned` 刚通过，行不可能消失（同一会话内）；除非并发注销删了它。
        # 显式抛权限错误而不是返回 None：调用方拿到的是一个明确失败。
        raise AuthorizationError(OBJECT_NOT_ACCESSIBLE_MESSAGE)
    return record


async def restore_object(
    session: AsyncSession,
    *,
    account_id: object,
    support_object_id: object,
    now: datetime | None = None,
) -> SupportObject:
    """恢复：置 `archived_at` 为空。幂等：重复恢复保持为空（第 8 节）。

    Raises:
        AuthorizationError: 对象不存在或不属于该账号。
    """
    await require_owned(account_id, support_object_id)
    record = await repo.restore_support_object(session, support_object_id=support_object_id, now=now)
    if record is None:
        raise AuthorizationError(OBJECT_NOT_ACCESSIBLE_MESSAGE)
    return record


async def resolve_default_object(session: AsyncSession, *, account_id: object) -> str | None:
    """推导该账号的默认支持对象（第 6 节）。

    判据两段：先取绑定历史里 `bound_at` 最大的那条的在用对象；
    没有历史时回退到创建最早的在用对象。

    一期不设对象数量上限，也不新增「账号当前对象」字段——那会成为第二个可写的真源，
    与绑定记录冲突时无法判断谁对（第 6 节）。

    Returns:
        对象标识；该账号一个在用对象都没有时返回 `None`。
        不是错误：由入口引导新建（第 8 节末行、`AC-02`）。

    Raises:
        ProfileDataError: 账号标识不合法。
    """
    bound = await repo.latest_bound_object_id(session, account_id=account_id)
    if bound is not None:
        return str(bound)
    earliest = await repo.earliest_active_object_id(session, account_id=account_id)
    return str(earliest) if earliest is not None else None


async def bind_first_object(
    session: AsyncSession,
    *,
    session_id: object,
    account_id: object,
    support_object_id: object,
    now: datetime | None = None,
) -> bool:
    """首对象补绑（支持对象第 6 节）：会话无绑定时补建，有绑定则无操作。

    「判定已有绑定」用主键存在性（repository 的条件插入），不用更新：
    该不变量禁止的是既有绑定的变更；补绑只发生一次——会话已有绑定后再建新对象
    不改绑（第 6 节）。

    为什么需要它（`RQ-ACC-09`）：会话建立时账号没有任何在用对象的，该会话先落
    「无绑定」；引导对话在该会话里创建第一个对象时补建为该会话的唯一绑定。
    这是从无到有的首次绑定，不是改绑。

    Args:
        session: 关系库会话。
        session_id: 会话标识。
        account_id: 建立绑定时所属账号。
        support_object_id: 要绑定的对象。
        now: 参照时间。

    Returns:
        True 表示本次真的建立了绑定；False 表示该会话已有绑定、本次无操作
        （并发下两个对象先后补建时，第二个得 False——这是正常结果，不是错误）。

    Raises:
        ProfileDataError: 任一标识不合法。
    """
    inserted = await repo.insert_session_binding(
        session,
        session_id=session_id,
        account_id=account_id,
        support_object_id=support_object_id,
        now=now,
    )
    return inserted is not None


async def discard_session_binding(session: AsyncSession, *, session_id: object) -> int:
    """删除某会话的对象绑定，返回删除条数（只在会话本身被丢弃时用）。

    唯一合法调用点是「会话刚建好就注定不存在」的补偿删除：应急入口在一个事务里
    落归属行、绑定与首轮注入标记，而运行起步失败时调用方拿不到 `session_id`
    ——那个会话没有任何入口可达。绑定行会独立留在这张表里，而
    :func:`resolve_default_object` 按 `bound_at` 最大的绑定的对象推导「上一次的选择」：
    一个从未存在过的会话就此决定该账号下一次新建会话绑哪个对象。

    不用它做改绑：一个会话恰好一个对象、建立后不再改变（支持对象第 6 节），
    「可切换」影响的是后续新建的会话。

    Returns:
        实际删除的条数；该会话没有绑定时为 0（不是错误）。

    Raises:
        ProfileDataError: 会话标识不合法。
    """
    return await repo.delete_session_binding(session, session_id=session_id)


async def read_session_bindings(
    session: AsyncSession,
    *,
    session_ids: Sequence[object],
) -> dict[str, SessionObjectBinding]:
    """按会话标识批量取绑定，返回「会话标识 → 绑定行」。

    会话列表的对象名取数入口（`surfaces/consult` 的 `ObjectNameReader` 实现用它）：
    一页最多 `modules/accounts/session_repository.LIST_MAX_LIMIT` 条，逐会话取绑定会
    让整页产生同等次数的查询，这里一次查询覆盖整页。

    与逐条取（`repo.get_session_binding`）取到的是同一行：`session_id` 是绑定表主键，
    一个会话至多一行，因此批量读既不需要排序也没有选取歧义。

    不做归属判定（与逐条版一致）：绑定行不带对象名，调用方拿它去查自己账号的对象名，
    别的账号的绑定在那里必然取不到名字，因此不构成越权读取。

    Returns:
        命中的绑定行，键是会话标识；没有绑定的会话不出现在映射里——调用方据此
        区分「无对象」与「对象名为空」。

    Raises:
        ProfileDataError: 任一会话标识不合法（与逐条版同一判据）。
    """
    rows = await repo.list_session_bindings(session, session_ids=session_ids)
    return {row.session_id: row for row in rows}


# ============================================================================
# 档案条目：写入用例
# ============================================================================


async def propose_item(
    session: AsyncSession,
    *,
    account_id: object,
    support_object_id: object,
    domain: str,
    topic: object,
    description: object,
    origin: str,
    source: dict,
    confirmation: str | None = None,
    contexts: list | None = None,
    manifestations: list | None = None,
    helpful_support: list | None = None,
    unhelpful_support: list | None = None,
    person_report: str | None = None,
    probable_need: str | None = None,
    pending_id: object | None = None,
    now: datetime | None = None,
) -> ProfileItem:
    """写入一条档案条目——`propose_profile_item` 的用例层（唯一写入口）。

    三条硬约束在此硬卡（个性化档案第 7 节：落层判定在工具实现层）：

    1. 推断不得冒充事实：`origin` 属 `system_observation` / `ai_inference` 时，
       传入 `confirmation = confirmed` 的请求被拒绝，而不是被降级改写
       （`RQ-MEM-04`）。静默降级会让调用方以为「我提交的是确认过的事实」。
    2. 领域名非法明确失败，不静默归入「其他」。
    3. 对象必须存在、属于当前账号且未归档（经 `require_writable`）。

    落层由 `origin` 决定（第 3 节的表），不由调用方传入——否则模型就能指定
    「这是一条已确认的事实」。

    Args:
        session: 关系库会话（调用方负责提交）。
        account_id: 当前账号（来自登录态）。
        support_object_id: 归属对象。
        domain: 领域取值，见 `DOMAINS`。
        topic: 该领域下的主题。
        description: 可观察、可执行的描述。
        origin: 生成方式（六值）。
        source: 来源定位（`AC-07` 要求条目带来源，必填）。
        confirmation: 调用方想要的确认状态；`None` 表示按 `origin` 推导。
            显式传入时受硬约束 1 约束。
        contexts: 情境列表。
        manifestations: 表现列表。
        helpful_support: 有效支持列表。
        unhelpful_support: 无效支持列表。
        person_report: 本人怎么说（一期为监护人转述，转述者记在 `source.relayed_by`）。
        probable_need: 可能的需求。
        pending_id: 产生本条目的待处理记录标识（幂等键）。手动补充条目时为 `None`。
        now: 参照时间。

    Returns:
        已加入会话的条目（尚未提交）。

    Raises:
        AuthorizationError: 对象不存在或不属于该账号（文案与「不存在」相同）。
        ObjectArchivedError: 对象已归档，不接受新增写入（文案区分于越权）。
        InferredCannotBeConfirmedError: 推断被尝试写成已确认。
        ProfileDataError: 领域名非法、描述或主题为空，或来源缺失。
    """
    if not isinstance(source, dict) or not source:
        # `AC-07` 要求条目带来源，而来源定位无法从其他参数还原
        # （`propose_profile_item` 契约第 2 节：`source` 是必填）。
        raise ProfileDataError(
            "source 缺失：条目必须带来源定位（AC-07）",
            operation="propose_item",
            detail="source 为空或不是对象",
        )
    if origin in CANDIDATE_ORIGINS and confirmation == CONFIRMATION_CONFIRMED:
        # 硬约束：请求被拒绝，而不是被降级改写（个性化档案第 7 节）。
        raise InferredCannotBeConfirmedError(
            f"生成方式 {origin!r} 不得写成 confirmed（推断不得冒充事实）",
            operation="propose_item",
            detail=f"origin={origin!r} confirmation={confirmation!r}",
        )

    await require_writable(account_id, support_object_id)

    return await repo.insert_item(
        session,
        support_object_id=support_object_id,
        domain=domain,
        topic=topic,
        description=description,
        origin=origin,
        confirmation=confirmation if confirmation is not None else confirmation_on_entry(origin),
        source=source,
        contexts=contexts,
        manifestations=manifestations,
        helpful_support=helpful_support,
        unhelpful_support=unhelpful_support,
        person_report=person_report,
        probable_need=probable_need,
        pending_id=_maybe_uuid(pending_id),
        now=now,
    )


async def add_manual_item(
    session: AsyncSession,
    *,
    account_id: object,
    support_object_id: object,
    domain: str,
    topic: object,
    description: object,
    contexts: list | None = None,
    manifestations: list | None = None,
    now: datetime | None = None,
) -> ProfileItem:
    """使用者在档案页手动补充一条（`RQ-MEM-03` 之外，第 5.2 节允许补充）。

    `origin` 由服务端定为 `user_statement`，不接受调用方传入——生成方式不是
    使用者可选的字段（档案面契约第 5 节）。来源同理：该入口的请求体不含 `source`，
    由服务端补一个可复核的定位（`MANUAL_ENTRY_SOURCE`）。

    Raises:
        AuthorizationError: 对象不存在或不属于该账号。
        ObjectArchivedError: 对象已归档，不接受新增写入（第 5 节：补充走同一写路径）。
        ProfileDataError: 领域名、描述或主题不合法。
    """
    return await propose_item(
        session,
        account_id=account_id,
        support_object_id=support_object_id,
        domain=domain,
        topic=topic,
        description=description,
        origin="user_statement",
        source=dict(MANUAL_ENTRY_SOURCE),
        contexts=contexts,
        manifestations=manifestations,
        now=now,
    )


# ============================================================================
# 档案条目：读取与状态迁移
# ============================================================================


@dataclass(frozen=True, slots=True)
class ItemView:
    """条目的对外视图：必须含 `origin`、`confirmation`、`freshness`。

    `read_profile_items` 契约第 3、4 节：返回不得为了「让输出干净」而省略来源与
    确认状态。`freshness` 是当下算出的有效值（候选超 90 天即 `stale`），
    因此它可能与库里的存储值不同。
    """

    item_id: str
    domain: str
    topic: str
    description: str
    origin: str
    confirmation: str
    freshness: str
    contexts: list
    manifestations: list
    helpful_support: list
    unhelpful_support: list
    person_report: str | None
    probable_need: str | None
    source: dict
    first_recorded_at: datetime
    last_confirmed_at: datetime
    superseded_by: str | None
    supersedes: str | None


class GroupedItems(NamedTuple):
    """条目按「稳定层 / 候选层」分组返回（档案面契约第 3 节）。

    候选单独成组而不是混进 `items`：这是候选层视觉不变量的服务端侧保证
    （`AC-18` 要求未确认内容只能出现在「待确认」分组，由返回结构保证，
    而不是靠前端自己分）。
    """

    items: list[ItemView]
    candidates: list[ItemView]


async def read_items(
    session: AsyncSession,
    *,
    account_id: object,
    support_object_id: object,
    domains: list[str] | None = None,
    include_candidates: bool = False,
    include_superseded: bool = False,
    limit: int = repo.ITEMS_DEFAULT_LIMIT,
    now: datetime | None = None,
) -> GroupedItems:
    """读取条目，候选层单独成组（`read_profile_items` 契约）。

    `include_candidates = False` 时不得混入候选（契约第 4 节）。

    `include_superseded = False`（缺省）时历史条目不返回；为真时它们随 `items`
    返回，带 `freshness = historical` 与互指的 `superseded_by`／`supersedes`，
    档案页据此在行首出「已更正」标。`rejected` 条目不受这个开关影响，一律不返回
    ——否定过的内容不得再进入对话，那是绝对的（契约第 3、4.1 节）。

    `include_superseded` 与 `include_candidates` 是两条独立的轴（时效 / 层）：
    前者只管「已被取代的旧条目可回看」，后者只管「未确认的候选是否返回」。
    两者都真时，「已被取代的候选」也会返回——它不是互斥组合。

    Raises:
        AuthorizationError: 对象不存在或不属于该账号。不得用空结果冒充
            「没有档案」——越权必须显式失败（第 5 节失败语义）。
        ProfileDataError: 领域过滤含词表外取值，或标识不合法。
    """
    await require_owned(account_id, support_object_id)
    rows = await repo.list_items(
        session,
        support_object_id=support_object_id,
        include_candidates=include_candidates,
        include_superseded=include_superseded,
        domains=domains,
        limit=limit,
    )
    reference = now if now is not None else _now()
    return _group(rows, now=reference)


def _group(rows: list[ProfileItem], *, now: datetime) -> GroupedItems:
    """把行按稳定层/候选层分组，并算出各自的当下新鲜度。

    归组判据是 `lands_in_stable_layer`（第 3 节的唯一判据），
    与 SQL 侧的过滤表达同一件事——因此 SQL 只负责缩小范围，
    最终分组由纯函数决定，两处不会给出互相矛盾的结论。

    历史条目（`freshness = historical`）按「它曾属哪一层」判，与新鲜度无关：
    未确认的系统推断（`system_observation`／`ai_inference`）即便已被取代也归 `candidates`
    （`AC-18`：输出与摘要中不出现任何未确认的系统推断，未确认的内容以「待确认」单独呈现）。
    历史且曾属稳定层的（四种非推断来源，或已确认）归 `items`：那是档案页第 62 行
    「已更正」标的路径，落在完整条目区。

    为什么由服务端定组：候选单独成组是候选层视觉不变量的服务端侧保证
    （档案面契约第 3 节：由返回结构保证，而不是靠前端自己分）。
    历史条目只可能在调用方打开 `include_superseded` 时出现在这里，
    因此缺省路径（`include_superseded = false`）的分组结果不变。
    """
    stable: list[ItemView] = []
    candidates: list[ItemView] = []
    for row in rows:
        view = _to_view(row, now=now)
        is_history = row.freshness == FRESHNESS_HISTORICAL
        # 历史条目只把新鲜度这一项按 `current` 判：它是历史只因被取代，不代表它曾属候选层。
        # 归组判据因此仍只有 `lands_in_stable_layer` 一条。
        layer_freshness = FRESHNESS_CURRENT if is_history else row.freshness
        if lands_in_stable_layer(origin=row.origin, confirmation=row.confirmation, freshness=layer_freshness):
            stable.append(view)
        else:
            candidates.append(view)
    return GroupedItems(items=stable, candidates=candidates)


async def confirm_item(
    session: AsyncSession,
    *,
    account_id: object,
    item_id: object,
    now: datetime | None = None,
) -> ProfileItem:
    """确认一条候选条目：此后进稳定层（第 3 节：候选 → 使用者确认 → 稳定档案）。

    只能作用于候选条目（`confirmation = unconfirmed`）：对已确认或已否定的
    条目返回失败（档案面契约第 4 节：422）。

    Raises:
        AuthorizationError: 条目不存在或不属于该账号（经对象归属判定）。
        ProfileItemNotFoundError: 条目不存在，或当前不是 `unconfirmed`。
    """
    row = await _load_owned_item(session, account_id=account_id, item_id=item_id)
    updated = await repo.confirm_item(session, item_id=item_id, now=now)
    if updated is None:
        raise ProfileItemNotFoundError(
            row.item_id,
            f"当前确认状态为 {row.confirmation!r}，只有候选条目（unconfirmed）可确认",
        )
    return updated


async def reject_item(
    session: AsyncSession,
    *,
    account_id: object,
    item_id: object,
) -> ProfileItem:
    """否定一条候选：不物理删除，此后不进摘要、不参与注入、不再作为候选提出（第 2 节）。

    Raises:
        AuthorizationError: 条目不存在或不属于该账号。
        ProfileItemNotFoundError: 条目不存在，或当前不是 `unconfirmed`。
    """
    row = await _load_owned_item(session, account_id=account_id, item_id=item_id)
    updated = await repo.reject_item(session, item_id=item_id)
    if updated is None:
        raise ProfileItemNotFoundError(
            row.item_id,
            f"当前确认状态为 {row.confirmation!r}，只有候选条目（unconfirmed）可否定",
        )
    return updated


async def correct_item(
    session: AsyncSession,
    *,
    account_id: object,
    item_id: object,
    description: object,
    topic: object | None = None,
    contexts: list | None = None,
    manifestations: list | None = None,
    now: datetime | None = None,
) -> tuple[ProfileItem, ProfileItem]:
    """纠正：新增取代条目，旧条目转 `historical` 并互指（第 3 节不变量 3）。

    不做物理覆盖，也不静默改写。载荷是新条目的完整形状而不是补丁字段
    （档案面契约第 4 节）：档案条目是「谁在何时说的」的记录，补丁会让新条目继承
    旧条目的来源与时间，那才是真正的污染。因此新条目由服务端重新计算生成方式、
    来源定位、`first_recorded_at` 与 `last_confirmed_at`。

    新描述的生成方式是 `user_statement`（描述由使用者在档案页写），入档即
    `confirmed`（第 3 节的落层表），因此新条目直接进稳定层。**沿用旧条目的
    `origin` 才是缺陷**：它会造出 `ai_inference + confirmed` 这类行——正是
    `propose_item` 与 Worker 两处硬拒、且第 7 节要求「请求被拒绝」的组合——
    同时把使用者亲手改的词在界面与摘要里标成「模型推断」（第 2 节：
    `origin` 回答「谁在什么位置上说的」）。

    Args:
        session: 关系库会话（调用方负责提交）。
        account_id: 当前账号。
        item_id: 被纠正的旧条目。
        description: 新的描述（必填——纠正要有实质变更）。
        topic: 新的主题；省略则沿用旧条目的主题。
        contexts: 新的情境列表；省略则沿用旧条目。
        manifestations: 新的表现列表；省略则沿用旧条目。
        now: 参照时间。

    Returns:
        `(新条目, 旧条目)`——新条目已带 `supersedes` 反向指针，
        旧条目已置 `historical` 与 `superseded_by`。

    Raises:
        AuthorizationError: 条目不存在或不属于该账号。
        ProfileDataError: 描述或主题为空，或纠正无变更（新描述与旧描述相同）。
        ProfileItemNotFoundError: 旧条目已被取代（或不在 `current` 态）——
            同一条目只被纠正一次，重复提交不覆写既有的取代关系。
    """
    old = await _load_owned_item(session, account_id=account_id, item_id=item_id)
    new_description = _require_change(description, old.description)
    reference = now if now is not None else _now()

    # 新条目：沿用旧条目的归属与领域（纠正的是内容，不是这条事实属于哪一类），
    # 但生成方式、来源与时间重新计算——见 docstring。
    new_item = await repo.insert_item(
        session,
        support_object_id=old.support_object_id,
        domain=old.domain,
        topic=old.topic if topic is None else topic,
        description=new_description,
        # `origin` 是「谁在什么位置上说的」，而这句话是使用者在档案页写的：
        # `add_manual_item` 的同源入口也定 `user_statement`（契约第 5 节）。
        origin="user_statement",
        # 与第 3 节的落层表一致：`user_statement` 入档即 `confirmed`。它不是
        # 「推断被写成事实」——这条新条目已经不是推断（`origin` 已改），
        # 因此这条路径不再绕过第 7 节的硬约束，也不成为 `confirm` 之外的第二个
        # 「候选转稳定」入口（契约第 4 节：确认才是那道闸门）。
        confirmation=CONFIRMATION_CONFIRMED,
        # 来源定位只回答「这句话在何处可复核」：纠正的请求体不含 `source`，
        # 因此由服务端补档案页这个通道标记，与「补充一条」同源。只逐字继承旧条目
        # 的来源才是污染——那会把使用者新写的词定位到提出旧推断的那次会话
        # （契约第 4 节：补丁会让新条目继承旧条目的来源与时间）。旧条目的
        # 来源仍留在旧行上，经 `supersedes` 可回看。
        source=dict(MANUAL_ENTRY_SOURCE),
        contexts=list(contexts) if contexts is not None else list(old.contexts or []),
        manifestations=list(manifestations) if manifestations is not None else list(old.manifestations or []),
        helpful_support=list(old.helpful_support or []),
        unhelpful_support=list(old.unhelpful_support or []),
        person_report=old.person_report,
        probable_need=old.probable_need,
        now=reference,
    )
    # 先把新条目落库拿到主键，再写两条互指：`superseded_by` 需要一个真实存在的
    # 目标主键，而外键会在 flush 时校验它。
    await session.flush()
    # 先做带状态判据的那一步：旧条目已被取代（或不在 `current` 态）时这里拿不到行，
    # 整笔纠正失败——不静默改写既有的取代关系，也不留下只有单向指针的半成品
    # （第 3 节不变量 3）。这一步同时挡住「同一纠正请求被重复提交」：第二次会
    # 覆写 `superseded_by`，让先前的取代者成为悬挂指针。
    superseded = await repo.mark_superseded(session, old_item_id=old.item_id, new_item_id=new_item.item_id)
    if superseded is None:
        # 载荷里的旧状态是读取时的快照：两次纠正请求各自都能通过 `_require_change`，
        # 只有带状态判据的这一步能分辨出来。
        raise ProfileItemNotFoundError(
            old.item_id,
            f"读取时新鲜度为 {old.freshness!r}、取代指针{'非空' if old.superseded_by is not None else '为空'}："
            "已被取代（或已在纠正过程中被删除）的条目不能再被纠正",
        )
    await repo.set_item_supersedes(session, item_id=new_item.item_id, supersedes=old.item_id)
    await session.refresh(new_item)
    return new_item, superseded


async def delete_item(
    session: AsyncSession,
    *,
    account_id: object,
    item_id: object,
) -> ProfileItem:
    """删除一条条目（`RQ-MEM-03`、`AC-08`：删除须覆盖该内容在检索与衍生中的使用）。

    与 `rejected` 的区别：删除不留取代条目；`rejected` 是另一条路径
    （使用者否定一条候选），不在这里表达（档案面契约第 4 节）。

    归属先判定再删，且「没删到行」不回报成功：条目不存在、不属于该账号，
    或已被删除（条目是物理删除，库表里没有留痕）三种情形一律抛
    `AuthorizationError`——档案面契约第 6 节要求「对象／条目越权或不存在
    → 404，文案与『不存在』逐字相同」。2026-09-30 编排器裁决 1 明确了这一点：
    把越权或不存在读成成功会让本面成为全应用唯一的例外。

    归为同一种失败是有意的：区分它们等于提供条目枚举通道，也就泄露了
    属主信息。

    Returns:
        被删除的条目行。

    Raises:
        AuthorizationError: 条目不存在、不属于该账号，或已被删除
            （三种情形文案逐字相同）。
        ProfileDataError: 标识不合法。
    """
    row = await _load_owned_item(session, account_id=account_id, item_id=item_id)
    # 归属判定之后仍走带归属圈定的 DELETE：两道判据同源，且并发下
    # 行被另一个请求抢先删掉时这里拿到 None——按「不可访问」报，不谎报成功。
    deleted = await repo.delete_item_scoped(session, item_id=row.item_id, account_id=account_id)
    if deleted is None:
        raise AuthorizationError(OBJECT_NOT_ACCESSIBLE_MESSAGE)
    return row


# ============================================================================
# 取数：摘要与应急上下文
# ============================================================================


async def summary(
    session: AsyncSession,
    *,
    account_id: object,
    support_object_id: object,
    now: datetime | None = None,
) -> ProfileSummary:
    """一页摘要：十二个字段，只从稳定层取数（第 4 节）。

    三处必须成立：

    1. `rejected` 条目不进摘要；
    2. 候选条目不进摘要——只有候选条目的对象返回「无档案」而不是空对象（第 10 节）；
    3. 摘要不新增事实：它只选编与压缩，不产生稳定层之外的内容。

    摘要里的 `freshness` 恒为 `current`：取数只走稳定层，而 `stale` 只降权
    非稳定层的未确认条目（第 3 节），两者交集为空——被降权的条目取不到，
    因此这里没有可标注的 `stale`。陈旧标注在条目读取路径上
    （`ItemView.freshness`，须显式检索候选）。已被取代（`historical`）的条目不出现。

    Raises:
        AuthorizationError: 对象不存在或不属于该账号。
    """
    await require_owned(account_id, support_object_id)
    reference = now if now is not None else _now()
    rows = await repo.read_stable_items_by_domains(session, support_object_id=support_object_id)

    by_domain: dict[str, list[SummaryEntry]] = {}
    for row in rows:
        entry = _to_summary_entry(row, now=reference)
        by_domain.setdefault(row.domain, []).append(entry)

    fields: list[SummaryField] = []
    covered = 0
    for key, (label, domains) in SUMMARY_FIELD_DOMAINS.items():
        entries: list[SummaryEntry] = []
        for domain in domains:
            entries.extend(by_domain.get(domain, []))
        if entries:
            fields.append(SummaryField(key=key, label=label, items=entries))
            covered += len(entries)

    possibly_stale = await repo.has_unfinished_pending_writes(session, support_object_id=support_object_id)
    return ProfileSummary(
        support_object_id=str(support_object_id),
        has_profile=covered > 0,
        fields=fields,
        item_count=covered,
        generated_at=reference,
        possibly_stale=possibly_stale,
    )


async def emergency_context(
    session: AsyncSession,
    *,
    account_id: object,
    support_object_id: object,
    now: datetime | None = None,
) -> EmergencyContext:
    """应急预取：八组，只取稳定层（第 8 节）。

    某组未预存时显式返回 `None`（absent），不为空列表让调用方去猜
    ——空列表与「这组没有内容」在语义上不同，而注入文案必须写「未预存」
    而不是暗示「没有这种情况」（技能设计：缺失即标注，不得由模型补全）。

    `communication` 组是具名结构（第 8 节），由 `communication` 字段承载：
    每个具名键要么带条目、要么不出现，两者可区分。

    无档案对象时 `has_profile = False`——调用方按 `AC-02` 标注「本次未使用个性化档案」。

    Raises:
        AuthorizationError: 对象不存在或不属于该账号。
    """
    await require_owned(account_id, support_object_id)
    reference = now if now is not None else _now()

    groups: dict[str, list[SummaryEntry] | None] = {}
    communication: dict[str, SummaryEntry] = {}
    for group in EMERGENCY_GROUPS:
        if group == EMERGENCY_GROUP_COMMUNICATION:
            # 具名结构：按 topic 精确取三个键，各自独立判定 absent。
            rows = await repo.read_stable_items_by_domains(
                session,
                support_object_id=support_object_id,
                domains=(EMERGENCY_COMMUNICATION_DOMAIN,),
                topics=EMERGENCY_COMMUNICATION_FIELDS,
            )
            for row in rows:
                communication[row.topic] = _to_summary_entry(row, now=reference)
            continue
        if group in EMERGENCY_STRATEGY_FIELDS:
            # 策略组：按条目字段取数（不是按领域，见函数的 docstring）。
            field_name = EMERGENCY_STRATEGY_FIELDS[group]
            rows = await repo.read_stable_items_by_domains(
                session,
                support_object_id=support_object_id,
                domains=(EMERGENCY_STRATEGY_DOMAIN,),
            )
            entries = _entries_from_list_field(rows, field=field_name, now=reference)
            groups[group] = entries if entries else None
            continue
        rows = await repo.read_stable_items_by_domains(
            session,
            support_object_id=support_object_id,
            domains=EMERGENCY_GROUP_DOMAINS[group],
        )
        entries = [_to_summary_entry(row, now=reference) for row in rows]
        # absent 与「空」必须可区分：显式 None 表示这一组未预存（第 8 节）。
        groups[group] = entries if entries else None

    return EmergencyContext(
        support_object_id=str(support_object_id),
        has_profile=bool(communication) or any(value is not None for value in groups.values()),
        groups=groups,
        communication=communication,
    )


async def resolve_for_context(
    session: AsyncSession,
    *,
    account_id: object,
    support_object_id: object,
    include_candidates: bool = False,
    now: datetime | None = None,
) -> list[ItemView]:
    """供 consult 装配上下文取数（第 8 节的 `resolve_for_context`）。

    `include_candidates` 为真时，候选条目必须带 `confirmation = unconfirmed` 标记
    ——调用方与模型都不得把它当作事实。`rejected` 条目一律不返回。

    已被取代的历史条目同样不返回，且这条路径不接 `read_items` 的回看开关：
    历史条目「此后不参与注入」（个性化档案第 122 行），历史回看只开给给人看的读路径。
    注入路径上没有「打开历史」的入参，因此这条约束在参数形状里就不可表达。

    参数 `situation` 不在此实现：第 8 节的签名收了它，但第 4 节没有定义任何
    与情境相关的取数判据（取数完全由领域映射决定）。为一个没有判据的参数
    安排筛选逻辑会是在发明规则，因此显式不收它——登记于报告「未决问题」。

    Raises:
        AuthorizationError: 对象不存在或不属于该账号。
        ProfileDataError: 标识不合法。
    """
    grouped = await read_items(
        session,
        account_id=account_id,
        support_object_id=support_object_id,
        include_candidates=include_candidates,
        limit=repo.ITEMS_MAX_LIMIT,
        now=now,
    )
    if not include_candidates:
        return grouped.items
    return [*grouped.items, *grouped.candidates]


# ============================================================================
# 内部：视图转换与归属圈定
# ============================================================================


def _now() -> datetime:
    """当前 UTC 时间（与 repository 的参照时间同源语义）。"""
    return datetime.now(timezone.utc)


def _maybe_uuid(raw: object | None) -> uuid.UUID | None:
    """把可选的待处理记录标识解析成 UUID。

    用 `object` 收参而不是 `uuid.UUID | None`，因为它是运行时边界：
    调用方可能给出字符串形式的标识（工具层与测试都常见）。
    """
    if raw is None:
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    return repo.to_item_uuid(raw)


def _require_change(description: object, previous: str) -> str:
    """校验纠正确实带来了变更（档案面契约第 1 节：纠正无变更 → 422）。

    Raises:
        ProfileDataError: 描述为空，或与旧描述逐字相同。
    """
    if not isinstance(description, str):
        raise ProfileDataError(
            "纠正的 description 必须是字符串",
            operation="correct_item",
            detail=f"type={type(description).__name__}",
        )
    stripped = description.strip()
    if not stripped:
        raise ProfileDataError(
            "纠正的 description 不得为空",
            operation="correct_item",
            detail="去空白后长度为 0",
        )
    if stripped == previous.strip():
        # 无变更的纠正是「新增取代条目 + 旧条目转历史」的空转：它会白白让一条
        # 有效认识变成历史态。显式拒绝，而不是静默当成功。
        raise ProfileDataError(
            "纠正无变更：新描述与旧描述相同",
            operation="correct_item",
            detail="description 与旧值逐字相同",
        )
    return stripped


async def _load_owned_item(session: AsyncSession, *, account_id: object, item_id: object) -> ProfileItem:
    """取一条属于当前账号的条目；不存在或越权都明确失败。

    归属判定经条目所属对象：条目表没有 `account_id` 列（归属经对象表达），
    因此先读条目拿到 `support_object_id`，再交给 `require_owned` 判定。
    这样「条目存在但不是你的」与「条目不存在」得到同一个结果——
    不提供条目枚举通道。

    Raises:
        AuthorizationError: 条目不存在，或它所属的对象不属于该账号
            （两种情况文案逐字相同）。
        ProfileItemNotFoundError: 条目存在且属于该账号，但状态不允许该操作以外
            的调用方会先拿到这一层；本函数只负责归属。
        ProfileDataError: 标识不合法。
    """
    try:
        row = await repo.get_item(session, item_id=item_id)
    except ProfileDataError as exc:
        # 畸形标识归入「不可访问」：否则调用方能区分「碰巧猜中真实标识」与
        # 「根本不是合法标识」，后者反而更值得隐瞒（与 authz 的同一处理）。
        raise AuthorizationError(OBJECT_NOT_ACCESSIBLE_MESSAGE) from exc
    if row is None:
        raise AuthorizationError(OBJECT_NOT_ACCESSIBLE_MESSAGE)
    await require_owned(account_id, row.support_object_id)
    return row


def _to_view(row: ProfileItem, *, now: datetime) -> ItemView:
    """把一行转成对外视图，并把新鲜度换算成当下的有效值。"""
    return ItemView(
        item_id=str(row.item_id),
        domain=row.domain,
        topic=row.topic,
        description=row.description,
        origin=row.origin,
        confirmation=row.confirmation,
        freshness=effective_freshness(
            origin=row.origin,
            confirmation=row.confirmation,
            freshness=row.freshness,
            last_confirmed_at=row.last_confirmed_at,
            now=now,
        ),
        contexts=list(row.contexts or []),
        manifestations=list(row.manifestations or []),
        helpful_support=list(row.helpful_support or []),
        unhelpful_support=list(row.unhelpful_support or []),
        person_report=row.person_report,
        probable_need=row.probable_need,
        source=dict(row.source or {}),
        first_recorded_at=row.first_recorded_at,
        last_confirmed_at=row.last_confirmed_at,
        superseded_by=str(row.superseded_by) if row.superseded_by is not None else None,
        supersedes=str(row.supersedes) if row.supersedes is not None else None,
    )


def _to_summary_entry(row: ProfileItem, *, now: datetime) -> SummaryEntry:
    """把一行转成摘要条目（带来源与时间；第 4 节要求可追溯到具体条目）。"""
    return SummaryEntry(
        item_id=str(row.item_id),
        origin=row.origin,
        last_confirmed_at=row.last_confirmed_at,
        description=row.description,
        freshness=effective_freshness(
            origin=row.origin,
            confirmation=row.confirmation,
            freshness=row.freshness,
            last_confirmed_at=row.last_confirmed_at,
            now=now,
        ),
    )


def _entries_from_list_field(rows: list[ProfileItem], *, field: str, now: datetime) -> list[SummaryEntry]:
    """把条目上的一个列表字段摊平成注入项（每一字段值各成一条）。

    为什么摊平而不是按条目返回：应急注入要的是「有哪些有效支持」这类清单，
    而不是「哪几条档案记录」（第 8 节 `proven_strategies` / `unhelpful_strategies`
    两组的语义即为此）。摊平让一条记录了三种有效支持的条目贡献三条注入项，
    模型据此直接得到可用的支持清单。

    摊平后的每一条仍带来源条目的 `item_id` 与确认时间，因此可追溯
    （第 4 节：摘要每条可追溯到具体条目）。
    """
    entries: list[SummaryEntry] = []
    for row in rows:
        values = getattr(row, field, None) or []
        for value in values:
            if not isinstance(value, str) or not value.strip():
                # 空值与非字符串值不产生注入项：它们不承载任何可执行内容。
                continue
            entries.append(
                SummaryEntry(
                    item_id=str(row.item_id),
                    origin=row.origin,
                    last_confirmed_at=row.last_confirmed_at,
                    description=value.strip(),
                    freshness=effective_freshness(
                        origin=row.origin,
                        confirmation=row.confirmation,
                        freshness=row.freshness,
                        last_confirmed_at=row.last_confirmed_at,
                        now=now,
                    ),
                )
            )
    return entries


#: 供测试与调用方核对「摘要字段覆盖性」（第 10 节验证项：十二个字段都能从
#: 第 6 节领域取值生产出来）。做成断言式辅助而不是注释承诺。
def assert_summary_coverable() -> None:
    """断言摘要十二字段与领域词表的一致性（第 4 节的覆盖性判据）。

    第 4 节原文：十二个字段全部有对应领域——这是领域取值覆盖性的判据。
    若哪天有人改了领域词表而漏改这份映射，本函数立即失败。

    Raises:
        AssertionError: 字段数不是 12，或某个字段的取数领域不在词表内。
    """
    assert len(SUMMARY_FIELD_DOMAINS) == 12, f"摘要字段应为 12 个，实际 {len(SUMMARY_FIELD_DOMAINS)} 个"
    unknown = {domain for _, domains in SUMMARY_FIELD_DOMAINS.values() for domain in domains if domain not in DOMAINS}
    assert not unknown, f"摘要取数引用了词表外的领域：{sorted(unknown)}"


__all__ = [
    "SUMMARY_FIELD_DOMAINS",
    "EmergencyContext",
    "GroupedItems",
    "ItemView",
    "ProfileSummary",
    "SummaryEntry",
    "SummaryField",
    "add_manual_item",
    "archive_object",
    "assert_summary_coverable",
    "bind_first_object",
    "confirm_item",
    "correct_item",
    "create_object",
    "delete_item",
    "emergency_context",
    "list_objects",
    "propose_item",
    "read_items",
    "read_session_bindings",
    "reject_item",
    "rename_object",
    "resolve_default_object",
    "resolve_for_context",
    "restore_object",
    "summary",
]
