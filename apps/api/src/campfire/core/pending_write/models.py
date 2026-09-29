"""待处理写入记录的表与状态词表。

归属（2026-09-29 用户裁决）：`pending_write` 是 **profile 与 memory 共用**的事实表，
因此归 `core/`。依据是依赖白名单（[项目结构设计](../../../../../../docs/项目结构设计.md)第 7 节）：
`modules/*` **只能**依赖 `core/*`、**且模块之间不得互相 import**——共用表若放在任一
业务模块里，另一个模块就用不上。这也是 `core/` 里唯一带业务词表（`kind`）的表，
属**有意的例外**：它的形状由[写入路径](../../../../../../docs/技术设计/technical-details/写入路径.md)
第 3 节拥有，词表是契约的一部分。

## 状态机（第 3、6 节）

    pending ──领取──> processing ──成功──> done
       ^                  │
       │                  ├──可重试失败（attempts+1、退避）──> pending
       └──────────────────┘
                          └──超过重试上限──> dead

**不变量**：**「没写进去」不得被当作「写进去了」**——只有 `state = done` 才算写入
成功，其余状态一律视为未写入（第 2 节）。因此本模块不提供「看起来成功」的便捷返回：
状态推进函数都要求显式给出目标状态。

租约（`lease_owner` + `lease_expires_at`）用于**领取**：第 4 节明确「不使用先查后改的
无锁流程」。租约过期视为可重新领取——Worker 崩溃不该让记录永久卡在 `processing`。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from campfire.core.db import Base, new_uuid

#: 记录种类。**只有这两种**（第 3 节）：档案条目与记忆片段。
KIND_PROFILE_ITEM = "profile_item"
KIND_MEMORY_EPISODE = "memory_episode"
KINDS: frozenset[str] = frozenset({KIND_PROFILE_ITEM, KIND_MEMORY_EPISODE})

#: 生成方式（第 3 节的 `origin`）。它决定「能不能写成已确认」这类判定，属契约一部分。
ORIGIN_USER_STATEMENT = "user_statement"  # 使用者自己说的
ORIGIN_GUARDIAN_OBSERVATION = "guardian_observation"  # 监护人观察
ORIGIN_SYSTEM_OBSERVATION = "system_observation"  # 系统观察
ORIGIN_AI_INFERENCE = "ai_inference"  # 模型推断
ORIGINS: frozenset[str] = frozenset(
    {
        ORIGIN_USER_STATEMENT,
        ORIGIN_GUARDIAN_OBSERVATION,
        ORIGIN_SYSTEM_OBSERVATION,
        ORIGIN_AI_INFERENCE,
    }
)

STATE_PENDING = "pending"
STATE_PROCESSING = "processing"
STATE_DONE = "done"
STATE_FAILED = "failed"
STATE_DEAD = "dead"
STATES: frozenset[str] = frozenset({STATE_PENDING, STATE_PROCESSING, STATE_DONE, STATE_FAILED, STATE_DEAD})

#: 尚未终结的状态（可被重新领取/重试）。`failed` 表示「刚失败、等待退避重试」，
#: 与 `pending` 的区别只是可诊断性，**都还不是写入成功**。
UNFINISHED_STATES: frozenset[str] = frozenset({STATE_PENDING, STATE_PROCESSING, STATE_FAILED})

#: 用于 `CHECK` 的 SQL 字面量。**从上面的集合派生**，避免两份清单漂移；排序保证文本稳定。
_KINDS_SQL = ", ".join(f"'{value}'" for value in sorted(KINDS))
_ORIGINS_SQL = ", ".join(f"'{value}'" for value in sorted(ORIGINS))
_STATES_SQL = ", ".join(f"'{value}'" for value in sorted(STATES))


class PendingWrite(Base):
    """一条待写入的事实（第 3 节的形状）。

    表名用 `campfire_` 前缀（`core/db` 的约定），避免与 SuperTokens core 自建表、
    SDK 自建表撞名。
    """

    __tablename__ = "campfire_pending_write"

    #: 幂等键，**在请求事务内生成**（第 3 节）。图库侧的确定性 episode 标识由它派生
    #: （见 `modules/memory/identity.derive_episode_uuid`）。
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    #: 记录种类，决定消费路径与归属字段要求（见下方 `support_object_id`）。
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: 发起者。**记忆的分区键即此值**（`group_id = account_id`，第 3 节）。
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    #: 归属支持对象。**仅 `profile_item` 需要**；`memory_episode` 必须为空
    #: （记忆属账号，不随对象分区——见[通用记忆](../../../../../../docs/技术设计/technical-details/通用记忆.md)第 1 节）。
    #: 该「按 kind 区分必填/可空」的判据**由 CHECK 约束在存储层承载**：
    #: `(kind = 'profile_item') = (support_object_id IS NOT NULL)`，见 `__table_args__`。
    #: 用 CHECK 而不是只在应用层校验，是因为「记忆被误设了对象」这类错误一旦落库，
    #: 后续所有按账号取记忆的查询都会漏掉它（静默）。
    support_object_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: 写入所需的最小载荷（JSONB）。**自足**：Worker 只凭它与 `kind` 就能完成写入，
    #: 不回查业务用例、不依赖请求上下文（第 3 节）。
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: 生成方式，取值见 `ORIGINS`。
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    #: 来源（会话 id、消息 seq、工具名、时间）。JSONB：形状随 kind 不同，
    #: 第 3 节只要求「最小载荷之外的来源信息」，不规定固定键。
    source: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: 处理状态，取值见 `STATES`。**只有 `done` 算写入成功**。
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATE_PENDING, server_default=sql_text(f"'{STATE_PENDING}'")
    )
    #: 已尝试次数（第 6 节：可重试失败时 +1）。
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sql_text("0"))
    #: 下次可尝试时间（退避）。为空表示立即可领取。
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 处理中的 Worker 标识（仅 `processing` 阶段）。
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: 租约到期时间；过期即可被重新领取（Worker 崩溃不该让记录永久卡住）。
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 最后一次失败的摘要。**只记摘要，不复述连接串或凭据**（AGENTS.md 安全条款）。
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()"), onupdate=sql_text("now()")
    )
    #: 终结时间（`done` 或 `dead` 时写入）。与 `updated_at` 分开：后者任何变更都会动，
    #: 而排查要的是「这条记录什么时候结束的」。
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # 兜底扫描的主查询：找「未终结且已到重试时间」的记录。
        # 先按 state 再按 next_attempt_at 排，让扫描能走索引前缀。
        Index("ix_campfire_pending_write_state_next_attempt", "state", "next_attempt_at"),
        # 租约过期回收：找「processing 且租约已过期」的记录。
        Index("ix_campfire_pending_write_lease_expires_at", "lease_expires_at"),
        # 按账号排查（记忆与档案都按账号定位发起者）。
        Index("ix_campfire_pending_write_account_created", "account_id", "created_at"),
        # --- 词表与归属判据落在**存储层**（CORE-05：不变量要落最强可行通道）---
        # 这些词表进审计与「按 kind 分派」，静默写入未知值会让分派无声走空。
        # **名字一律用短名**，由 `core/db` 的 NAMING_CONVENTION 展开为
        # `ck_campfire_pending_write_<name>`（实测：写完整名会被再套一层前缀并截断到
        # 63 字符，与工作区那段已修的账本约束同一个坑）。
        CheckConstraint(f"kind IN ({_KINDS_SQL})", name="kind"),
        CheckConstraint(f"origin IN ({_ORIGINS_SQL})", name="origin"),
        CheckConstraint(f"state IN ({_STATES_SQL})", name="state"),
        # **归属字段按 kind 的必填/可空**（第 3 节的硬要求）：`profile_item` 必须有
        # `support_object_id`；`memory_episode` 必须为空。用「等价」而不是两条独立断言，
        # 是为了让「记忆被误设了对象」与「档案缺了对象」都撞在同一处。
        CheckConstraint(
            "(kind = 'profile_item') = (support_object_id IS NOT NULL)",
            name="support_object_by_kind",
        ),
        # `attempts` 不得为负：负值会让「是否超过重试上限」的判定提前成立/永不成立。
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        {"comment": "待写入事实的真相源：只有 state=done 才算写入成功"},
    )


__all__ = [
    "KINDS",
    "KIND_MEMORY_EPISODE",
    "KIND_PROFILE_ITEM",
    "ORIGINS",
    "ORIGIN_AI_INFERENCE",
    "ORIGIN_GUARDIAN_OBSERVATION",
    "ORIGIN_SYSTEM_OBSERVATION",
    "ORIGIN_USER_STATEMENT",
    "STATES",
    "STATE_DEAD",
    "STATE_DONE",
    "STATE_FAILED",
    "STATE_PENDING",
    "STATE_PROCESSING",
    "UNFINISHED_STATES",
    "PendingWrite",
]
