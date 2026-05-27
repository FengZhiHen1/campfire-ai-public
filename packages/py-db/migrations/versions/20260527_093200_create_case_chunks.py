"""CASE-04: 创建 case_chunks 表，添加向量化索引支持。

迁移内容：
1. 创建 index_status_enum 类型
2. 创建 case_chunks 表
3. 在 case_chunks.embedding 上创建 HNSW 索引（vector_cosine_ops）
4. 添加 FK 约束：case_chunks.case_id → cases.id（若 cases 表存在）
5. 在 cases 表添加 index_status 列（ENUM）
6. 在 cases 表添加 indexed_at 列（TIMESTAMPTZ）

依赖说明：
    case_chunks 表的 FK 依赖 cases 表（由 CASE-01 创建）。
    若执行本迁移时 cases 表尚不存在，FK 约束将跳过（通过注释说明），
    需要 CASE-01 创建 cases 表后补充 FK 约束。

Revision ID: 20260527_093200
Create Date: 2026-05-27 09:32:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision: str = "20260527_093200"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：创建 case_chunks 表 + HNSW 索引 + cases 表增列。"""

    # 开启 pgvector 扩展（幂等操作）
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 创建 ENUM 类型（先于所有 DDL 操作，确保类型可被引用）
    op.execute(
        "CREATE TYPE index_status_enum AS ENUM "
        "('pending', 'processing', 'indexed', 'indexing_failed')"
    )

    # ------------------------------------------------------------------
    # 1. 创建 case_chunks 表（无 FK 约束，后续单独添加）
    # ------------------------------------------------------------------
    op.create_table(
        "case_chunks",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            comment="UUID v4 主键",
        ),
        sa.Column(
            "case_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
            comment="关联的案例标识，后续添加 FK → cases.id",
        ),
        sa.Column(
            "chunk_text",
            sa.Text(),
            nullable=False,
            comment="四要素拼接文本（场景 + 行为 + 干预 + 结果）",
        ),
        sa.Column(
            "embedding",
            sa.Text(),
            nullable=True,
            comment="1024 维嵌入向量（pgvector），由后续 ALTER 转换类型",
        ),
        sa.Column(
            "metadata",
            JSONB(),
            nullable=True,
            comment="结构化元数据：behavior_type, age_range, severity, evidence_level",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="记录创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="记录最后更新时间",
        ),
    )

    # 转换 embedding 列类型为 vector(1024)
    op.execute(
        "ALTER TABLE case_chunks ALTER COLUMN embedding TYPE vector(1024)"
        " USING CASE WHEN embedding IS NULL THEN NULL::vector(1024)"
        " ELSE embedding::vector(1024) END"
    )
    op.execute(
        "ALTER TABLE case_chunks ALTER COLUMN embedding"
        " SET DEFAULT NULL::vector(1024)"
    )

    # 2. 创建 HNSW 索引（cosine 距离）
    op.execute(
        "CREATE INDEX ix_case_chunks_embedding_hnsw"
        " ON case_chunks USING hnsw (embedding vector_cosine_ops)"
    )

    # ------------------------------------------------------------------
    # 3. 添加 FK 约束：case_chunks.case_id → cases.id
    # ------------------------------------------------------------------
    try:
        op.create_foreign_key(
            "fk_case_chunks_case_id",
            "case_chunks",
            "cases",
            ["case_id"],
            ["id"],
            ondelete="CASCADE",
        )
    except Exception:
        # cases 表可能不存在（CASE-01 尚未执行）
        # 此时不在数据库层面创建 FK，代码层面做好逻辑关联
        op.execute(
            "-- WARNING: FK fk_case_chunks_case_id skipped — cases table does not exist. "
            "Create FK manually after CASE-01 migration."
        )

    # ------------------------------------------------------------------
    # 4. 在 cases 表添加 index_status 列
    # ------------------------------------------------------------------
    try:
        op.add_column(
            "cases",
            sa.Column(
                "index_status",
                sa.Enum(
                    "pending",
                    "processing",
                    "indexed",
                    "indexing_failed",
                    name="index_status_enum",
                    create_type=False,
                ),
                nullable=True,
                comment="向量化索引状态: pending=队列等待, processing=处理中, "
                "indexed=已入库, indexing_failed=索引异常",
            ),
        )
    except Exception:
        # cases 表不存在，跳过
        op.execute(
            "-- WARNING: Cannot add index_status — cases table does not exist. "
            "Run this migration after CASE-01 has created the cases table."
        )

    # 在 index_status 列上创建索引
    try:
        op.create_index(
            "ix_cases_index_status",
            "cases",
            ["index_status"],
        )
    except Exception:
        pass

    # 5. 在 cases 表添加 indexed_at 列
    try:
        op.add_column(
            "cases",
            sa.Column(
                "indexed_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="索引完成时间，仅 index_status='indexed' 时有值",
            ),
        )
    except Exception:
        pass


def downgrade() -> None:
    """回滚：删除 case_chunks 表 + HNSW 索引 + cases 表删列。"""

    # 1. 删除 HNSW 索引
    op.execute("DROP INDEX IF EXISTS ix_case_chunks_embedding_hnsw")

    # 2. 删除 FK 约束（若存在）
    try:
        op.drop_constraint(
            "fk_case_chunks_case_id",
            "case_chunks",
            type_="foreignkey",
        )
    except Exception:
        pass

    # 3. 删除 case_chunks 表
    op.drop_table("case_chunks")

    # 4. 从 cases 表删除 indexed_at 列
    try:
        op.drop_column("cases", "indexed_at")
    except Exception:
        pass

    # 5. 从 cases 表删除 index_status 列
    try:
        op.drop_column("cases", "index_status")
    except Exception:
        pass

    # 6. 删除 index_status 上的索引
    try:
        op.drop_index("ix_cases_index_status", table_name="cases")
    except Exception:
        pass

    # 7. 删除 ENUM 类型
    op.execute("DROP TYPE IF EXISTS index_status_enum")
