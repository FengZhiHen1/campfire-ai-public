"""个性化档案与支持对象的表结构、词表与落层判据。

职责：定义 `campfire_support_object`、`profile_item`、`campfire_session_object` 三张表，
以及领域词表、确认状态词表、新鲜度词表与落层判据（纯函数）。
边界：表与判据在此；读写用例在 `repository`，业务用例在 `service`，注销清除在 `purge`。
参考：docs/技术设计/technical-details/支持对象.md 第 3、6 节；
docs/技术设计/technical-details/个性化档案.md 第 2、3 节。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from campfire.core.db import Base, new_uuid
from campfire.core.pending_write import ORIGIN_AI_INFERENCE, ORIGIN_SYSTEM_OBSERVATION, ORIGINS

#: 账号标识的列宽（与 `PendingWrite.account_id`、账本、邀请码一致）。
MAX_ACCOUNT_ID_LENGTH = 128

#: 支持对象名的列宽（支持对象第 3 节）。64 是使用者自起称呼的长度上界。
MAX_DISPLAY_NAME_LENGTH = 64

#: 会话标识的列宽。SDK 的会话表该列是无界 `String`，本表显式设上界（CORE-11）：
#: 会话标识进入 URL 与我们的查询键，无界输入不该被接受。128 对 UUID 形态留有充分余量。
MAX_SESSION_ID_LENGTH = 128

# ---------------------------------------------------------------------------
# 领域取值（个性化档案第 6 节的十四个一级模块，另设「其他」兜底）
# ---------------------------------------------------------------------------

DOMAIN_BASIC_IDENTITY = "basic_identity"  # 1 基本身份与档案信息
DOMAIN_ABOUT_SELF = "about_self"  # 2 关于本人、优势、兴趣与目标
DOMAIN_COMMUNICATION = "communication"  # 3 沟通
DOMAIN_SENSORY_PROCESSING = "sensory_processing"  # 4 感觉处理
DOMAIN_ROUTINES_AND_CHANGE = "routines_and_change"  # 5 日常规律与变化
DOMAIN_EMOTIONAL_REGULATION = "emotional_regulation"  # 6 情绪与自我调节
DOMAIN_TRIGGERS_AND_SUPPORT = "triggers_and_support"  # 7 触发因素与支持策略
DOMAIN_EXECUTIVE_FUNCTION = "executive_function"  # 8 执行功能与认知特点
DOMAIN_DAILY_LIVING = "daily_living"  # 9 日常生活与适应功能
DOMAIN_SOCIAL_RELATIONSHIPS = "social_relationships"  # 10 社交与关系
DOMAIN_PHYSICAL_MEDICAL = "physical_medical"  # 11 身体与医疗
DOMAIN_LEARNING_AND_WORK = "learning_and_work"  # 12 学习与工作
DOMAIN_RISK_AND_CRISIS = "risk_and_crisis"  # 13 风险与危机
DOMAIN_GOALS_AND_PLANS = "goals_and_plans"  # 14 目标与长期计划
DOMAIN_OTHER = "other"  # 兜底，保证不丢失

#: 合法领域取值集合。闭集落 CHECK：静默写入未知领域会让摘要与应急取数无声漏条。
DOMAINS: frozenset[str] = frozenset(
    {
        DOMAIN_BASIC_IDENTITY,
        DOMAIN_ABOUT_SELF,
        DOMAIN_COMMUNICATION,
        DOMAIN_SENSORY_PROCESSING,
        DOMAIN_ROUTINES_AND_CHANGE,
        DOMAIN_EMOTIONAL_REGULATION,
        DOMAIN_TRIGGERS_AND_SUPPORT,
        DOMAIN_EXECUTIVE_FUNCTION,
        DOMAIN_DAILY_LIVING,
        DOMAIN_SOCIAL_RELATIONSHIPS,
        DOMAIN_PHYSICAL_MEDICAL,
        DOMAIN_LEARNING_AND_WORK,
        DOMAIN_RISK_AND_CRISIS,
        DOMAIN_GOALS_AND_PLANS,
        DOMAIN_OTHER,
    }
)

_DOMAINS_SQL = ", ".join(f"'{value}'" for value in sorted(DOMAINS))

# ---------------------------------------------------------------------------
# 确认状态与新鲜度
# ---------------------------------------------------------------------------

#: 使用者是否确认过这条内容（个性化档案第 2 节）。
CONFIRMATION_UNCONFIRMED = "unconfirmed"
CONFIRMATION_CONFIRMED = "confirmed"
#: 使用者明确否定（不物理删除：「否定过这件事」本身是可追溯事实）。
CONFIRMATION_REJECTED = "rejected"

CONFIRMATIONS: frozenset[str] = frozenset({CONFIRMATION_UNCONFIRMED, CONFIRMATION_CONFIRMED, CONFIRMATION_REJECTED})

_CONFIRMATIONS_SQL = ", ".join(f"'{value}'" for value in sorted(CONFIRMATIONS))

#: 是否仍是当前认识（个性化档案第 2 节）。
FRESHNESS_CURRENT = "current"
#: 已被取代（纠正产生）：旧条目转此值，不参与取数。
FRESHNESS_HISTORICAL = "historical"
#: 降权（长期未确认）：不进摘要与默认读取，但不删除。
FRESHNESS_STALE = "stale"

FRESHNESSES: frozenset[str] = frozenset({FRESHNESS_CURRENT, FRESHNESS_HISTORICAL, FRESHNESS_STALE})

_FRESHNESSES_SQL = ", ".join(f"'{value}'" for value in sorted(FRESHNESSES))

#: `origin` 词表的 SQL 字面量。从 `core.pending_write.ORIGINS` 派生，不另写一份清单：
#: 六值这个词表的所有者是写入路径第 3 节（`core/pending_write` 已实现并带 CHECK），
#: 本模块沿用同一个集合——两处各写一份必然漂移（CORE-10）。
_ORIGINS_SQL = ", ".join(f"'{value}'" for value in sorted(ORIGINS))

#: 降权时限（个性化档案第 3 节：90 天）。
#:
#: 90 天够长到不误伤低频但真实的观察，够短到不让陈旧推断污染输出。
STALE_AFTER_DAYS = 90

#: 「直接进稳定层」的生成方式（个性化档案第 3 节的落层表前四行）。
#:
#: `third_party_report` 与 `document` 虽直接进稳定层，但入档时 `confirmation`
#: 仍是 `unconfirmed`（明确提供的信息，但未经使用者本人确认）。
STABLE_ORIGINS: frozenset[str] = frozenset({"user_statement", "guardian_observation", "third_party_report", "document"})

#: 「只进候选层」的生成方式（第 3 节表后两行）：系统观察与模型推断。
CANDIDATE_ORIGINS: frozenset[str] = frozenset({ORIGIN_SYSTEM_OBSERVATION, ORIGIN_AI_INFERENCE})

#: 入档时的 `confirmation` 取值（第 3 节的落层表）。
#:
#: 只有 `user_statement` 与 `guardian_observation` 是 `confirmed`：
#: 一期使用者即陈述人，陈述本身即确认，无需第二次确认（RQ-MEM-02「直接陈述零确认入档」）。
#: 其余四种一律 `unconfirmed`。
CONFIRMED_ON_ENTRY_ORIGINS: frozenset[str] = frozenset({"user_statement", "guardian_observation"})

#: 档案页使用者书写入口的来源标记（档案面 HTTP 契约第 5 节的「补充一条」与第 4 节的纠正）。
#:
#: 两个入口的请求体都不含 `source`，而 `AC-07` 要求条目带来源定位——因此由服务端补一个
#: 可复核的定位。它记录的是「这条由使用者在档案页写下」，不是会话内来源。
#: 两处共用一个标记而不是各写一份：同一事实两处定义必然漂移（CORE-10）。
MANUAL_ENTRY_SOURCE: dict[str, str] = {"channel": "profile_page"}

# ---------------------------------------------------------------------------
# 应急预取的八组（个性化档案第 8 节）
# ---------------------------------------------------------------------------

#: 八组的键名（照第 8 节逐字取）。
EMERGENCY_GROUP_BASELINE = "baseline"
EMERGENCY_GROUP_KNOWN_TRIGGERS = "known_triggers"
EMERGENCY_GROUP_COMMUNICATION = "communication"
EMERGENCY_GROUP_SENSORY_PROFILE = "sensory_profile"
EMERGENCY_GROUP_MEDICAL_RISKS = "medical_risks"
EMERGENCY_GROUP_PROVEN_STRATEGIES = "proven_strategies"
EMERGENCY_GROUP_UNHELPFUL_STRATEGIES = "unhelpful_strategies"
EMERGENCY_GROUP_SAFETY_HISTORY = "safety_history"

#: 八组的键名与取数领域。
#:
#: 第 8 节只给键名形状、不给键到领域的映射（第 4 节给了摘要十二字段的映射）。
#: 此处的映射按各领域在第 6 节覆盖的子主题就近取：
#: - `baseline` 取「情绪与自我调节」的平静基线；
#: - `known_triggers` 取「触发因素与支持策略」（该领域的主题即触发因素与情境）；
#: - `communication` 取「沟通」（信息处理速度即 Processing time）；
#: - `sensory_profile` 取「感觉处理」；
#: - `medical_risks` 取「身体与医疗」与「风险与危机」两个领域；
#: - `safety_history` 取「风险与危机」。
#:
#: `proven_strategies` 与 `unhelpful_strategies` 不在本表里：它们与
#: `known_triggers` 同属「触发因素与支持策略」领域，但语义是条目里的不同字段
#: （`helpful_support` 与 `unhelpful_support`），不是不同领域。若按领域取数，
#: 同一条条目会同时出现在三组里，而「有效支持」与「无效支持」本是成对相反的
#: 两类内容——那会把注入变成重复噪声。两者的取数规则见
#: `EMERGENCY_STRATEGY_FIELDS`。
EMERGENCY_GROUP_DOMAINS: dict[str, tuple[str, ...]] = {
    EMERGENCY_GROUP_BASELINE: (DOMAIN_EMOTIONAL_REGULATION,),
    EMERGENCY_GROUP_KNOWN_TRIGGERS: (DOMAIN_TRIGGERS_AND_SUPPORT,),
    EMERGENCY_GROUP_COMMUNICATION: (DOMAIN_COMMUNICATION,),
    EMERGENCY_GROUP_SENSORY_PROFILE: (DOMAIN_SENSORY_PROCESSING,),
    EMERGENCY_GROUP_MEDICAL_RISKS: (DOMAIN_PHYSICAL_MEDICAL, DOMAIN_RISK_AND_CRISIS),
    EMERGENCY_GROUP_SAFETY_HISTORY: (DOMAIN_RISK_AND_CRISIS,),
}

#: 两个策略组借以取数的条目字段（第 8 节的 `proven_strategies` 与
#: `unhelpful_strategies`）。
#:
#: 键 → 在其上取数的条目字段名。这两个组的内容是条目里成对的字段，
#: 因此取数按字段而不按领域：只有带该字段的条目才出内容，
#: 每条字段值各成一条注入项。
EMERGENCY_STRATEGY_FIELDS: dict[str, str] = {
    EMERGENCY_GROUP_PROVEN_STRATEGIES: "helpful_support",
    EMERGENCY_GROUP_UNHELPFUL_STRATEGIES: "unhelpful_support",
}

#: 两个策略组取数时先按领域圈定范围（它们的内容都在「触发因素与支持策略」里）。
EMERGENCY_STRATEGY_DOMAIN = DOMAIN_TRIGGERS_AND_SUPPORT

#: 八组的键名集合（顺序按第 8 节书写顺序：先框架七组，`unhelpful_strategies` 插在
#: 有效策略之后——它在框架里与有效策略成对）。
EMERGENCY_GROUPS: tuple[str, ...] = (
    EMERGENCY_GROUP_BASELINE,
    EMERGENCY_GROUP_KNOWN_TRIGGERS,
    EMERGENCY_GROUP_COMMUNICATION,
    EMERGENCY_GROUP_SENSORY_PROFILE,
    EMERGENCY_GROUP_MEDICAL_RISKS,
    EMERGENCY_GROUP_PROVEN_STRATEGIES,
    EMERGENCY_GROUP_UNHELPFUL_STRATEGIES,
    EMERGENCY_GROUP_SAFETY_HISTORY,
)

#: `communication` 组在稳定层里的三个具名键（第 8 节的
#: `communication{baseline, best_mode, processing_time_seconds}`）。
#:
#: 第 8 节给定形而未给存储约定。本实现用条目的 `topic` 承载这三个键：
#: `topic` 等于下列值之一的稳定条目，其 `description` 即该键的取值。
#: 未预存时该键不出现（调用方据此走「未预存」分支，而不是读到空串去猜）。
EMERGENCY_COMMUNICATION_FIELDS: tuple[str, ...] = ("baseline", "best_mode", "processing_time_seconds")

#: `communication` 组借以承载三个具名键的领域。
#:
#: 它必须落在「沟通」领域（第 8 节的取数语义），而三个键是具名结构：
#: 该组返回 `{键: 条目}` 而不是条目列表，因此取数不能与其余七组共用同一形状。
EMERGENCY_COMMUNICATION_DOMAIN = DOMAIN_COMMUNICATION

# ---------------------------------------------------------------------------
# 落层判据（纯函数）
# ---------------------------------------------------------------------------


def confirmation_on_entry(origin: str) -> str:
    """按生成方式给出入档时的 `confirmation`（第 3 节的落层表）。

    为什么由 `origin` 决定而不是由调用方给：落层判定的位置是工具实现层
    （第 7 节），若确认状态由调用方任意传入，模型就能把推断写成已确认。

    Args:
        origin: 生成方式，取值见 `ORIGINS`。

    Returns:
        `confirmed`（陈述与监护人观察）或 `unconfirmed`（其余四种）。
    """
    return CONFIRMATION_CONFIRMED if origin in CONFIRMED_ON_ENTRY_ORIGINS else CONFIRMATION_UNCONFIRMED


def lands_in_stable_layer(*, origin: str, confirmation: str, freshness: str) -> bool:
    """落层判据（第 3 节的唯一判据）。

    判据：`freshness = current` 且（`origin` 属四种非推断来源，或 `confirmation = confirmed`）。

    两个方向都要理解：

    - `third_party_report` 与 `document` 进稳定层却仍是 `unconfirmed`
      ——「直接稳定层」说的是它参与取数，不是「已确认」。
    - `system_observation` 与 `ai_inference` 在 `confirmation = unconfirmed` 时不进稳定层；
      使用者经确认入口把它置为 `confirmed` 后即进——这正是「推断要使用者确认才成事实」的落点。

    Args:
        origin: 生成方式。
        confirmation: 确认状态。
        freshness: 新鲜度（存储值，不是按 90 天算出的有效值）。

    Returns:
        True 表示参与摘要、注入与应急取数。
    """
    if freshness != FRESHNESS_CURRENT:
        return False
    return origin in STABLE_ORIGINS or confirmation == CONFIRMATION_CONFIRMED


def effective_freshness(
    *, origin: str, confirmation: str, freshness: str, last_confirmed_at: datetime, now: datetime
) -> str:
    """算出当下的新鲜度：把「长期未确认的候选条目」降权为 `stale`（第 3 节）。

    降权是取数期的判定，不落后台任务：只有候选条目（非四种稳定来源，且未被确认）
    会随 90 天时限降权；已确认为事实的条目不因时间推移而降权
    ——「当前认识」不会因为没人再点一次确认而失效。

    降权不删除数据：返回的只是一个标记，行仍在库里，且被检索到时须标注陈旧。

    Args:
        origin: 生成方式。
        confirmation: 确认状态。
        freshness: 存储的新鲜度。
        last_confirmed_at: 最近确认时间；降权的计时起点。
        now: 参照时间（显式传入，便于测试与纯函数性）。

    Returns:
        存储值本身，或 `stale`（候选条目超时）。
    """
    if freshness != FRESHNESS_CURRENT or confirmation != CONFIRMATION_UNCONFIRMED:
        return freshness
    if origin in STABLE_ORIGINS:
        # `third_party_report` 与 `document` 虽未确认但在稳定层，不属「未经确认的推断」。
        return freshness
    if now - last_confirmed_at >= timedelta(days=STALE_AFTER_DAYS):
        return FRESHNESS_STALE
    return freshness


# ---------------------------------------------------------------------------
# 表
# ---------------------------------------------------------------------------


class SupportObject(Base):
    """一个支持对象：平台围绕提供支持的具体孤独症人士（支持对象第 3 节）。

    它只有三件事：这个对象是谁的、叫什么、是否仍在用。不承载关于这个人的事实
    （那是档案），也不承载使用者自身的经验（那是通用记忆）。

    生命周期没有删除，只有 `archived_at` 这一个状态位（第 4 节）：
    归档而非删除，是为了避免在途写入的「查不到不等于从未存在」歧义——
    行始终存在，因此本表不需要墓碑（认证与账号第 8 节的墓碑是为真删准备的）。
    """

    __tablename__ = "campfire_support_object"

    #: 业务主键。不外露为账号或分区键——它是档案的归属键，不是任何图库分区键。
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=new_uuid)
    #: 属主账号（即身份服务的用户标识，认证与账号第 3 节）。
    #:
    #: 不建外键到身份服务表：身份服务的表由 core 拥有，跨进程外键不可靠
    #: （支持对象第 3 节，同「不建映射表」的取向）。
    account_id: Mapped[str] = mapped_column(String(MAX_ACCOUNT_ID_LENGTH), nullable=False)
    #: 对象名（使用者自己起的称呼）。非空判据落存储层 CHECK：
    #: 空名会让切换器出现无法辨认的条目，而「先查后写」挡不住并发与直连写入（第 3 节）。
    display_name: Mapped[str] = mapped_column(String(MAX_DISPLAY_NAME_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()"), onupdate=sql_text("now()")
    )
    #: 归档时间；为空表示仍在用。唯一的生命周期状态位（第 3 节）。
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # 切换到某账号的对象列表，且默认只取在用对象。
        Index("ix_campfire_support_object_account_archived", "account_id", "archived_at"),
        # 默认排序（创建先后），也是「上次选择」推导的回退路径（第 6 节）。
        Index("ix_campfire_support_object_account_created", "account_id", "created_at"),
        # 非空名落存储层（CORE-05）：任何位置只要有一个非空白字符即可。
        #
        # 判据用正则而不是 `length(btrim(display_name)) > 0`：PostgreSQL 的
        # `btrim` 默认只剥空格，不含制表、换行与其它空白（实测
        # `length(btrim(E'\t')) = 1`），字面照搬那条写法会让「纯制表符」的名字通过
        # ——而设计要求的是「空名或全空白都明确失败」（支持对象第 8 节）。
        # `[[:space:]]` 覆盖空格、制表、换行、回车、换页与垂直制表。
        #
        # 放在存储层是因为它要拒绝一切写入者（含运维直连）：空名或肉眼看不见的名字
        # 会让切换器出现无法辨认的条目，而「先查后写」挡不住并发与旁路写入。
        CheckConstraint("display_name ~ '[^[:space:]]'", name="display_name_not_blank"),
        # 刻意不建唯一约束：同一账号下可以有两个同名对象（两个人都叫「小宝」是真实情形），
        # 同名由使用者自己辨认，不靠数据库拒绝（第 3 节）。
        {"comment": "支持对象：档案的归属主体，生命周期为创建/改名/归档/恢复，无删除"},
    )


class ProfileItem(Base):
    """一条档案条目：关于某个支持对象的可追溯认识（个性化档案第 2 节）。

    四个字段分工，不合并成一个枚举：

    - `origin` 回答「谁在什么位置上说的」（生成方式）；
    - `source` 回答「这句话在何处可复核」（来源定位）；
    - `confirmation` 回答「是否被使用者确认过」；
    - `freshness` 回答「是否仍是当前认识」。
    """

    __tablename__ = "profile_item"

    #: 条目标识。
    item_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=new_uuid)
    #: 归属支持对象。外键落在存储层：跨对象的条目混入会让「两个对象的档案互不可见」
    #: （AC-22）失去最后一道兜底；注销时须先删条目再删对象（支持对象第 7 节）。
    support_object_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campfire_support_object.id"), nullable=False
    )
    #: 领域取值，见 `DOMAINS`（十四个一级模块之一或「其他」）。
    domain: Mapped[str] = mapped_column(String(32), nullable=False)
    #: 该领域下的具体特征或主题（自由文本）。
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    #: 可观察、可执行的描述。非空落 CHECK：空描述是「进了列表但看不出内容」的条目。
    description: Mapped[str] = mapped_column(Text, nullable=False)
    #: 情境、表现、有效支持、无效支持。JSONB 数组：
    #: 形状是「同类值的列表」，长度随条目而变，没有第二个真源。
    contexts: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=sql_text("'[]'::jsonb"), default=list)
    manifestations: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'[]'::jsonb"), default=list
    )
    helpful_support: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'[]'::jsonb"), default=list
    )
    unhelpful_support: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'[]'::jsonb"), default=list
    )
    #: 本人怎么说。一期只能由监护人转述，转述这一事实记在 `source.relayed_by`
    #: （第 2 节：不为此增设第七个 `origin` 取值——转述是来源定位，不是生成方式）。
    person_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 可能的需求。
    probable_need: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 生成方式，取值见 `core.pending_write.ORIGINS`（六值）。
    #: 复用 `core` 的集合而不是另写一份：两处定义同一个契约必然漂移（CORE-10）。
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    #: 来源定位（会话 id、消息定位、工具名、时间、转述者）。
    #: 本期无外键也无固定键集：第 2 节只要求它承载「这句话在何处可复核」。
    source: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: 确认状态，取值见 `CONFIRMATIONS`。
    confirmation: Mapped[str] = mapped_column(String(16), nullable=False)
    #: 新鲜度（存储值），取值见 `FRESHNESSES`。
    #: `stale` 的实际判定在取数期（`effective_freshness`），此处只存显式状态。
    freshness: Mapped[str] = mapped_column(
        String(16), nullable=False, default=FRESHNESS_CURRENT, server_default=sql_text(f"'{FRESHNESS_CURRENT}'")
    )
    #: 首次记录时间。
    first_recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )
    #: 最近确认时间。它同时是降权计时起点（第 3 节的 90 天）。
    last_confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )
    #: 被取代时指向新条目；旧条目不删除（纠正 = 新增 + 旧转 historical 并互指）。
    #:
    #: `ondelete="SET NULL"` 是必需的：两个指针互指（本列与 `supersedes`），
    #: 若用默认的 `NO ACTION`，删除任一侧都会被另一侧挡住——而 `AC-08` 要求
    #: 删除真的生效。指针是说明性的（「这条取代了那条」），删掉对方后
    #: 把它置空即可，不该让历史指针否决一次删除。
    superseded_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("profile_item.item_id", ondelete="SET NULL"),
        nullable=True,
    )
    #: 本条取代的旧条目（`superseded_by` 的反向指针，两者互指）。
    #: 档案面契约第 4 节纠正的响应带 `supersedes`，因此这一侧必须落地。
    #: `ondelete="SET NULL"` 的理由同上。
    supersedes: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("profile_item.item_id", ondelete="SET NULL"),
        nullable=True,
    )
    #: 产生本条目的待处理记录，幂等键（写入路径第 5 节：档案条目对 `pending_id`
    #: 建唯一约束，重复消费不产生重复条目）。
    #:
    #: 可空且这是必然：手动补充条目（档案面契约第 5 节）不经待处理记录。
    #: PostgreSQL 的唯一约束允许多个 NULL，因此「唯一」与「可空」正好同时成立。
    pending_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, unique=True)

    __table_args__ = (
        # 按对象取条目（列表、摘要、应急取数的主查询）。
        Index("ix_profile_item_object_domain", "support_object_id", "domain"),
        # 按对象 + 新鲜度筛稳定层。
        Index("ix_profile_item_object_freshness", "support_object_id", "freshness"),
        # 词表与形状落存储层（CORE-05）。四个闭集都是契约的一部分：
        # 静默写入未知领域会让取数无声漏条；未知确认状态会让「是否已确认」判错方向。
        CheckConstraint(f"domain IN ({_DOMAINS_SQL})", name="domain"),
        CheckConstraint(f"origin IN ({_ORIGINS_SQL})", name="origin"),
        CheckConstraint(f"confirmation IN ({_CONFIRMATIONS_SQL})", name="confirmation"),
        CheckConstraint(f"freshness IN ({_FRESHNESSES_SQL})", name="freshness"),
        # 空描述被拒（档案面契约第 1 节：空描述 422；存储层兜底同样的判据）。
        # 判据同 `display_name_not_blank`：`btrim` 只剥空格，纯制表符会漏过。
        CheckConstraint("description ~ '[^[:space:]]'", name="description_not_blank"),
        # 空主题被拒：条目行以 `topic` 为标题，空主题让列表与分组失去可辨认性。
        CheckConstraint("topic ~ '[^[:space:]]'", name="topic_not_blank"),
        {"comment": "档案条目：稳定层与候选层按 origin 与 confirmation 分流"},
    )


class SessionObjectBinding(Base):
    """会话与支持对象的绑定（支持对象第 6 节）。

    主键是 `session_id`：一个会话只有一个对象；「可切换」影响的是后续新建的会话，
    不是进行中的会话。因此同一会话内不存在改绑——改绑只会撞主键。

    本表不回答「会话属于哪个账号」（那是 `modules/accounts` 的 `campfire_session`）：
    它只在会话已绑定对象时才有行，无对象账号的会话先落「无绑定」。
    两表回答两个不同的问题，不互斥、不互相推导。
    """

    __tablename__ = "campfire_session_object"

    #: 会话标识。不建外键到 SDK 的会话表：会话真源由 SDK 拥有，
    #: 且归属判定不靠本表（支持对象第 6 节：不得用本表有无行推断会话是否存在）。
    session_id: Mapped[str] = mapped_column(String(MAX_SESSION_ID_LENGTH), primary_key=True)
    #: 建立绑定时所属账号。
    account_id: Mapped[str] = mapped_column(String(MAX_ACCOUNT_ID_LENGTH), nullable=False)
    #: 绑定的支持对象。
    support_object_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campfire_support_object.id"), nullable=False
    )
    #: 绑定时间。用于推导「上一次的选择」（取该账号 `bound_at` 最大的那条绑定）。
    bound_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )

    __table_args__ = (
        # 推导「上一次的选择」。
        Index("ix_campfire_session_object_account_bound", "account_id", "bound_at"),
        {"comment": "会话与支持对象的绑定：一个会话恰好一个对象，建立后不再改变"},
    )


__all__ = [
    # 常量
    "CANDIDATE_ORIGINS",
    "CONFIRMED_ON_ENTRY_ORIGINS",
    "EMERGENCY_COMMUNICATION_DOMAIN",
    "EMERGENCY_COMMUNICATION_FIELDS",
    "EMERGENCY_GROUP_DOMAINS",
    "EMERGENCY_GROUPS",
    "MANUAL_ENTRY_SOURCE",
    "MAX_ACCOUNT_ID_LENGTH",
    "MAX_DISPLAY_NAME_LENGTH",
    "MAX_SESSION_ID_LENGTH",
    "STABLE_ORIGINS",
    "STALE_AFTER_DAYS",
    # 词表
    "CONFIRMATIONS",
    "CONFIRMATION_CONFIRMED",
    "CONFIRMATION_REJECTED",
    "CONFIRMATION_UNCONFIRMED",
    "DOMAINS",
    "DOMAIN_ABOUT_SELF",
    "DOMAIN_BASIC_IDENTITY",
    "DOMAIN_COMMUNICATION",
    "DOMAIN_DAILY_LIVING",
    "DOMAIN_EMOTIONAL_REGULATION",
    "DOMAIN_EXECUTIVE_FUNCTION",
    "DOMAIN_GOALS_AND_PLANS",
    "DOMAIN_LEARNING_AND_WORK",
    "DOMAIN_OTHER",
    "DOMAIN_PHYSICAL_MEDICAL",
    "DOMAIN_RISK_AND_CRISIS",
    "DOMAIN_ROUTINES_AND_CHANGE",
    "DOMAIN_SENSORY_PROCESSING",
    "DOMAIN_SOCIAL_RELATIONSHIPS",
    "DOMAIN_TRIGGERS_AND_SUPPORT",
    "EMERGENCY_GROUP_BASELINE",
    "EMERGENCY_GROUP_COMMUNICATION",
    "EMERGENCY_GROUP_KNOWN_TRIGGERS",
    "EMERGENCY_GROUP_MEDICAL_RISKS",
    "EMERGENCY_GROUP_PROVEN_STRATEGIES",
    "EMERGENCY_GROUP_SAFETY_HISTORY",
    "EMERGENCY_GROUP_SENSORY_PROFILE",
    "EMERGENCY_GROUP_UNHELPFUL_STRATEGIES",
    "EMERGENCY_STRATEGY_DOMAIN",
    "EMERGENCY_STRATEGY_FIELDS",
    "FRESHNESSES",
    "FRESHNESS_CURRENT",
    "FRESHNESS_HISTORICAL",
    "FRESHNESS_STALE",
    # 判据
    "confirmation_on_entry",
    "effective_freshness",
    "lands_in_stable_layer",
    # 表
    "ProfileItem",
    "SessionObjectBinding",
    "SupportObject",
]
