"""资料条目表与检索节点表

Revision ID: 113a04901d24
Revises:
Create Date: 2026-09-29 19:36:18.728803

业务意图（依据 docs/技术设计/technical-details/RAG策略.md 第 2 节与
docs/技术设计/decisions/检索链归入library模块.md）：

- 本迁移建出检索链的两张表：条目表是事实真源（状态、撤下、来源、适用范围、
  `keywords`/`aliases`），节点表是它的投影（供向量检索），两者同库同事务——
  撤下可在一个事务里同时改条目状态与删节点，`RQ-KB-04` 的「撤下即刻不可检索」成立。
- 节点表结构必须与 LlamaIndex `PGVectorStore` 期望的逐列一致（表名 `data_`
  前缀、`id bigint` + sequence、`metadata_ jsonb`、`embedding vector(2560)`）；
  取用方以 `perform_setup=False` 使用它，DDL 由本迁移拥有（实测见 TODO `TECH-19`）。
- 三个字面路 GIN trigram 索引建在 `title`/`keywords`/`aliases` 上。用文本列而非
  数组：`gin_trgm_ops` 不接受 `text[]`，`array_to_string` 表达式索引又非 IMMUTABLE
  （2026-09-29 实测）。
- 中文约束已实测：本库 locale `en_US.utf8`，汉字被认作词字符；`LIKE` 走 GIN、
  `~` 正则走顺序扫描。
"""

from typing import Sequence, Union

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "113a04901d24"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建扩展与两张表。

    扩展必须最先建：`vector` 列类型与 `gin_trgm_ops` 操作符类都依赖它们。
    用 `CREATE EXTENSION IF NOT EXISTS` 使迁移在已启用扩展的库上可重复执行。
    """
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "campfire_knowledge_item",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("applicable_scope", sa.Text(), nullable=False),
        sa.Column("version", sa.String(length=100), server_default=sa.text("'1'"), nullable=False),
        sa.Column("withdrawn", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'published'"), nullable=False),
        sa.Column("keywords", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("aliases", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("doc_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campfire_knowledge_item")),
        sa.UniqueConstraint("source_path", "doc_hash", name="uq_campfire_knowledge_item_source_doc"),
        comment="专业资料条目：事实真源（内容与来源字段的权威）",
    )
    # 字面路索引（RAG 策略第 3.1 节）：中文须用 LIKE/ILIKE 才走 GIN。
    op.create_index(
        "ix_campfire_knowledge_item_aliases_trgm",
        "campfire_knowledge_item",
        ["aliases"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"aliases": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_campfire_knowledge_item_keywords_trgm",
        "campfire_knowledge_item",
        ["keywords"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"keywords": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_campfire_knowledge_item_title_trgm",
        "campfire_knowledge_item",
        ["title"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    # 检索的 SQL 内过滤维度（不变量：过滤在 SQL 内完成）。
    op.create_index(
        "ix_campfire_knowledge_item_withdrawn_status",
        "campfire_knowledge_item",
        ["withdrawn", "status"],
        unique=False,
    )

    # 节点表：列名与类型由框架决定，不可随意改（见模块头部说明）。
    op.create_table(
        "data_campfire_node",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("metadata_", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("node_id", sa.String(), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=2560), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_campfire_node")),
        comment="检索节点：条目表的投影，供 PGVectorStore 读写（perform_setup=False）",
    )
    # 表达式索引：框架自建 ref_doc_id 一个，另补检索真正用到的过滤维度。
    op.create_index(
        "ix_data_campfire_node_item_id",
        "data_campfire_node",
        [sa.literal_column("((metadata_ ->> 'item_id'))")],
        unique=False,
    )
    op.create_index(
        "ix_data_campfire_node_library",
        "data_campfire_node",
        [sa.literal_column("((metadata_ ->> 'library'))")],
        unique=False,
    )
    op.create_index("ix_data_campfire_node_node_id", "data_campfire_node", ["node_id"], unique=False)
    op.create_index(
        "ix_data_campfire_node_ref_doc_id",
        "data_campfire_node",
        [sa.literal_column("((metadata_ ->> 'ref_doc_id'))")],
        unique=False,
    )
    op.create_index(
        "ix_data_campfire_node_withdrawn",
        "data_campfire_node",
        [sa.literal_column("((metadata_ ->> 'withdrawn'))")],
        unique=False,
    )


def downgrade() -> None:
    """回滚：删两张表。

    不删扩展：`vector` 与 `pg_trgm` 可能被本项目其他表或后续迁移复用，
    回滚单个迁移不该影响它们（删扩展会连带删除依赖它的列与索引）。
    """
    op.drop_index("ix_data_campfire_node_withdrawn", table_name="data_campfire_node")
    op.drop_index("ix_data_campfire_node_ref_doc_id", table_name="data_campfire_node")
    op.drop_index("ix_data_campfire_node_node_id", table_name="data_campfire_node")
    op.drop_index("ix_data_campfire_node_library", table_name="data_campfire_node")
    op.drop_index("ix_data_campfire_node_item_id", table_name="data_campfire_node")
    op.drop_table("data_campfire_node")
    op.drop_index("ix_campfire_knowledge_item_withdrawn_status", table_name="campfire_knowledge_item")
    op.drop_index(
        "ix_campfire_knowledge_item_title_trgm",
        table_name="campfire_knowledge_item",
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.drop_index(
        "ix_campfire_knowledge_item_keywords_trgm",
        table_name="campfire_knowledge_item",
        postgresql_using="gin",
        postgresql_ops={"keywords": "gin_trgm_ops"},
    )
    op.drop_index(
        "ix_campfire_knowledge_item_aliases_trgm",
        table_name="campfire_knowledge_item",
        postgresql_using="gin",
        postgresql_ops={"aliases": "gin_trgm_ops"},
    )
    op.drop_table("campfire_knowledge_item")
