"""CSLT-01: 创建 crisis_keywords 表。

Revision ID: 20260527_000007
Create Date: 2026-05-27 00:00:07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "20260527_000007"
down_revision: Union[str, None] = "20260527_000006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：创建 crisis_keywords 表 + 索引。"""

    op.create_table(
        "crisis_keywords",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            default=sa.text("gen_random_uuid()"),
            comment="UUID v4 主键",
        ),
        sa.Column(
            "keyword",
            sa.String(100),
            nullable=False,
            index=True,
            comment="关键词原文，长度不超过 100 字符",
        ),
        sa.Column(
            "category",
            sa.String(20),
            nullable=False,
            comment="关键词分类（severe / moderate / mild）",
        ),
        sa.Column(
            "trigger_rule_id",
            sa.String(50),
            nullable=False,
            comment="触发规则编号，如 KW_SELF_HARM_001",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="是否启用。仅加载 is_active=true 的记录",
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
            onupdate=sa.func.now(),
            nullable=False,
            comment="记录最后更新时间",
        ),
    )


def downgrade() -> None:
    """回滚：删除 crisis_keywords 表。"""

    op.drop_table("crisis_keywords")
