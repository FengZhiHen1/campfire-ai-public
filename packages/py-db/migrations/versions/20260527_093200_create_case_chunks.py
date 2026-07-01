"""CASE-04: 创建 case_chunks 表，添加向量化索引支持。

迁移内容：
1. 创建 case_chunks 表
2. 在 case_chunks.embedding 上创建 HNSW 索引（vector_cosine_ops）
3. 添加 FK 约束：case_chunks.case_id → cases.case_id

依赖说明：
    case_chunks 表的 FK 依赖 cases 表（由前置迁移创建）。

Revision ID: 20260527_093200
Create Date: 2026-05-27 09:32:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "20260527_093200"
down_revision: Union[str, None] = "20260527_000007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：创建 case_chunks 表 + HNSW 索引 + FK。"""

    # 开启 pgvector 扩展（幂等操作）
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ------------------------------------------------------------------
    # 1. 创建 case_chunks 表
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
            sa.String(20),
            sa.ForeignKey("cases.case_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
            comment="关联的案例标识，FK → cases.case_id",
        ),
        sa.Column(
            "chunk_text",
            sa.Text(),
            nullable=False,
            comment="四要素拼接文本（场景 + 行为 + 干预 + 结果）",
        ),
        sa.Column(
            "chunk_type",
            sa.String(20),
            nullable=True,
            comment="切片所属的案例四要素类型：scene / behavior / intervention / result",
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
    op.execute("ALTER TABLE case_chunks ALTER COLUMN embedding SET DEFAULT NULL::vector(1024)")

    # 2. 创建 HNSW 索引（cosine 距离）
    op.execute("CREATE INDEX ix_case_chunks_embedding_hnsw ON case_chunks USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    """回滚：删除 case_chunks 表 + HNSW 索引 + FK。"""

    # 1. 删除 HNSW 索引
    op.execute("DROP INDEX IF EXISTS ix_case_chunks_embedding_hnsw")

    # 2. 删除 case_chunks 表（FK 随表自动删除）
    op.drop_table("case_chunks")
