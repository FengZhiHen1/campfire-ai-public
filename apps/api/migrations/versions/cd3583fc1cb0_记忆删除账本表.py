"""记忆删除账本表

Revision ID: cd3583fc1cb0
Revises: 113a04901d24
Create Date: 2026-09-29 21:16:27.934584

业务意图（依据 docs/技术设计/technical-details/通用记忆.md 第 7 节与
docs/技术设计/decisions/通用记忆归属为账号.md）：

- 本迁移建出通用记忆的**删除账本**。这是记忆模块在关系库侧的**唯一一张表**：
  episode 原文与派生事实都在 Graphiti 的图库里，账本只记「哪条记忆已被删除」。
- **为什么必须有这张表**：Graphiti 的 ``remove_episode`` 只删该 episode **独占**的
  实体与边——共享实体的摘要不重算、被它强化过的边残留、它标记失效的边保留失效标记
  （源码实读）。纯 ``remove_episode`` 无法满足 `RQ-MEM-03`「删除须覆盖检索与衍生中
  的使用」。因此**语义删除的生效点是本账本**：两条读路径读图库前先按它过滤；
  图库内的物理残留只是存储问题，登记为扩展缝（不构成验收违反）。
- **`episode_key` 是确定性 episode uuid**（由 `pending_id` 派生，与 `pending_write`
  的幂等键同源），**不是 `name`**：图库的身份是 `uuid`
  （`MERGE (n:Episodic {uuid: $uuid})`，2026-09-29 实测），`name` 只是属性。
  该列建**唯一约束**——同一条记忆重复删除不得产生第二行，删除本身也须幂等。
- **`account_id` 是分区键同源**（`group_id = account_id`，按账号归属、不随支持
  对象分区）：账号级清理按它筛，也是「一次查询一个分区」的落点。
- **`derived_uuids` 是尽力清单、不作过滤依据**：一条边可带多个来源 episode
  （`EntityEdge.episodes` 是列表，实测），靠 uuid 清单无法覆盖「删除后又被合法
  复用」的边——过滤判据是「来源 episode 在账本中」。

索引只建两条：`(account_id, deleted_at)` 供账号级清理与排查，`reason` 供告警与
审计（纠正与账号清理的量级不同）。`episode_key` 不另建普通索引——唯一约束自带索引，
而时间线回看的过滤正是按它等值查。

本迁移经 `--autogenerate` 生成后人工调整：删去了 autogenerate 误产的
`drop_table_comment` 两条（见下）。**根因已修**：`campfire_knowledge_item` 与
`data_campfire_node` 的表注释由上一个迁移写入，而 ORM 侧未声明，导致每次自动生成
都会产出「删注释」这种与本次改动无关的破坏性操作；已在两个模型的 `__table_args__`
里补齐 comment，metadata 与库内实际一致，autogenerate 不再漂移。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "cd3583fc1cb0"
down_revision: Union[str, Sequence[str], None] = "113a04901d24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建删除账本表与两条索引。

    **只加表，不改动图库**：账本保障的是「读取侧不再返回」，图库内的物理清理
    按对象批量另行执行、不在删除请求路径内（通用记忆第 7、11 节）。
    """
    op.create_table(
        "campfire_memory_deletion_ledger",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("episode_key", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_by", sa.UUID(), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column(
            "derived_uuids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campfire_memory_deletion_ledger")),
        sa.UniqueConstraint("episode_key", name=op.f("uq_campfire_memory_deletion_ledger_episode_key")),
        comment="通用记忆的删除账本：语义删除的唯一生效点（读取侧按此过滤）",
    )
    op.create_index(
        "ix_campfire_memory_deletion_ledger_account_deleted_at",
        "campfire_memory_deletion_ledger",
        ["account_id", "deleted_at"],
        unique=False,
    )
    op.create_index(
        "ix_campfire_memory_deletion_ledger_reason",
        "campfire_memory_deletion_ledger",
        ["reason"],
        unique=False,
    )


def downgrade() -> None:
    """回滚：删表与索引。

    ⚠️ 回滚**不恢复**已删除的记忆：账本记的是「删除发生过」，表一旦消失，
    图库里的残留派生物会重新出现在读路径上。因此回滚只在「确认这些记忆
    不需要再被屏蔽」时执行，不是无副作用的 schema 回退。
    """
    op.drop_index("ix_campfire_memory_deletion_ledger_reason", table_name="campfire_memory_deletion_ledger")
    op.drop_index(
        "ix_campfire_memory_deletion_ledger_account_deleted_at",
        table_name="campfire_memory_deletion_ledger",
    )
    op.drop_table("campfire_memory_deletion_ledger")
