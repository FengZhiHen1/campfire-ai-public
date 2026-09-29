"""通用记忆的表结构：删除账本。

归属（见 docs/项目结构设计.md 第 6 节与
docs/技术设计/technical-details/通用记忆.md 第 7 节）：本模块拥有「通用记忆的写入
与读取、时间演变与失效判定」。episode 与派生事实存在 Graphiti 的图库里，
**关系库侧只有这一张表**——删除账本。

## 为什么需要删除账本（不是可选的记账）

Graphiti 的 ``remove_episode`` 只删该 episode **独占**的实体与边：共享实体的摘要
不重算、被它强化过的边残留、它标记失效的边保留失效标记（源码实读，见通用记忆第 7 节）。
纯 ``remove_episode`` 无法满足 `RQ-MEM-03`「删除须覆盖检索与衍生中的使用」。

因此**语义删除的生效点是本账本，不是图库**：两条读路径读图库前先按本表过滤。
图库内的物理残留只是存储问题，登记为扩展缝（通用记忆第 11 节）。

## 两个设计要点（都在通用记忆第 7 节有依据）

1. **`episode_key` 是确定性 episode uuid**（由 `pending_id` 派生，与
   `pending_write` 的幂等键同源）——不是 `name`。图库的身份是 `uuid`
   （`MERGE (n:Episodic {uuid: $uuid})`，实测），`name` 只是属性。
2. **`derived_uuids` 是「尽力清单」**：删除时能查到的派生物 uuid（边与节点）。
   它**不是**过滤依据——过滤走「来源 episode 在账本中」这一判据，因为一条边可以
   带多个来源 episode（`EntityEdge.episodes` 是列表，实测），靠 uuid 清单无法
   覆盖「删除后又被合法复用」的边。
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from campfire.core.db import Base, new_uuid

#: 删除原因的词表。**集中定义**，因为它是契约的一部分（通用记忆第 7 节的表结构），
#: 且调用方需要按原因区分处置：`account_deletion` 是账号级清理，其余是单条语义删除。
DELETION_REASON_USER_REQUEST = "user_request"  # 使用者显式删除某条记忆
DELETION_REASON_CORRECTION = "correction"  # 纠正：删旧 episode，另写新 episode
DELETION_REASON_ACCOUNT_DELETION = "account_deletion"  # 账号注销/清理

#: 合法原因取值集合（frozenset：不可变，见 PY-03）。
DELETION_REASONS: frozenset[str] = frozenset(
    {
        DELETION_REASON_USER_REQUEST,
        DELETION_REASON_CORRECTION,
        DELETION_REASON_ACCOUNT_DELETION,
    }
)


class MemoryDeletionLedger(Base):
    """已删除记忆片段的账本：**语义删除的唯一生效点**。

    读取侧按 `episode_key` 过滤 episode 时间线；按「来源 episode 在账本中」过滤
    派生事实（见 ``store.py``）。物理清理图库是另一个动作，不在这张表的语义内。
    """

    __tablename__ = "campfire_memory_deletion_ledger"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    #: 确定性 episode uuid（由 pending_id 派生）。**唯一**：同一条记忆重复删除
    #: 不产生第二行——删除本身也必须是幂等的。
    episode_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    #: 归属账号：分区键同源（`group_id = account_id`）。账号级清理按它筛。
    #:
    #: **为什么是 String 而不是 UUID**（2026-09-29 评审复核修正）：`identity.to_account_id`
    #: 接受的字符集是 Graphiti 的 `group_id` 判据（`[a-zA-Z0-9_-]`），**不只 UUID**——
    #: 而 `accounts/` 仍是占位包、账号标识的形态**尚未决定**（技术栈设计称标识存在
    #: SuperTokens 的 `email` 字段里，业务账号名形态未定）。此前列类型定为 UUID，与
    #: 本校验直接冲突：实测 `'acct_aaa'::uuid` 报 `invalid input syntax for type uuid`，
    #: 即「合法账号键无法落库」，删除与纠正对该类账号不可实现。
    #: 改为 String 后，UUID 形态的账号同样可用（36 字符 < 上界），**不预先收窄契约**；
    #: 宽度与 `identity.MAX_ACCOUNT_ID_LENGTH` 一致。
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )
    #: 发起删除的账号（一期与 account_id 同值；二期机构协作时二者可能不同）。
    #: 类型与 `account_id` 同源，理由同上。
    deleted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: 删除原因，取值见 `DELETION_REASONS`。
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    #: 删除时已知的派生物 uuid 清单（边与节点）。**尽力记录，不作过滤依据**
    #: （见模块说明第 2 点）；物理清理时可作起点。
    derived_uuids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=sql_text("'[]'::jsonb"))

    __table_args__ = (
        # 读取侧按账号 + 时间取账本（账号级清理与排查用）。
        Index(
            "ix_campfire_memory_deletion_ledger_account_deleted_at",
            "account_id",
            "deleted_at",
        ),
        # 按原因筛选（告警与审计：纠正与账号清理的量级不同）。
        Index("ix_campfire_memory_deletion_ledger_reason", "reason"),
        # 说明：`episode_key` 上**只**建唯一约束、不另建普通索引——唯一约束自带索引，
        # 而时间线回看的过滤正是按 episode_key 等值查，走的就是它。
        # 表注释必须在此声明：迁移建表时写 comment、而 ORM 不声明的话，
        # `--autogenerate` 会反复产出 drop_table_comment（2026-09-29 实测）。
        {"comment": "通用记忆的删除账本：语义删除的唯一生效点（读取侧按此过滤）"},
    )


__all__ = [
    "DELETION_REASONS",
    "DELETION_REASON_ACCOUNT_DELETION",
    "DELETION_REASON_CORRECTION",
    "DELETION_REASON_USER_REQUEST",
    "MemoryDeletionLedger",
]
