"""待处理写入记录表

Revision ID: 5e27503214c3
Revises: 760b797c8bab
Create Date: 2026-09-29 22:38:39.717410

业务意图（依据 docs/技术设计/technical-details/写入路径.md 第 3、4、6 节；
归属裁决见 docs/项目结构设计.md 第 6 节）：

- 建 `campfire_pending_write`：**待写入事实的真相源**。离开请求路径的写入（记忆的
  实体抽取与嵌入是耗时与成本的主要来源）先落这条记录，再由 Worker 消费。
- **不变量**：「没写进去」不得被当作「写进去了」——只有 `state = done` 才算成功，
  其余状态一律视为未写入（第 2 节）。因此 `state` 的默认值是 `pending`，
  **不是**任何看起来像成功的值。
- **归属字段按 kind 区分**（第 3 节的硬要求，2026-09-29 记忆归属裁决）：
  `profile_item` 必须有 `support_object_id`；`memory_episode` 必须为空（记忆属账号、
  不随对象分区）。该判据由 CHECK
  `(kind = 'profile_item') = (support_object_id IS NOT NULL)` 在**存储层**承载——
  只在应用层校验的话，「记忆被误设了对象」一旦落库，后续所有按账号取记忆的查询都会
  漏掉它（静默）。
- **词表落 CHECK**：`kind` / `origin` / `state` 三个闭集都是契约的一部分（进审计与
  「按 kind 分派」），静默写入未知值会让分派无声走空。`attempts >= 0` 同理由：
  负值会让「是否超过重试上限」的判定提前成立或永不成立。
  （这些由 autogenerate 自动写入 `create_table`，实测新建表时它会带上 CHECK——
  与「给既有表补 CHECK 需要手工写」不同，见 `760b797c8bab` 的说明。）
- **索引**对应第 4、6 节的三条查询：兜底扫描（未终结 + 到重试时间）、租约过期回收、
  按账号排查。**租约时长短于扫描周期**（都是 5 分钟，第 10 节），好让 Worker 崩溃
  能在一次扫描内被发现。
- 表名用 `campfire_` 前缀，避免与 SuperTokens core 自建表、SDK 自建表撞名。

**回滚方向**：直接删表。**已排队的待写入事实会随之丢失**——这是删表迁移的固有代价，
部署回滚前须确认队列已清空或可接受该损失（生产环境的回滚决策不在本文件内）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5e27503214c3"
down_revision: Union[str, Sequence[str], None] = "760b797c8bab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建待处理写入记录表、三条索引与五条 CHECK 约束。"""
    op.create_table(
        "campfire_pending_write",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("support_object_id", sa.String(length=128), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("source", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(kind = 'profile_item') = (support_object_id IS NOT NULL)",
            name=op.f("ck_campfire_pending_write_support_object_by_kind"),
        ),
        sa.CheckConstraint("kind IN ('memory_episode', 'profile_item')", name=op.f("ck_campfire_pending_write_kind")),
        sa.CheckConstraint(
            "origin IN ('ai_inference', 'guardian_observation', 'system_observation', 'user_statement')",
            name=op.f("ck_campfire_pending_write_origin"),
        ),
        sa.CheckConstraint(
            "state IN ('dead', 'done', 'failed', 'pending', 'processing')",
            name=op.f("ck_campfire_pending_write_state"),
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_campfire_pending_write_attempts_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campfire_pending_write")),
        comment="待写入事实的真相源：只有 state=done 才算写入成功",
    )
    op.create_index(
        "ix_campfire_pending_write_account_created",
        "campfire_pending_write",
        ["account_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_campfire_pending_write_lease_expires_at",
        "campfire_pending_write",
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_campfire_pending_write_state_next_attempt",
        "campfire_pending_write",
        ["state", "next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    """删表与索引（**已排队的待写入事实会丢失**，见模块头部说明）。"""
    op.drop_index("ix_campfire_pending_write_state_next_attempt", table_name="campfire_pending_write")
    op.drop_index("ix_campfire_pending_write_lease_expires_at", table_name="campfire_pending_write")
    op.drop_index("ix_campfire_pending_write_account_created", table_name="campfire_pending_write")
    op.drop_table("campfire_pending_write")
