"""引用索引表

Revision ID: 0fee1666c829
Revises: 65e928565300
Create Date: 2026-10-01 15:28:20.180894

业务意图（依据 docs/技术设计/technical-details/通用基座.md 第 4 节）：

- 本迁移建出引用索引表。它的作用是让输出里的每条「可引用依据」都能回指到业务条目
  （来源、时间、业务标识），因此第 4 节的不变量「没有索引记录的注入消息不得成为
  可引用依据」需要一处落点来写入与读回。
- 这一列 `seq`（自增序号）是为「按写入顺序读回」专门加的，不靠 `recorded_at` 排序：
  记录方的时钟可由装配处注入，同一时刻的多条记录用时间戳无法定序，而端口契约明确要求
  `list_for_run` 按写入顺序返回。
- 主键取 `citation_id` 而不是另立代理键：端口契约要求实现自带超时上界，而超时是
  「结果未知」——它要求「要么按 `citation_id` 幂等，要么超时后按该标识核实」。
  主键即幂等键，写入走 `ON CONFLICT DO NOTHING`，因此重试不会产生重复记录。
- 索引 `ix_campfire_citation_run_seq` 对应 `list_for_run` 的唯一查询形状
  （按运行取、按写入顺序排）：排序键紧随等值键，排序不需要额外一次 sort。

⚠️ 逐行核对过 `upgrade()`：只建本表、一个唯一约束与一个索引，没有任何 drop/remove。
`--autogenerate` 本次只报告「Detected added table 'campfire_citation'」与
「Detected added index 'ix_campfire_citation_run_seq'」，未提议任何 remove_table /
remove_index——白名单过滤器（`migrations/env.py` 的 `include_object`）正常工作，
SuperTokens core 建在同一个库里的几十张无前缀表未被当成待删对象。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0fee1666c829"
down_revision: Union[str, Sequence[str], None] = "65e928565300"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建引用索引表与其查询索引、写入序号。"""
    op.create_table(
        "campfire_citation",
        sa.Column("citation_id", sa.String(length=64), nullable=False),
        #: 写入序号，由数据库自增（`Identity`）而不是应用侧赋值：
        #: 并发写入不会拿到同一个序号，因此它就是可靠的写入顺序。
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        #: 记录时间取记录方给的时刻（`nullable=False`，不带 `server_default`）：
        #: 记录方可能注入时钟，用库时间会让同一批记录有两个时间来源。
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        #: 约束名用 `op.f(...)` 包装的完整名，与 `core/db` 的 NAMING_CONVENTION
        #: 展开结果逐字一致；不包装会被再套一层前缀并截断到 63 字符。
        sa.PrimaryKeyConstraint("citation_id", name=op.f("pk_campfire_citation")),
        sa.UniqueConstraint("seq", name=op.f("uq_campfire_citation_seq")),
        comment="引用索引：注入项的可回指凭据（不是对话的第二份真源）",
    )
    op.create_index(
        "ix_campfire_citation_run_seq",
        "campfire_citation",
        ["run_id", "seq"],
        unique=False,
    )


def downgrade() -> None:
    """回滚：删引用索引表及其索引。

    代价说明：这张表只存回指凭据，不存对话或业务事实（真源在会话消息与业务条目本身，
    见第 2 节的事实归属表），因此回滚丢的是「能回指」这一能力，不会让对话或档案失真。
    代价是历史运行的事件流里那些引用标识将无法再解析——已经落库的 `run_finished`
    事件仍带着它们，所以回滚后按旧运行查看引用会取不到内容。
    """
    op.drop_index("ix_campfire_citation_run_seq", table_name="campfire_citation")
    op.drop_table("campfire_citation")
